"""Cliente Google AI (Gemini) con Structured Outputs y embeddings.

- Controla el ritmo de los embeddings para no superar el límite de tokens por minuto.
- Reintenta los errores 429 respetando el ``retryDelay`` que indica la API, y los 5xx
  con espera exponencial.
- Cualquier fallo definitivo (sin clave, red, cuota, respuesta inválida) se traduce en
  ``AIUnavailable`` para que la capa de estado conmute a modo manual (RF-AUTO-10).
"""

import asyncio
import json
import math
import re
import threading
import time
from collections import deque
from collections.abc import Callable
from typing import Literal, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from ..settings import Settings, get_settings

T = TypeVar("T", bound=BaseModel)
EMBED_BATCH = 100
# Estimación conservadora de tokens por carácter (código y texto mixto).
CHARS_PER_TOKEN = 3.0
# Si la API pide esperar más que esto, la cuota es diaria o similar: no se reintenta.
MAX_RETRY_DELAY = 120.0

Notify = Callable[[str], None]


class AIUnavailable(RuntimeError):
    """La capa de IA no está disponible o devolvió una respuesta inutilizable."""


class AIClient(Protocol):
    def generate_json(self, model: str, system_instruction: str, content: str, schema: type[T]) -> T: ...

    async def agenerate_json(
        self, model: str, system_instruction: str, content: str, schema: type[T]
    ) -> T: ...

    def embed(
        self, texts: list[str], kind: Literal["query", "document"], progress: Notify | None = None
    ) -> list[list[float]]: ...


# --- Utilidades -------------------------------------------------------------

def estimate_tokens(text: str) -> int:
    return max(1, math.ceil(len(text) / CHARS_PER_TOKEN))


