"""Pre-evaluación de subfactores con RAG + Gemini (RF-AUTO-04..06).

Solo se evalúan subfactores activos de factores relevantes (IR > 1). Cada cita se
verifica contra los fragmentos recuperados; las citas que no aparecen se descartan
y después se aplica la regla de fallback del núcleo (score 2 si no hay evidencia).
"""

import re
from collections.abc import Callable
from dataclasses import dataclass

from pydantic import BaseModel, Field
from sqlmodel import Session

from ..core.evaluator import apply_ai_fallback
from ..core.schemas import CitationItem, SubfactorAISuggestion, SubfactorPropuesta
from ..models import repository as repo
from ..models.database import DocumentoChunk
from ..settings import get_settings
from .ai_client import AIClient
from .repo_ingestor import STATIC_REPORT_PATH
from .sanitizer import UNTRUSTED_NOTICE, sanitize_untrusted, wrap_untrusted

MAX_CONTEXT_CHARS = 60_000


# --- Esquema de respuesta del modelo ---------------------------------------

class _LLMCita(BaseModel):
    chunk_id: int = Field(description="Identificador del fragmento citado (atributo id)")
    archivo: str
    ubicacion: str
    fragmento: str = Field(description="Texto copiado literalmente del fragmento")


class _LLMSugerencia(BaseModel):
    subfactor_id: int
    score_ia: int = Field(ge=1, le=4)
    nivel_confianza: float = Field(ge=0.0, le=1.0)
    justificacion: str
    citas: list[_LLMCita] = Field(default_factory=list)


class _LLMRespuesta(BaseModel):
    evaluaciones: list[_LLMSugerencia]


SYSTEM_INSTRUCTION = f"""Eres un auditor técnico de software libre que aplica la metodología GUIOS.
Para cada subfactor (una afirmación sobre el software) asigna un puntaje de cumplimiento:
1 = No cumple el requisito; 2 = Desconozco si cumple el requisito; 3 = Cumple parcialmente; 4 = Cumple.
Reglas obligatorias:
- Basa cada puntaje 1, 3 o 4 EXCLUSIVAMENTE en los fragmentos proporcionados y cítalos.
- Cada cita debe copiar LITERALMENTE un fragmento breve (máx. 300 caracteres) del texto del
  fragmento indicado por chunk_id, con su archivo y ubicación.
- Si no hay evidencia suficiente, o el subfactor depende de información interna de la
  organización, responde 2 con nivel_confianza bajo y sin citas.
- nivel_confianza (0..1) refleja cuán concluyente es la evidencia.
- Justificación breve en español.
{UNTRUSTED_NOTICE}"""


@dataclass
class PrefillStats:
    evaluados: int = 0
    con_evidencia: int = 0
    revision_prioritaria: int = 0
    fragmentos_con_embedding: int = 0  # Contexto RAG disponible (sin contar el análisis estático).


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def verify_citations(citas: list[_LLMCita], context: dict[int, DocumentoChunk]) -> list[CitationItem]:
    """Conserva solo citas cuyo fragmento existe literalmente en el chunk referido."""
    valid: list[CitationItem] = []
    for c in citas:
        chunk = context.get(c.chunk_id)
        frag = _norm(c.fragmento)
        if chunk is None or len(frag) < 8 or frag not in _norm(chunk.contenido_texto):
            continue
        valid.append(
            CitationItem(
                archivo=chunk.ruta_archivo,
                ubicacion=chunk.ubicacion or c.ubicacion,
                fragmento=c.fragmento.strip()[:1000],
            )
        )
    return valid


def _build_prompt(factor: str, subfactores: list[tuple[int, str, str]], context: list[DocumentoChunk]) -> str:
    subs = "\n".join(
        f"- subfactor_id={sid}: «{afirmacion}» (guía: {guia or 'n/d'})" for sid, afirmacion, guia in subfactores
    )
    parts, size = [], 0
    for c in context:
        block = wrap_untrusted(c.contenido_texto, id=c.id or 0, archivo=c.ruta_archivo, ubicacion=c.ubicacion or "")
        if size + len(block) > MAX_CONTEXT_CHARS:
            break
        parts.append(block)
        size += len(block)
    return (
        f"Factor GUIOS: {sanitize_untrusted(factor)}\n\nSubfactores a evaluar:\n{subs}\n\n"
        f"Fragmentos recuperados del repositorio y la documentación:\n\n" + "\n\n".join(parts)
        + "\n\nDevuelve una evaluación por cada subfactor_id listado."
    )


def prefill(
    session: Session,
    evaluacion_id: int,
    client: AIClient,
    progress: Callable[[str], None] | None = None,
) -> PrefillStats:
    """Ejecuta la pre-evaluación y persiste propuestas + evidencias.

    Lanza ``AIUnavailable`` si la API falla; lo ya guardado se conserva.
    """
    settings = get_settings()
    notify = progress or (lambda _m: None)
    stats = PrefillStats()
    embedded, _ = repo.embedding_stats(session, evaluacion_id)
    stats.fragmentos_con_embedding = max(0, embedded - 1)
    static_chunks = [
        c for c in repo.chunks_by_category(session, evaluacion_id, "configuracion")
        if c.ruta_archivo == STATIC_REPORT_PATH
    ]

    names = {ef.id: f.nombre for ef, f, _ in repo.evaluation_factors(session, evaluacion_id)}
    by_factor: dict[int, tuple[str, list]] = {}
    for es, sub, ef in repo.evaluation_subfactors(session, evaluacion_id):
        if ef.es_relevante and sub.subfactor_activo:
            by_factor.setdefault(ef.id, (names[ef.id], []))[1].append((es, sub))

    total = len(by_factor)
    for n, (_, (factor_name, items)) in enumerate(by_factor.items(), start=1):
        notify(f"Pre-evaluando «{factor_name}» ({n}/{total})…")
        queries = [f"{sub.afirmacion}. {sub.guia_verificacion or ''}" for _, sub in items]
        vectors = client.embed(queries, "query", notify)
        context: dict[int, DocumentoChunk] = {c.id: c for c in static_chunks}
        for v in vectors:
            for c in repo.search_chunks(session, evaluacion_id, v, settings.rag_top_k):
                context.setdefault(c.id, c)

        prompt = _build_prompt(
            factor_name, [(sub.id, sub.afirmacion, sub.guia_verificacion) for _, sub in items], list(context.values())
        )
        resp = client.generate_json(settings.gemini_model_evaluacion, SYSTEM_INSTRUCTION, prompt, _LLMRespuesta)
        answers = {a.subfactor_id: a for a in resp.evaluaciones}

        for es, sub in items:
            a = answers.get(sub.id)
            suggestion = SubfactorAISuggestion(
                subfactor_id=sub.id,
                score_ia=a.score_ia if a else 2,
                nivel_confianza=a.nivel_confianza if a else 0.0,
                justificacion=(a.justificacion if a else "El modelo no devolvió evaluación para este subfactor."),
                citas=verify_citations(a.citas, context) if a else [],
            )
            propuesta: SubfactorPropuesta = apply_ai_fallback(suggestion)
            repo.save_ai_proposal(session, es.id, propuesta)
            stats.evaluados += 1
            stats.con_evidencia += bool(propuesta.citas)
            stats.revision_prioritaria += propuesta.requiere_revision
        session.commit()  # Persistencia incremental por factor.

    repo.recompute(session, evaluacion_id)
    session.commit()
    return stats
