"""Login y registro."""

import reflex as rx

from ..components import auth_shell
from ..state.auth_state import AuthState


def _error() -> rx.Component:
    return rx.cond(
        AuthState.auth_error != "",
        rx.callout(AuthState.auth_error, icon="triangle-alert", color_scheme="red", size="1"),
    )


def _field(label: str, name: str, type_: str = "text", **props) -> rx.Component:
    return rx.vstack(
        rx.text(label, size="2", weight="medium"),
        rx.input(name=name, type=type_, width="100%", **props),
        spacing="1",
        width="100%",
    )


def login_page() -> rx.Component:
    return auth_shell(
        rx.heading("Iniciar sesión", size="4"),
        _error(),
        rx.form(
            rx.vstack(
                _field("Correo", "email", "email", required=True, auto_complete="email"),
                _field("Contraseña", "password", "password", required=True, auto_complete="current-password"),
                rx.button("Entrar", type="submit", width="100%"),
                spacing="3",
                width="100%",
            ),
            on_submit=AuthState.login,
            reset_on_submit=False,
            width="100%",
        ),
        rx.text("¿No tiene cuenta? ", rx.link("Regístrese", href="/registro"), size="2"),
    )


def register_page() -> rx.Component:
    return auth_shell(
        rx.heading("Crear cuenta", size="4"),
        rx.text("El primer usuario registrado será administrador.", size="1", color_scheme="gray"),
        _error(),
        rx.form(
            rx.vstack(
                _field("Nombre completo", "nombre", required=True),
                _field("Correo", "email", "email", required=True),
                _field("Organización", "organizacion"),
                _field("Contraseña (mín. 8)", "password", "password", required=True, auto_complete="new-password"),
                _field("Confirmar contraseña", "confirm", "password", required=True, auto_complete="new-password"),
                rx.button("Registrarse", type="submit", width="100%"),
                spacing="3",
                width="100%",
            ),
            on_submit=AuthState.register,
            reset_on_submit=False,
            width="100%",
        ),
        rx.text("¿Ya tiene cuenta? ", rx.link("Inicie sesión", href="/login"), size="2"),
    )