def _normalize(v: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def _embedding_input(text: str, kind: str) -> str:
    # gemini-embedding-2 usa prefijos de tarea en el texto en lugar de task_type.
    if kind == "query":
        return f"task: search result | query: {text}"
    return f"title: none | text: {text}"


_RETRY_PATTERNS = (
    re.compile(r"retryDelay['\"]?\s*:\s*['\"]?(\d+(?:\.\d+)?)s"),
    re.compile(r"retry in (\d+(?:\.\d+)?)\s*s", re.IGNORECASE),
)


def error_code(exc: BaseException) -> int | None:
    code = getattr(exc, "code", None)
    return code if isinstance(code, int) else None


def retry_delay(exc: BaseException) -> float | None:
    """Segundos de espera sugeridos por la API en un error 429 (o ``None``)."""
    text = str(exc)
    details = getattr(exc, "details", None)
    if details:
        text += " " + str(details)
    for pattern in _RETRY_PATTERNS:
        m = pattern.search(text)
        if m:
            return float(m.group(1))
    return None


def is_retryable(exc: BaseException) -> bool:
    """429 y 5xx se reintentan; también errores de red (sin código HTTP)."""
    code = error_code(exc)
    if code is None:
        return not isinstance(exc, (ValidationError, ValueError, AIUnavailable))
    return code == 429 or code >= 500


def backoff_seconds(exc: BaseException, attempt: int) -> float:
    if error_code(exc) == 429:
        delay = retry_delay(exc)
        return (delay if delay is not None else 30.0) + 1.0
    return float(min(2**attempt, 16))


class TokenRateLimiter:
    """Ventana deslizante de 60 s: bloquea hasta que el lote quepa en el límite por minuto."""

    def __init__(
        self,
        limit_per_minute: int,
        window: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.limit = limit_per_minute
        self.window = window
        self._clock = clock
        self._sleep = sleep
        self._events: deque[tuple[float, int]] = deque()
        self._lock = threading.Lock()

    def _used(self, now: float) -> int:
        while self._events and now - self._events[0][0] >= self.window:
            self._events.popleft()
        return sum(t for _, t in self._events)

    def acquire(self, tokens: int, notify: Notify | None = None) -> float:
        """Reserva ``tokens``; devuelve los segundos esperados."""
        tokens = min(tokens, self.limit)  # Un lote mayor que el límite pasa solo en una ventana vacía.
        waited = 0.0
        while True:
            with self._lock:
                now = self._clock()
                used = self._used(now)
                if used + tokens <= self.limit:
                    self._events.append((now, tokens))
                    return waited
                # Espera a que salga de la ventana el evento más antiguo.
                wait = max(0.05, self.window - (now - self._events[0][0]))
            if notify:
                notify(f"Esperando cuota de embeddings ({wait:.0f} s)…")
            self._sleep(wait)
            waited += wait

    def penalize(self, seconds: float) -> None:
        """Tras un 429, bloquea la cuota durante ``seconds`` (también para otros hilos)."""
        with self._lock:
            now = self._clock()
            # Evento que llena la ventana y expira exactamente dentro de ``seconds``.
            self._events.appendleft((now - (self.window - seconds), self.limit))


_LIMITERS: dict[tuple[str, int], TokenRateLimiter] = {}
_LIMITERS_LOCK = threading.Lock()


def shared_limiter(model: str, limit: int) -> TokenRateLimiter:
    """La cuota es por proyecto y modelo: un limitador compartido por proceso."""
    with _LIMITERS_LOCK:
        key = (model, limit)
        if key not in _LIMITERS:
            _LIMITERS[key] = TokenRateLimiter(limit)
        return _LIMITERS[key]


# --- Cliente ----------------------------------------------------------------

class GeminiClient:
    def __init__(self, settings: Settings | None = None, sleep: Callable[[float], None] = time.sleep):
        self.settings = settings or get_settings()
        if not self.settings.ai_enabled:
            raise AIUnavailable("GEMINI_API_KEY no está configurada.")
        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:  # pragma: no cover
            raise AIUnavailable("El paquete google-genai no está instalado.") from exc
        self._types = types
        self._sleep = sleep
        self._client = genai.Client(
            api_key=self.settings.gemini_api_key,
            http_options=types.HttpOptions(timeout=self.settings.gemini_timeout_seconds * 1000),
        )
        self.limiter = shared_limiter(
            self.settings.gemini_embedding_model, self.settings.gemini_embed_tpm_limit
        )

    @property
    def _attempts(self) -> int:
        return max(self.settings.gemini_max_retries, self.settings.gemini_rate_limit_retries) + 1

    def _should_retry(self, exc: BaseException, attempt: int) -> bool:
        if attempt + 1 >= self._attempts:
            return False
        if error_code(exc) == 429:
            delay = retry_delay(exc)
            return attempt < self.settings.gemini_rate_limit_retries and (delay is None or delay <= MAX_RETRY_DELAY)
        return attempt < self.settings.gemini_max_retries and is_retryable(exc)

    # --- Generación estructurada --------------------------------------------

    def _config(self, system_instruction: str, schema: type[BaseModel]):
        return self._types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=self.settings.gemini_temperature,
            response_mime_type="application/json",
            response_json_schema=schema.model_json_schema(),
        )

    @staticmethod
    def _parse(text: str | None, schema: type[T]) -> T:
        if not text:
            raise ValueError("Respuesta vacía del modelo.")
        return schema.model_validate(json.loads(text))

    def generate_json(self, model: str, system_instruction: str, content: str, schema: type[T]) -> T:
        last: Exception | None = None
        for attempt in range(self._attempts):
            try:
                resp = self._client.models.generate_content(
                    model=model, contents=content, config=self._config(system_instruction, schema)
                )
                return self._parse(resp.text, schema)
            except (ValidationError, ValueError) as exc:  # JSON inválido: reintento inmediato
                last = exc
                if attempt >= self.settings.gemini_max_retries:
                    break
            except Exception as exc:
                last = exc
                if not self._should_retry(exc, attempt):
                    break
                self._sleep(backoff_seconds(exc, attempt))
        raise AIUnavailable(f"Fallo de Google AI ({model}): {last}") from last

    async def agenerate_json(
        self, model: str, system_instruction: str, content: str, schema: type[T]
    ) -> T:
        last: Exception | None = None
        for attempt in range(self._attempts):
            try:
                resp = await self._client.aio.models.generate_content(
                    model=model, contents=content, config=self._config(system_instruction, schema)
                )
                return self._parse(resp.text, schema)
            except (ValidationError, ValueError) as exc:
                last = exc
                if attempt >= self.settings.gemini_max_retries:
                    break
            except Exception as exc:
                last = exc
                if not self._should_retry(exc, attempt):
                    break
                await asyncio.sleep(backoff_seconds(exc, attempt))
        raise AIUnavailable(f"Fallo de Google AI ({model}): {last}") from last

    # --- Embeddings ---------------------------------------------------------

    def _embed_batch(self, inputs: list[str], config, notify: Notify | None) -> list[list[float]]:
        # Un Content por texto: con gemini-embedding-2 el SDK fusiona una lista de
        # cadenas en un único Content y la API devolvería un solo vector agregado.
        contents = [self._types.Content(parts=[self._types.Part(text=x)]) for x in inputs]
        tokens = sum(estimate_tokens(x) for x in inputs)
        last: Exception | None = None
        for attempt in range(self._attempts):
            self.limiter.acquire(tokens, notify)
            try:
                resp = self._client.models.embed_content(
                    model=self.settings.gemini_embedding_model, contents=contents, config=config
                )
            except Exception as exc:
                last = exc
                if not self._should_retry(exc, attempt):
                    break
                wait = backoff_seconds(exc, attempt)
                if error_code(exc) == 429:
                    # La espera la aplica el limitador en el próximo ``acquire``.
                    self.limiter.penalize(wait)
                    if notify:
                        notify(f"Límite de cuota alcanzado: reintentando en {wait:.0f} s…")
                else:
                    self._sleep(wait)
                continue
            vectors = [_normalize(list(e.values or [])) for e in (resp.embeddings or [])]
            if len(vectors) != len(inputs):
                raise AIUnavailable("La API de embeddings devolvió un número inesperado de vectores.")
            return vectors
        raise AIUnavailable(f"Fallo al generar embeddings: {last}") from last

    def embed(
        self, texts: list[str], kind: Literal["query", "document"], progress: Notify | None = None
    ) -> list[list[float]]:
        config = self._types.EmbedContentConfig(output_dimensionality=self.settings.gemini_embedding_dim)
        out: list[list[float]] = []
        for i in range(0, len(texts), EMBED_BATCH):
            inputs = [_embedding_input(t, kind) for t in texts[i : i + EMBED_BATCH]]
            out.extend(self._embed_batch(inputs, config, progress))
        return out


def get_ai_client() -> GeminiClient:
    """Crea el cliente o lanza ``AIUnavailable``."""
    return GeminiClient()
