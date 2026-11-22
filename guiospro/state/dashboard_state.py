"""Panel principal: evaluaciones del usuario y alta de nuevas evaluaciones."""

import reflex as rx

from ..core.constants import Rol
from ..models import repository as repo
from ..models.database import Usuario
from ..models.session import session_scope
from .auth_state import AuthState
from .models import EvaluationCard

ESTADO_LABEL = {
    "paso_1": "Paso 1 · Importancia",
    "paso_2": "Paso 2 · Relevancia",
    "paso_3": "Pasos 3-4 · Ponderación",
    "revision": "Revisión",
    "finalizada": "Finalizada",
}


class DashboardState(AuthState):
    evaluations: list[EvaluationCard] = []
    create_open: bool = False
    form_error: str = ""

    @rx.event
    def load(self):
        if not self.user_id:
            return
        with session_scope() as session:
            user = session.get(Usuario, self.user_id)
            self.evaluations = [
                EvaluationCard(
                    id=e.id,
                    nombre=e.nombre_software,
                    version=e.version or "",
                    organizacion=e.organizacion or "",
                    modo="Híbrido IA" if e.modo == "hibrido_ia" else "Manual",
                    estado=e.estado,
                    estado_label=ESTADO_LABEL.get(e.estado, e.estado),
                    dictamen=e.dictamen_base or "",
                    actualizado=e.actualizado_en.strftime("%Y-%m-%d %H:%M"),
                    puede_borrar=user.rol == Rol.ADMIN or e.usuario_propietario_id == user.id,
                )
                for e in repo.list_evaluaciones_for_user(session, user)
            ]

    @rx.event
    def set_create_open(self, value: bool):
        self.create_open = value
        self.form_error = ""

    @rx.event
    def create(self, form: dict):
        nombre = str(form.get("nombre_software", "")).strip()
        if not nombre:
            self.form_error = "El nombre del software es obligatorio."
            return
        url = str(form.get("url_repositorio", "")).strip()
        if url and not url.startswith("https://"):
            self.form_error = "La URL del repositorio debe empezar por https://"
            return
        with session_scope() as session:
            ev = repo.create_evaluacion(
                session,
                self.user_id,
                nombre,
                str(form.get("version", "")),
                url,
                str(form.get("organizacion", "")),
            )
            new_id = ev.id
        self.create_open = False
        return rx.redirect(f"/evaluacion?id={new_id}")

    @rx.event
    def delete(self, evaluacion_id: int):
        with session_scope() as session:
            ev = repo.get_evaluacion(session, evaluacion_id)
            user = session.get(Usuario, self.user_id)
            if ev is None or not (user.rol == Rol.ADMIN or ev.usuario_propietario_id == user.id):
                return rx.toast.error("No tiene permiso para eliminar esta evaluación.")
            repo.delete_evaluacion(session, evaluacion_id)
        self.evaluations = [e for e in self.evaluations if e.id != evaluacion_id]
        return rx.toast.success("Evaluación eliminada.")
