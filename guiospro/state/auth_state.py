"""Sesión, login/registro y control de acceso por rol (RF-AUTH-01)."""

import reflex as rx

from ..core.constants import Rol
from ..models import repository as repo
from ..models.database import Usuario
from ..models.session import session_scope
from ..services.auth import (
    MIN_PASSWORD_LENGTH,
    create_session_token,
    hash_password,
    read_session_token,
    verify_password,
)


class AuthState(rx.State):
    session_token: str = rx.LocalStorage("", name="guiosad_session", sync=True)
    user_id: int = 0
    user_name: str = ""
    user_email: str = ""
    user_rol: str = ""
    auth_error: str = ""

    @rx.var
    def is_logged_in(self) -> bool:
        return self.user_id > 0

    @rx.var
    def is_admin(self) -> bool:
        return self.user_rol == Rol.ADMIN.value

    # --- Utilidades internas ------------------------------------------------

    def _set_user(self, user: Usuario | None) -> None:
        if user is None or not user.activo:
            self.user_id, self.user_name, self.user_email, self.user_rol = 0, "", "", ""
            return
        self.user_id = user.id
        self.user_name = user.nombre_completo
        self.user_email = user.email
        self.user_rol = user.rol

    def _current_user(self, session) -> Usuario | None:
        uid = read_session_token(self.session_token)
        user = session.get(Usuario, uid) if uid else None
        return user if user and user.activo else None

    def _restore(self) -> bool:
        with session_scope() as session:
            self._set_user(self._current_user(session))
        return self.user_id > 0

    # --- Eventos ------------------------------------------------------------

    @rx.event
    def require_login(self):
        if not self._restore():
            return rx.redirect("/login")

    @rx.event
    def require_admin(self):
        if not self._restore():
            return rx.redirect("/login")
        if self.user_rol != Rol.ADMIN.value:
            return [rx.toast.error("Acceso restringido a administradores."), rx.redirect("/")]

    @rx.event
    def redirect_if_logged(self):
        if self._restore():
            return rx.redirect("/")

    @rx.event
    def login(self, form: dict):
        email = str(form.get("email", "")).strip().lower()
        password = str(form.get("password", ""))
        with session_scope() as session:
            user = repo.get_user_by_email(session, email)
            if user is None or not user.activo or not verify_password(password, user.password_hash):
                self.auth_error = "Correo o contraseña incorrectos."
                return
            self.session_token = create_session_token(user.id)
            self._set_user(user)
        self.auth_error = ""
        return rx.redirect("/")

    @rx.event
    def register(self, form: dict):
        nombre = str(form.get("nombre", "")).strip()
        email = str(form.get("email", "")).strip().lower()
        password = str(form.get("password", ""))
        confirm = str(form.get("confirm", ""))
        organizacion = str(form.get("organizacion", "")).strip()
        if not nombre or "@" not in email:
            self.auth_error = "Ingrese su nombre y un correo válido."
            return
        if len(password) < MIN_PASSWORD_LENGTH:
            self.auth_error = f"La contraseña debe tener al menos {MIN_PASSWORD_LENGTH} caracteres."
            return
        if password != confirm:
            self.auth_error = "Las contraseñas no coinciden."
            return
        with session_scope() as session:
            if repo.get_user_by_email(session, email):
                self.auth_error = "Ya existe una cuenta con ese correo."
                return
            user = repo.create_user(session, nombre, email, hash_password(password), organizacion)
            self.session_token = create_session_token(user.id)
            self._set_user(user)
        self.auth_error = ""
        return [rx.toast.success("Cuenta creada."), rx.redirect("/")]

    @rx.event
    def logout(self):
        self.session_token = ""
        self._set_user(None)
        return rx.redirect("/login")
