import ast
from pathlib import Path

import pytest
from pydantic import ValidationError

from guiospro.core.calibration import calibrate, il_from_ratio, quartiles, ratio
from guiospro.core.catalog import get_catalog
from guiospro.core.constants import (
    CARTESIAN_MATRIX,
    Alcance,
    AlcanceAplicado,
    Dictamen,
    Foda,
    cartesian,
)
from guiospro.core.evaluator import (
    apply_ai_fallback,
    classify_foda,
    dictamen_base,
    evaluate,
    is_relevant,
    ponderacion_media,
    relative_importance,
)
from guiospro.core.schemas import (
    CalibracionFactorInput,
    CitationItem,
    EvaluacionInput,
    FactorInput,
    SubfactorAISuggestion,
)

CORE_DIR = Path(__file__).resolve().parent.parent / "guiospro" / "core"
FORBIDDEN = {"reflex", "google", "sqlmodel", "sqlalchemy", "httpx"}


def test_core_is_pure_python():
    for py in CORE_DIR.glob("*.py"):
        tree = ast.parse(py.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                names = [node.module or ""]
            for n in names:
                assert n.split(".")[0] not in FORBIDDEN, f"{py.name} importa {n}"


# --- Catálogo ---------------------------------------------------------------

def test_catalog_shape():
    c = get_catalog()
    assert len(c.factors) == 18
    assert c.subfactor_count == 61
    assert c.dimensions == ["Tecnológica", "Organizacional", "Económica"]
    scopes = [f.scope for f in c.factors]
    assert scopes.count(Alcance.INTERNO) == 6
    assert scopes.count(Alcance.EXTERNO) == 11
    configurable = [f.name for f in c.factors if f.scope == Alcance.CONFIGURABLE]
    assert configurable == ["Soporte"]
    codes = [s.codigo for f in c.factors for s in f.subfactors]
    assert len(set(codes)) == 61
    assert all(f.cadena_busqueda for f in c.factors)


# --- Matriz -----------------------------------------------------------------

@pytest.mark.parametrize(("key", "expected"), CARTESIAN_MATRIX.items())
def test_cartesian_matrix(key, expected):
    assert cartesian(*key) == expected


def test_cartesian_out_of_range():
    with pytest.raises(ValueError):
        cartesian(0, 5)


def test_relative_importance_and_relevance():
    assert relative_importance(1, 2) == 1 and not is_relevant(1)
    assert relative_importance(4, 1) == 2 and is_relevant(2)
    assert relative_importance(4, 4) == 4


# --- Calibración ------------------------------------------------------------

def test_ratio_requires_active_subfactors():
    assert ratio(10, 4) == 2.5
    with pytest.raises(ValueError):
        ratio(3, 0)


def test_quartiles_exclusive_default():
    assert quartiles([1, 2, 3, 4, 5, 6, 7]) == (2.0, 4.0, 6.0)


def test_il_boundaries():
    q = (1.0, 2.0, 3.0)
    assert [il_from_ratio(r, q) for r in (0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.1)] == [1, 1, 2, 2, 3, 3, 4]


def test_calibrate_assigns_il_and_is():
    data = [CalibracionFactorInput(factor_id=i, citas_pertinentes=c, subfactores_activos=1)
            for i, c in enumerate([1, 2, 3, 4, 5, 6, 7, 8])]
    res = calibrate(data)
    ils = [f.il_calculado for f in res.factores]
    assert ils == [1, 1, 2, 2, 3, 3, 4, 4]
    # IS = M(3, IL)
    assert [f.is_calculado for f in res.factores] == [2, 2, 2, 2, 3, 3, 3, 3]
    assert all(f.ie_fijo == 3 for f in res.factores)


# --- PM, FODA y dictamen ----------------------------------------------------

def test_pm_and_foda():
    assert ponderacion_media([1, 2, 3, 4]) == 2.5
    with pytest.raises(ValueError):
        ponderacion_media([])
    assert classify_foda(3.0, AlcanceAplicado.INTERNO) == Foda.FORTALEZA
    assert classify_foda(2.99, AlcanceAplicado.INTERNO) == Foda.DEBILIDAD
    assert classify_foda(3.0, AlcanceAplicado.EXTERNO) == Foda.OPORTUNIDAD
    assert classify_foda(1.0, AlcanceAplicado.EXTERNO) == Foda.AMENAZA


def test_dictamen_rules():
    assert dictamen_base([]) is None
    assert dictamen_base([(3, Foda.FORTALEZA), (2, Foda.OPORTUNIDAD)]) == Dictamen.A
    assert dictamen_base([(3, Foda.FORTALEZA), (3, Foda.OPORTUNIDAD), (2, Foda.DEBILIDAD)]) == Dictamen.B
    assert dictamen_base([(3, Foda.FORTALEZA), (3, Foda.AMENAZA)]) == Dictamen.C
    # Negativos > positivos aunque todos sean Opcionales -> C.
    assert dictamen_base([(4, Foda.FORTALEZA), (2, Foda.DEBILIDAD), (2, Foda.AMENAZA)]) == Dictamen.C
    # Empate negativos = positivos con IR=2 -> B.
    assert dictamen_base([(4, Foda.FORTALEZA), (2, Foda.DEBILIDAD)]) == Dictamen.B
    # Los excluidos no cuentan.
    assert dictamen_base([(1, Foda.EXCLUIDO), (3, Foda.FORTALEZA)]) == Dictamen.A


def _factor(fid, is_, id_, alcance, scores):
    return FactorInput(factor_id=fid, nombre=f"F{fid}", is_aplicado=is_, id_decisor=id_,
                       alcance=alcance, scores=scores)


def test_evaluate_pending_blocks_final_dictamen():
    data = EvaluacionInput(factores=[
        _factor(1, 3, 3, AlcanceAplicado.INTERNO, [4, 4]),
        _factor(2, 3, 3, AlcanceAplicado.EXTERNO, [4, None]),
        _factor(3, 2, 1, AlcanceAplicado.EXTERNO, [1]),  # IR=1 -> excluido
    ])
    res = evaluate(data)
    assert res.relevantes == 2 and res.pendientes == 1
    assert res.dictamen is None
    assert res.dictamen_provisional == Dictamen.A
    assert res.factores[2].foda == Foda.EXCLUIDO and not res.factores[2].es_relevante


def test_evaluate_complete():
    data = EvaluacionInput(factores=[
        _factor(1, 3, 3, AlcanceAplicado.INTERNO, [4, 3]),
        _factor(2, 2, 2, AlcanceAplicado.EXTERNO, [1, 2]),
    ])
    res = evaluate(data)
    assert res.factores[0].pm == 3.5 and res.factores[0].foda == Foda.FORTALEZA
    assert res.factores[1].foda == Foda.AMENAZA
    assert res.dictamen == Dictamen.B
    assert res.conteo_foda[Foda.FORTALEZA] == 1


def test_scores_out_of_range_rejected():
    with pytest.raises(ValidationError):
        _factor(1, 3, 3, AlcanceAplicado.INTERNO, [5])


# --- Fallback IA ------------------------------------------------------------

def _sugg(score, conf, citas):
    return SubfactorAISuggestion(subfactor_id=1, score_ia=score, nivel_confianza=conf,
                                 justificacion="x", citas=citas)


CITA = CitationItem(archivo="LICENSE", ubicacion="L1", fragmento="MIT License")


def test_fallback_without_citations():
    p = apply_ai_fallback(_sugg(4, 0.9, []))
    assert p.score_ia == 2 and p.requiere_revision


def test_fallback_low_confidence():
    p = apply_ai_fallback(_sugg(4, 0.44, [CITA]))
    assert p.score_ia == 2 and p.requiere_revision


def test_no_fallback_when_supported():
    p = apply_ai_fallback(_sugg(4, 0.45, [CITA]))
    assert p.score_ia == 4 and not p.requiere_revision
