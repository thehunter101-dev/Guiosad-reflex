"""Prueba GeminiClient.embed contra la conversión real de contenidos del SDK (sin red)."""

from types import SimpleNamespace

import pytest
from google.genai import _transformers as t

from guiospro.services.ai_client import EMBED_BATCH, AIUnavailable, GeminiClient
from guiospro.settings import Settings


class SDKLikeModels:
    """Imita embed_content de google-genai para gemini-embedding-2:
    normaliza con ``t_contents`` (que fusiona cadenas sueltas en un único Content)
    y devuelve un vector por Content resultante."""

    def __init__(self):
        self.calls = 0

    def embed_content(self, model, contents, config):
        self.calls += 1
        normalized = t.t_contents(contents)
        return SimpleNamespace(
            embeddings=[SimpleNamespace(values=[float(i + 1), 0.0, 0.0]) for i in range(len(normalized))]
        )


@pytest.fixture
def client():
    c = GeminiClient(Settings(_env_file=None, gemini_api_key="clave-de-prueba"))
    c._client = SimpleNamespace(models=SDKLikeModels())
    return c


def test_sdk_merges_plain_strings():
    # Documenta la causa del fallo original: 3 cadenas -> 1 Content -> 1 vector.
    assert len(t.t_contents(["a", "b", "c"])) == 1


def test_embed_returns_one_vector_per_text(client):
    texts = [f"fragmento {i}" for i in range(EMBED_BATCH + 7)]
    vectors = client.embed(texts, "document")
    assert len(vectors) == len(texts)
    assert client._client.models.calls == 2  # lotes de 100 + 7
    assert all(abs(sum(x * x for x in v) - 1.0) < 1e-9 for v in vectors)  # normalizados


def test_embed_count_mismatch_raises(client):
    client._client.models.embed_content = lambda **_: SimpleNamespace(embeddings=[])
    with pytest.raises(AIUnavailable):
        client.embed(["a", "b"], "query")


# --- Cuota: control de ritmo y reintentos 429 -------------------------------

from google.genai import errors  # noqa: E402

from guiospro.services.ai_client import TokenRateLimiter, estimate_tokens, retry_delay  # noqa: E402


def _quota_error(delay: str = "43s") -> errors.ClientError:
    return errors.ClientError(429, {"error": {
        "code": 429, "status": "RESOURCE_EXHAUSTED",
        "message": "Embed content tokens per minute limit exceeded on Tier 1.",
        "details": [{"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": delay}],
    }})


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self):
        return self.now

    def sleep(self, s):
        self.sleeps.append(s)
        self.now += s


def test_retry_delay_parsing():
    assert retry_delay(_quota_error("43s")) == 43.0
    assert retry_delay(Exception("Please retry in 12.5s.")) == 12.5
    assert retry_delay(Exception("otro error")) is None


def test_rate_limiter_waits_for_window():
    clock = FakeClock()
    lim = TokenRateLimiter(1000, clock=clock, sleep=clock.sleep)
    lim.acquire(600)
    lim.acquire(400)
    assert clock.sleeps == []
    lim.acquire(500)  # no cabe: espera a que salga el primer evento de la ventana
    assert clock.sleeps == [60.0]
    lim.acquire(400)  # 500 + 400 <= 1000 tras expirar el lote de 400
    assert len(clock.sleeps) == 1


def test_rate_limiter_paces_large_volume():
    clock = FakeClock()
    lim = TokenRateLimiter(800_000, clock=clock, sleep=clock.sleep)
    for _ in range(20):  # 20 lotes de 100k = 2M tokens
        lim.acquire(100_000)
    assert clock.now >= 120.0  # al menos dos ventanas completas de espera


class FlakyModels(SDKLikeModels):
    def __init__(self, failures):
        super().__init__()
        self.failures = list(failures)

    def embed_content(self, model, contents, config):
        if self.failures:
            self.calls += 1
            raise self.failures.pop(0)
        return super().embed_content(model, contents, config)


def _client_with(models, **settings):
    clock = FakeClock()
    c = GeminiClient(Settings(_env_file=None, gemini_api_key="k", **settings), sleep=clock.sleep)
    c.limiter = TokenRateLimiter(10**9, clock=clock, sleep=clock.sleep)
    c._client = SimpleNamespace(models=models)
    return c, clock


def test_embed_retries_429_with_server_delay():
    c, clock = _client_with(FlakyModels([_quota_error("43s"), _quota_error("5s")]))
    msgs: list[str] = []
    assert len(c.embed(["a", "b"], "document", msgs.append)) == 2
    assert clock.sleeps[:2] == [44.0, 6.0]
    assert any("reintentando" in m for m in msgs)


def test_embed_gives_up_on_long_quota_delay():
    c, clock = _client_with(FlakyModels([_quota_error("3600s")]))
    with pytest.raises(AIUnavailable):
        c.embed(["a"], "document")
    assert clock.sleeps == []


def test_embed_gives_up_after_max_429_retries():
    c, clock = _client_with(FlakyModels([_quota_error("1s")] * 10), gemini_rate_limit_retries=3)
    with pytest.raises(AIUnavailable):
        c.embed(["a"], "document")
    assert len(clock.sleeps) == 3


def test_embed_does_not_retry_client_errors():
    bad = errors.ClientError(400, {"error": {"code": 400, "message": "bad", "status": "INVALID_ARGUMENT"}})
    c, clock = _client_with(FlakyModels([bad]))
    with pytest.raises(AIUnavailable):
        c.embed(["a"], "document")
    assert clock.sleeps == []


def test_estimate_tokens_is_conservative():
    assert estimate_tokens("x" * 3000) == 1000
