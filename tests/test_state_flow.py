"""Recorre el flujo de la UI llamando a los manejadores reales de los estados Reflex."""

import pytest
from reflex.state import State

from guiospro.core.constants import COMPLIANCE_LEVELS, Rol
from guiospro.models import repository as repo
from guiospro.models import session as session_module
from guiospro.state import AuthState, CatalogState, DashboardState, EvaluationState


@pytest.fixture
def root(engine, monkeypatch):
    monkeypatch.setattr(session_module, "get_engine", lambda url=None: engine)
    return State(_reflex_internal_init=True)


def sub(root, cls):
    return root.get_substate(cls.get_full_name().split(".")[1:])


def call(state, handler, *args):
    return getattr(type(state), handler).fn(state, *args)


def _register(root, email="ana@x.org"):
    auth = sub(root, AuthState)
    call(auth, "register", {"nombre": "Ana", "email": email, "password": "secreto123",
                            "confirm": "secreto123", "organizacion": "UNEMI"})
    assert auth.auth_error == "" and auth.user_id > 0
    return auth


def test_register_login_logout(root):
    auth = _register(root)
    assert auth.user_rol == Rol.ADMIN and auth.session_token
    call(auth, "logout")
    assert auth.user_id == 0
    call(auth, "login", {"email": "ana@x.org", "password": "mala"})
    assert auth.auth_error
    call(auth, "login", {"email": "ANA@x.org", "password": "secreto123"})
    assert auth.user_id > 0


def test_register_validation(root):
    auth = sub(root, AuthState)
    call(auth, "register", {"nombre": "A", "email": "a@x.org", "password": "corta", "confirm": "corta"})
    assert "8" in auth.auth_error


def test_manual_wizard_flow(root, engine):
    _register(root)
    dash = sub(root, DashboardState)
    call(dash, "create", {"nombre_software": "Moodle", "version": "4.4"})
    call(dash, "load")
    assert [e.nombre for e in dash.evaluations] == ["Moodle"]

    ev = sub(root, EvaluationState)
    ev.eval_id = dash.evaluations[0].id
    ev.my_role = Rol.DECISOR.value
    ev._refresh()
    assert len(ev.factors) == 18 and ev.dictamen == ""

    # Pasos 1-2: todo Fundamental -> todos relevantes.
    for f in list(ev.factors):
        call(ev, "set_decisor", f.ef_id, "Fundamental")
    assert all(f.relevante for f in ev.factors)
    assert ev.total_count == 61 and ev.scored_count == 0

    # Pasos 3-4: autoguardado de cada subfactor.
    for s in list(ev.subfactors):
        call(ev, "set_score", s.es_id, COMPLIANCE_LEVELS[3])
    assert ev.progress_pct == 100
    call(ev, "set_observation", ev.subfactors[0].es_id, "  Verificado en sitio  ")
    assert ev.subfactors[0].observacion == "Verificado en sitio"

    # Filtro "Pendientes / Desconozco" vacío; cabeceras por factor en vista completa.
    call(ev, "set_filtro", "Pendientes / Desconozco (2)")
    assert ev.visible_subfactors == []
    call(ev, "set_filtro", "Todos")
    assert sum(c.show_header for c in ev.visible_subfactors) == 18

    # Pasos 5-6
    assert ev.dictamen == "A" and ev.pendientes == 0
    call(ev, "finalize")
    assert ev.is_final and not ev.can_edit_scores


def test_evaluator_role_cannot_edit_decisor(root):
    _register(root)
    ev = sub(root, EvaluationState)
    dash = sub(root, DashboardState)
    call(dash, "create", {"nombre_software": "X"})
    call(dash, "load")
    ev.eval_id = dash.evaluations[0].id
    ev.my_role = Rol.EVALUADOR.value
    ev._refresh()
    before = ev.factors[0].decisor_label
    call(ev, "set_decisor", ev.factors[0].ef_id, "Fundamental")
    ev._refresh()
    assert ev.factors[0].decisor_label == before


def test_catalog_crud(root):
    _register(root)
    cat = sub(root, CatalogState)
    call(cat, "load")
    assert len(cat.factors) == 18
    call(cat, "open_factor", 0)
    call(cat, "save_factor", {"codigo": "ECO-02", "nombre": "Licenciamiento", "dimension": "Económica",
                              "tipo_alcance": "Externo", "cadena_busqueda": "x"})
    assert cat.form_error == "" and len(cat.factors) == 19
    new = next(f for f in cat.factors if f.codigo == "ECO-02")
    call(cat, "select_factor", new.id)
    call(cat, "open_subfactor", 0)
    call(cat, "save_subfactor", {"codigo": "ECO-02-01", "afirmacion": "La licencia es OSI", "guia_verificacion": ""})
    assert [s.codigo for s in cat.subfactors] == ["ECO-02-01"]
    # Duplicado -> error controlado.
    call(cat, "open_subfactor", 0)
    call(cat, "save_subfactor", {"codigo": "ECO-02-01", "afirmacion": "dup"})
    assert cat.form_error
    call(cat, "toggle_factor", new.id)
    assert not next(f for f in cat.factors if f.id == new.id).activo
    call(cat, "delete_factor", new.id)
    assert len(cat.factors) == 18
