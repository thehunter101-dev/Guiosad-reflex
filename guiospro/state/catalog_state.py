"""Gestor del catálogo GUIOS sin tocar código (RF-AUTH-02)."""

import reflex as rx
import sqlalchemy as sa
from sqlmodel import select

from ..core.constants import Alcance
from ..models import repository as repo
from ..models.database import Dimension, EvaluacionFactor, EvaluacionSubfactor, Factor, Subfactor
from ..models.session import session_scope
from .auth_state import AuthState
from .models import CatalogFactorRow, CatalogSubfactorRow, DimensionRow

ALCANCES = [a.value for a in Alcance]


class CatalogState(AuthState):
    dimensions: list[DimensionRow] = []
    factors: list[CatalogFactorRow] = []
    subfactors: list[CatalogSubfactorRow] = []
    selected_factor_id: int = 0

    # Diálogos de edición (id 0 = nuevo)
    dim_dialog: bool = False
    dim_edit: DimensionRow = DimensionRow()
    factor_dialog: bool = False
    factor_edit: CatalogFactorRow = CatalogFactorRow()
    sub_dialog: bool = False
    sub_edit: CatalogSubfactorRow = CatalogSubfactorRow()
    form_error: str = ""

    @rx.var
    def dimension_names(self) -> list[str]:
        return [d.nombre for d in self.dimensions]

    @rx.var
    def selected_factor_name(self) -> str:
        return next((f.nombre for f in self.factors if f.id == self.selected_factor_id), "")

    @rx.var
    def factor_dimension_name(self) -> str:
        return next((d.nombre for d in self.dimensions if d.id == self.factor_edit.dimension_id), "")

    @rx.event
    def load(self):
        if not self.is_admin:
            return
        with session_scope() as session:
            self._reload(session)

    def _reload(self, session) -> None:
        dims = repo.list_dimensions(session)
        names = {d.id: d.nombre for d in dims}
        counts = repo.active_subfactor_counts(session)
        self.dimensions = [
            DimensionRow(id=d.id, codigo=d.codigo, nombre=d.nombre, descripcion=d.descripcion or "", activa=d.activa)
            for d in dims
        ]
        self.factors = [
            CatalogFactorRow(
                id=f.id, dimension_id=f.dimension_id, dimension=names.get(f.dimension_id, ""), codigo=f.codigo,
                nombre=f.nombre, tipo_alcance=f.tipo_alcance, cadena_busqueda=f.cadena_busqueda,
                is_vigente=f.is_vigente, activo=f.activo, subfactores_activos=counts.get(f.id, 0),
            )
            for f in repo.list_factors(session)
        ]
        if not self.selected_factor_id and self.factors:
            self.selected_factor_id = self.factors[0].id
        self.subfactors = [
            CatalogSubfactorRow(id=s.id, factor_id=s.factor_id, codigo=s.codigo, afirmacion=s.afirmacion,
                                guia_verificacion=s.guia_verificacion or "", activo=s.subfactor_activo)
            for s in repo.list_subfactors(session, self.selected_factor_id)
        ]

    @rx.event
    def select_factor(self, factor_id: int):
        self.selected_factor_id = factor_id
        with session_scope() as session:
            self._reload(session)

    def _guard(self) -> bool:
        return self.is_admin

    def _save(self, fn):
        try:
            with session_scope() as session:
                fn(session)
                session.flush()
                self._reload(session)
        except sa.exc.IntegrityError:
            self.form_error = "El código o nombre ya existe."
            return None
        except ValueError as exc:
            self.form_error = str(exc)
            return None
        self.form_error = ""
        self.dim_dialog = self.factor_dialog = self.sub_dialog = False
        return rx.toast.success("Catálogo actualizado.")

    # --- Dimensiones -------------------------------------------------------

    @rx.event
    def open_dimension(self, dim_id: int):
        self.dim_edit = next((d for d in self.dimensions if d.id == dim_id), DimensionRow())
        self.form_error, self.dim_dialog = "", True

    @rx.event
    def set_dim_dialog(self, value: bool):
        self.dim_dialog = value

    @rx.event
    def save_dimension(self, form: dict):
        if not self._guard():
            return

        def apply(session):
            codigo, nombre = str(form.get("codigo", "")).strip().upper(), str(form.get("nombre", "")).strip()
            if not codigo or not nombre:
                raise ValueError("Código y nombre son obligatorios.")
            d = session.get(Dimension, self.dim_edit.id) if self.dim_edit.id else Dimension(codigo=codigo, nombre=nombre)
            d.codigo, d.nombre = codigo, nombre
            d.descripcion = str(form.get("descripcion", "")).strip() or None
            session.add(d)

        return self._save(apply)

    @rx.event
    def toggle_dimension(self, dim_id: int):
        if not self._guard():
            return

        def apply(session):
            d = session.get(Dimension, dim_id)
            d.activa = not d.activa
            session.add(d)

        return self._save(apply)

    # --- Factores ----------------------------------------------------------

    @rx.event
    def open_factor(self, factor_id: int):
        default_dim = self.dimensions[0].id if self.dimensions else 0
        self.factor_edit = next(
            (f for f in self.factors if f.id == factor_id),
            CatalogFactorRow(dimension_id=default_dim, tipo_alcance=Alcance.EXTERNO.value),
        )
        self.form_error, self.factor_dialog = "", True

    @rx.event
    def set_factor_dialog(self, value: bool):
        self.factor_dialog = value

    @rx.event
    def save_factor(self, form: dict):
        if not self._guard():
            return

        def apply(session):
            codigo, nombre = str(form.get("codigo", "")).strip().upper(), str(form.get("nombre", "")).strip()
            alcance = str(form.get("tipo_alcance", ""))
            dim_name = str(form.get("dimension", ""))
            dim = next((d for d in self.dimensions if d.nombre == dim_name), None)
            if not codigo or not nombre or dim is None or alcance not in ALCANCES:
                raise ValueError("Complete código, nombre, dimensión y alcance.")
            f = session.get(Factor, self.factor_edit.id) if self.factor_edit.id else Factor(
                dimension_id=dim.id, codigo=codigo, nombre=nombre, tipo_alcance=alcance, orden=len(self.factors)
            )
            f.dimension_id, f.codigo, f.nombre, f.tipo_alcance = dim.id, codigo, nombre, alcance
            f.cadena_busqueda = str(form.get("cadena_busqueda", "")).strip()
            session.add(f)

        return self._save(apply)

    @rx.event
    def toggle_factor(self, factor_id: int):
        if not self._guard():
            return

        def apply(session):
            f = session.get(Factor, factor_id)
            f.activo = not f.activo
            session.add(f)

        return self._save(apply)

    @rx.event
    def delete_factor(self, factor_id: int):
        if not self._guard():
            return

        def apply(session):
            used = session.exec(select(EvaluacionFactor.id).where(EvaluacionFactor.factor_id == factor_id)).first()
            if used:
                raise ValueError("El factor se usa en evaluaciones: desactívelo en lugar de eliminarlo.")
            repo.delete_entity(session, Factor, factor_id)
            self.selected_factor_id = 0

        result = self._save(apply)
        if self.form_error:
            return rx.toast.error(self.form_error)
        return result

    # --- Subfactores -------------------------------------------------------

    @rx.event
    def open_subfactor(self, sub_id: int):
        self.sub_edit = next(
            (s for s in self.subfactors if s.id == sub_id), CatalogSubfactorRow(factor_id=self.selected_factor_id)
        )
        self.form_error, self.sub_dialog = "", True

    @rx.event
    def set_sub_dialog(self, value: bool):
        self.sub_dialog = value

    @rx.event
    def save_subfactor(self, form: dict):
        if not self._guard() or not self.selected_factor_id:
            return

        def apply(session):
            codigo, afirmacion = str(form.get("codigo", "")).strip().upper(), str(form.get("afirmacion", "")).strip()
            if not codigo or not afirmacion:
                raise ValueError("Código y afirmación son obligatorios.")
            s = session.get(Subfactor, self.sub_edit.id) if self.sub_edit.id else Subfactor(
                factor_id=self.selected_factor_id, codigo=codigo, afirmacion=afirmacion, orden=len(self.subfactors)
            )
            s.codigo, s.afirmacion = codigo, afirmacion
            s.guia_verificacion = str(form.get("guia_verificacion", "")).strip() or None
            session.add(s)

        return self._save(apply)

    @rx.event
    def toggle_subfactor(self, sub_id: int):
        if not self._guard():
            return

        def apply(session):
            s = session.get(Subfactor, sub_id)
            s.subfactor_activo = not s.subfactor_activo
            session.add(s)

        return self._save(apply)

    @rx.event
    def delete_subfactor(self, sub_id: int):
        if not self._guard():
            return

        def apply(session):
            used = session.exec(select(EvaluacionSubfactor.id).where(EvaluacionSubfactor.subfactor_id == sub_id)).first()
            if used:
                raise ValueError("El subfactor se usa en evaluaciones: desactívelo en lugar de eliminarlo.")
            repo.delete_entity(session, Subfactor, sub_id)

        result = self._save(apply)
        if self.form_error:
            return rx.toast.error(self.form_error)
        return result
