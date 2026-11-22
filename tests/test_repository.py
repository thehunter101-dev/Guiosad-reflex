import pytest
from sqlmodel import select

from guiospro.core.calibration import calibrate
from guiospro.core.constants import AlcanceAplicado, Dictamen, EstadoEvaluacion, Foda, Rol
from guiospro.core.schemas import CalibracionFactorInput, CitationItem, SubfactorPropuesta
from guiospro.models import repository as repo
from guiospro.models.database import DocumentoChunk, EvaluacionSubfactor, Factor


def test_seed_is_idempotent(session):
    assert len(repo.list_factors(session)) == 18
    assert len(repo.list_subfactors(session)) == 61
    assert repo.seed_catalog(session, None) == 0


def test_first_user_is_admin(session, user):
    assert user.rol == Rol.ADMIN and user.email == "ana@example.org"
    other = repo.create_user(session, "Luis", "luis@x.org", "h")
    assert other.rol == Rol.DECISOR


def test_create_evaluation_rows(session, user):
    ev = repo.create_evaluacion(session, user.id, "Odoo", "17")
    factors = repo.evaluation_factors(session, ev.id)
    subs = repo.evaluation_subfactors(session, ev.id)
    assert len(factors) == 18 and len(subs) == 61
    soporte = next(ef for ef, f, _ in factors if f.nombre == "Soporte")
    assert soporte.alcance_aplicado == AlcanceAplicado.INTERNO
    assert ev.estado == EstadoEvaluacion.PASO_1


def _score_all(session, ev_id, value):
    for es, _, ef in repo.evaluation_subfactors(session, ev_id):
        if ef.es_relevante:
            repo.set_subfactor_score(session, es.id, value)


def test_full_manual_flow(session, user):
    ev = repo.create_evaluacion(session, user.id, "Odoo")
    for ef, _, _ in repo.evaluation_factors(session, ev.id):
        repo.set_decisor_importance(session, ef.id, 4)
    assert ev.estado == EstadoEvaluacion.PASO_2
    _score_all(session, ev.id, 4)
    result = repo.recompute(session, ev.id)
    assert result.dictamen == Dictamen.A
    assert ev.estado == EstadoEvaluacion.REVISION and ev.dictamen_base == "A"
    repo.finalize(session, ev.id)
    assert ev.estado == EstadoEvaluacion.FINALIZADA


def test_irrelevant_factor_excluded(session, user):
    ev = repo.create_evaluacion(session, user.id, "X")
    ef, f, _ = next(r for r in repo.evaluation_factors(session, ev.id) if r[0].is_aplicado == 2)
    repo.set_decisor_importance(session, ef.id, 1)  # M(1,2) = 1
    assert ef.ir_calculado == 1 and not ef.es_relevante and ef.clasificacion_foda == Foda.EXCLUIDO


def test_alcance_only_configurable(session, user):
    ev = repo.create_evaluacion(session, user.id, "X")
    rows = repo.evaluation_factors(session, ev.id)
    soporte = next(ef for ef, f, _ in rows if f.nombre == "Soporte")
    repo.set_alcance(session, soporte.id, AlcanceAplicado.EXTERNO)
    assert soporte.alcance_aplicado == "Externo"
    other = next(ef for ef, f, _ in rows if f.nombre != "Soporte")
    with pytest.raises(ValueError):
        repo.set_alcance(session, other.id, AlcanceAplicado.INTERNO)


def test_finalize_requires_complete(session, user):
    ev = repo.create_evaluacion(session, user.id, "X")
    with pytest.raises(ValueError):
        repo.finalize(session, ev.id)


def test_access_control(session, user):
    other = repo.create_user(session, "Luis", "luis@x.org", "h")
    third = repo.create_user(session, "Eva", "eva@x.org", "h")
    ev = repo.create_evaluacion(session, other.id, "X")
    assert repo.participant_role(session, ev.id, third) is None
    repo.add_participant(session, ev.id, "eva@x.org", Rol.EVALUADOR)
    assert repo.participant_role(session, ev.id, third) == Rol.EVALUADOR
    assert repo.participant_role(session, ev.id, user) == Rol.DECISOR  # admin
    assert [e.id for e in repo.list_evaluaciones_for_user(session, third)] == [ev.id]


def test_cascade_delete(session, user):
    ev = repo.create_evaluacion(session, user.id, "X")
    repo.delete_evaluacion(session, ev.id)
    session.flush()
    assert session.exec(select(EvaluacionSubfactor)).all() == []


def test_ai_proposal_prefills_and_respects_human(session, user):
    ev = repo.create_evaluacion(session, user.id, "X")
    es, _, _ = repo.evaluation_subfactors(session, ev.id)[0]
    cita = CitationItem(archivo="README.md", ubicacion="L3", fragmento="Docker")
    p = SubfactorPropuesta(subfactor_id=es.subfactor_id, score_ia=4, nivel_confianza=0.9,
                           justificacion="ok", citas=[cita])
    repo.save_ai_proposal(session, es.id, p)
    assert es.score_evaluador == 4 and not es.validado_por_humano
    assert len(repo.evidences_by_subfactor(session, ev.id)[es.id]) == 1
    repo.set_subfactor_score(session, es.id, 1)
    repo.save_ai_proposal(session, es.id, p.model_copy(update={"score_ia": 3}))
    assert es.score_evaluador == 1 and es.score_ia == 3


def test_vector_search_fallback(session, user):
    ev = repo.create_evaluacion(session, user.id, "X")
    repo.replace_chunks(session, ev.id, [
        DocumentoChunk(evaluacion_id=0, ruta_archivo="a", categoria="codigo", contenido_texto="a", embedding=[1.0, 0.0]),
        DocumentoChunk(evaluacion_id=0, ruta_archivo="b", categoria="codigo", contenido_texto="b", embedding=[0.0, 1.0]),
    ])
    top = repo.search_chunks(session, ev.id, [0.1, 0.9], k=1)
    assert [c.ruta_archivo for c in top] == ["b"]
    assert repo.count_chunks(session, ev.id) == 2


def test_apply_calibration_updates_is(session, user):
    counts = repo.active_subfactor_counts(session)
    factors = repo.list_factors(session)
    data = [CalibracionFactorInput(factor_id=f.id, citas_pertinentes=i * 3, subfactores_activos=counts[f.id])
            for i, f in enumerate(factors)]
    result = calibrate(data)
    cal = repo.create_calibracion(session, user.id, 2020, 2025)
    repo.apply_calibration(session, cal.id, result)
    assert repo.vigente_calibration(session).id == cal.id
    by_id = {r.factor_id: r.is_calculado for r in result.factores}
    assert all(session.get(Factor, fid).is_vigente == v for fid, v in by_id.items())
    assert len(repo.calibration_rows(session, cal.id)) == 18
