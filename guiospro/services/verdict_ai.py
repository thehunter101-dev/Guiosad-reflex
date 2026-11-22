"""Dictamen ejecutivo y plan de mitigación FODA (RF-AUTO-07/08).

El LLM redacta, pero NUNCA decide: ``dictamen_base`` siempre es el calculado por
``core.evaluator`` y el plan solo puede referirse a Debilidades/Amenazas reales.
"""

import json

from pydantic import BaseModel, Field

from ..core.constants import DICTAMEN_CODIGO, DICTAMEN_TEXTO, FODA_NEGATIVOS, Foda, importance_label
from ..core.schemas import PlanAccionItem, VerdictRequest, VerdictResponse
from ..settings import get_settings
from .ai_client import AIClient, AIUnavailable
from .sanitizer import UNTRUSTED_NOTICE, sanitize_untrusted, wrap_untrusted

MANUAL_MODEL = "determinista (sin IA)"


class _LLMPlanItem(BaseModel):
    factor_id: int
    accion: str
    prioridad: str = Field(description="Alta, Media o Baja")


class _LLMVerdict(BaseModel):
    resumen_ejecutivo: str
    plan_accion: list[_LLMPlanItem] = Field(default_factory=list)


SYSTEM_INSTRUCTION = f"""Eres consultor senior en adopción de software libre (metodología GUIOS).
Recibes un resultado YA CALCULADO de forma determinista. Tu tarea:
1. Redactar un resumen ejecutivo (3-6 párrafos, español formal) que justifique el dictamen
   base recibido, contextualizado a la organización, citando factores, IR, PM y FODA.
2. Proponer acciones técnicas u organizacionales concretas para mitigar CADA Debilidad y
   Amenaza (al menos una por factor), con prioridad Alta/Media/Baja.
Prohibido: cambiar, cuestionar o contradecir el dictamen base; inventar factores o datos.
{UNTRUSTED_NOTICE}"""


def _negatives(req: VerdictRequest) -> dict[int, tuple[str, Foda, int]]:
    return {
        f.factor_id: (f.nombre, f.foda, f.ir)
        for f in req.resultado.factores
        if f.es_relevante and f.foda in FODA_NEGATIVOS
    }


def _priority(ir: int) -> str:
    return "Alta" if ir >= 4 else "Media" if ir == 3 else "Baja"


def _build_prompt(req: VerdictRequest) -> str:
    r = req.resultado
    factores = [
        {
            "factor_id": f.factor_id,
            "factor": f.nombre,
            "IS": f.is_aplicado,
            "ID": f.id_decisor,
            "IR": f"{f.ir} ({importance_label(f.ir)})",
            "alcance": f.alcance.value,
            "PM": round(f.pm, 2) if f.pm is not None else None,
            "FODA": f.foda.value if f.foda else None,
        }
        for f in r.factores
    ]
    evid = "\n".join(
        wrap_untrusted(
            f"Afirmación: {e.afirmacion}\nPuntaje validado: {e.score_evaluador}\n"
            f"Observación: {e.observacion or '-'}\n"
            + "\n".join(f"Cita {c.archivo} ({c.ubicacion}): {c.fragmento}" for c in e.citas),
            factor_id=e.factor_id,
        )
        for e in req.evidencias[:80]
    )
    return (
        f"Software: {sanitize_untrusted(req.nombre_software)} {sanitize_untrusted(req.version or '')}\n"
        f"Organización: {sanitize_untrusted(req.organizacion or 'no especificada')}\n"
        f"DICTAMEN BASE (inmutable): Tipo {r.dictamen.value} — {DICTAMEN_CODIGO[r.dictamen]}\n"
        f"Conteo FODA: {json.dumps({k.value: v for k, v in r.conteo_foda.items()}, ensure_ascii=False)}\n"
        f"Factores:\n{json.dumps(factores, ensure_ascii=False, indent=1)}\n\n"
        f"Evidencias validadas por el evaluador:\n{evid or '(sin evidencias técnicas)'}"
    )


def manual_verdict(req: VerdictRequest) -> VerdictResponse:
    """Dictamen determinista para modo manual o cuando falla la IA."""
    if req.resultado.dictamen is None:
        raise ValueError("El dictamen requiere todos los factores relevantes evaluados.")
    plan = [
        PlanAccionItem(
            factor_id=fid,
            factor_nombre=name,
            tipo_foda=foda.value,
            accion=(
                f"Definir un plan de mejora interna para «{name}» (capacitación, procesos o recursos)."
                if foda == Foda.DEBILIDAD
                else f"Asignar recursos de ingeniería o proveedores para mitigar «{name}» en el software."
            ),
            prioridad=_priority(ir),
        )
        for fid, (name, foda, ir) in _negatives(req).items()
    ]
    return VerdictResponse(
        dictamen_base=req.resultado.dictamen,
        resumen_ejecutivo=DICTAMEN_TEXTO[req.resultado.dictamen],
        plan_accion=plan,
    )


def generate_verdict(req: VerdictRequest, client: AIClient) -> VerdictResponse:
    if req.resultado.dictamen is None:
        raise ValueError("El dictamen requiere todos los factores relevantes evaluados.")
    llm = client.generate_json(
        get_settings().gemini_model_dictamen, SYSTEM_INSTRUCTION, _build_prompt(req), _LLMVerdict
    )
    negatives = _negatives(req)
    plan: list[PlanAccionItem] = []
    for item in llm.plan_accion:
        if item.factor_id not in negatives:
            continue  # El LLM no puede introducir factores que no son negativos.
        name, foda, ir = negatives[item.factor_id]
        prioridad = item.prioridad.capitalize() if item.prioridad.capitalize() in {"Alta", "Media", "Baja"} else _priority(ir)
        plan.append(
            PlanAccionItem(factor_id=item.factor_id, factor_nombre=name, tipo_foda=foda.value,
                           accion=item.accion.strip(), prioridad=prioridad)
        )
    # Garantiza al menos una acción por cada Debilidad/Amenaza.
    covered = {p.factor_id for p in plan}
    plan += [p for p in manual_verdict(req).plan_accion if p.factor_id not in covered]
    if not llm.resumen_ejecutivo.strip():
        raise AIUnavailable("El modelo devolvió un resumen vacío.")
    return VerdictResponse(
        dictamen_base=req.resultado.dictamen,  # Siempre el del núcleo.
        resumen_ejecutivo=llm.resumen_ejecutivo.strip(),
        plan_accion=plan,
    )
