"""Calibración bibliográfica: r_i = c_i / n_i, cuartiles → IL, y IS = M(IE, IL)."""

import statistics

from .constants import IE_FIJO, cartesian
from .schemas import CalibracionFactorInput, CalibracionFactorResultado, CalibracionResultado


def ratio(citas: int, subfactores_activos: int) -> float:
    if subfactores_activos <= 0:
        raise ValueError("El factor no tiene subfactores activos (n_i = 0).")
    return citas / subfactores_activos


def quartiles(values: list[float]) -> tuple[float, float, float]:
    """Q1, Q2, Q3 con ``statistics.quantiles(n=4)`` (método por defecto: exclusive)."""
    if len(values) < 2:
        raise ValueError("Se necesitan al menos 2 factores para calcular cuartiles.")
    q1, q2, q3 = statistics.quantiles(values, n=4)
    return q1, q2, q3


def il_from_ratio(r: float, q: tuple[float, float, float]) -> int:
    q1, q2, q3 = q
    if r <= q1:
        return 1
    if r <= q2:
        return 2
    if r <= q3:
        return 3
    return 4


def suggested_importance(il: int, ie: int = IE_FIJO) -> int:
    """IS = M(IE, IL)."""
    return cartesian(ie, il)


def calibrate(factores: list[CalibracionFactorInput], ie: int = IE_FIJO) -> CalibracionResultado:
    ratios = [ratio(f.citas_pertinentes, f.subfactores_activos) for f in factores]
    q = quartiles(ratios)
    resultados = []
    for f, r in zip(factores, ratios):
        il = il_from_ratio(r, q)
        resultados.append(
            CalibracionFactorResultado(
                **f.model_dump(),
                ratio_normalizado=r,
                il_calculado=il,
                ie_fijo=ie,
                is_calculado=suggested_importance(il, ie),
            )
        )
    return CalibracionResultado(q1=q[0], q2=q[1], q3=q[2], factores=resultados)
