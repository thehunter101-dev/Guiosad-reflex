"""Núcleo determinista GUIOS: IR, filtro IR > 1, PM_i, FODA y dictamen A/B/C."""

from collections import Counter
from collections.abc import Iterable

from .constants import (
    FODA_NEGATIVOS,
    FODA_POSITIVOS,
    IMPORTANT_LEVEL,
    SCORE_DESCONOZCO,
    UMBRAL_CONFIANZA_IA,
    UMBRAL_FODA,
    AlcanceAplicado,
    Dictamen,
    Foda,
    cartesian,
)
from .schemas import (
    EvaluacionInput,
    FactorResultado,
    ResultadoEvaluacion,
    SubfactorAISuggestion,
    SubfactorPropuesta,
)


# --- Pasos 1 y 2 ------------------------------------------------------------

def relative_importance(id_decisor: int, is_: int) -> int:
    """IR = M(ID, IS)."""
    return cartesian(id_decisor, is_)


def is_relevant(ir: int) -> bool:
    return ir > 1


# --- Pasos 3 y 4 ------------------------------------------------------------

def ponderacion_media(scores: list[int]) -> float:
    if not scores:
        raise ValueError("No hay subfactores puntuados.")
    return sum(scores) / len(scores)


# --- Paso 5 -----------------------------------------------------------------

def classify_foda(pm: float, alcance: AlcanceAplicado) -> Foda:
    favorable = pm >= UMBRAL_FODA
    if alcance == AlcanceAplicado.INTERNO:
        return Foda.FORTALEZA if favorable else Foda.DEBILIDAD
    return Foda.OPORTUNIDAD if favorable else Foda.AMENAZA


# --- Paso 6 -----------------------------------------------------------------

def dictamen_base(evaluados: Iterable[tuple[int, Foda]]) -> Dictamen | None:
    """Dictamen sobre pares (IR, FODA) de factores relevantes evaluados.

    - C: alguna Debilidad/Amenaza con IR >= 3, o negativos > positivos.
    - B: hay Debilidades/Amenazas, todas con IR = 2.
    - A: cero Debilidades y cero Amenazas.
    """
    pares = [(ir, foda) for ir, foda in evaluados if foda != Foda.EXCLUIDO]
    if not pares:
        return None
    negativos = [ir for ir, foda in pares if foda in FODA_NEGATIVOS]
    positivos = sum(1 for _, foda in pares if foda in FODA_POSITIVOS)
    if any(ir >= IMPORTANT_LEVEL for ir in negativos) or len(negativos) > positivos:
        return Dictamen.C
    if negativos:
        return Dictamen.B
    return Dictamen.A


def evaluate(data: EvaluacionInput) -> ResultadoEvaluacion:
    resultados: list[FactorResultado] = []
    for f in data.factores:
        ir = relative_importance(f.id_decisor, f.is_aplicado)
        relevante = is_relevant(ir)
        pm = foda = None
        pendiente = False
        if not relevante:
            foda = Foda.EXCLUIDO
        elif not f.scores or any(s is None for s in f.scores):
            pendiente = True
        else:
            pm = ponderacion_media([s for s in f.scores if s is not None])
            foda = classify_foda(pm, f.alcance)
        resultados.append(
            FactorResultado(
                factor_id=f.factor_id,
                nombre=f.nombre,
                is_aplicado=f.is_aplicado,
                id_decisor=f.id_decisor,
                ir=ir,
                alcance=f.alcance,
                es_relevante=relevante,
                pendiente=pendiente,
                pm=pm,
                foda=foda,
            )
        )

    evaluados = [(r.ir, r.foda) for r in resultados if r.es_relevante and r.foda]
    pendientes = sum(r.pendiente for r in resultados)
    relevantes = sum(r.es_relevante for r in resultados)
    provisional = dictamen_base(evaluados)
    conteo = Counter(r.foda for r in resultados if r.foda)
    return ResultadoEvaluacion(
        factores=resultados,
        relevantes=relevantes,
        pendientes=pendientes,
        conteo_foda={f: conteo.get(f, 0) for f in Foda},
        dictamen=provisional if pendientes == 0 else None,
        dictamen_provisional=provisional,
    )


# --- Regla de fallback de la pre-evaluación IA -----------------------------

def apply_ai_fallback(s: SubfactorAISuggestion) -> SubfactorPropuesta:
    """Sin citas o con confianza < 0.45 → score 2 ("Desconozco") y revisión prioritaria."""
    if not s.citas or s.nivel_confianza < UMBRAL_CONFIANZA_IA:
        return SubfactorPropuesta(
            **s.model_dump(exclude={"score_ia"}), score_ia=SCORE_DESCONOZCO, requiere_revision=True
        )
    return SubfactorPropuesta(**s.model_dump(), requiere_revision=False)
