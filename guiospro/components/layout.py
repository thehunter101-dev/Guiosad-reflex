"""Estructura general: cabecera con navegación, menú de usuario y contenedores."""

import reflex as rx

from ..state.auth_state import AuthState

APP_TITLE = "GUIOSAD"
APP_SUBTITLE = "Evaluación de software open source asistida por IA · metodología GUIOS"


def _nav_link(label: str, href: str, icon: str) -> rx.Component:
    return rx.link(
        rx.hstack(rx.icon(icon, size=16), rx.text(label, size="2"), spacing="1", align="center"),
        href=href,
        underline="none",
        color_scheme="gray",
        high_contrast=True,
    )


def header() -> rx.Component:
    return rx.flex(
        rx.link(
            rx.vstack(
                rx.heading(APP_TITLE, size="6"),
                rx.text(APP_SUBTITLE, color_scheme="gray", size="1"),
                spacing="0",
            ),
            href="/",
            underline="none",
            color_scheme="gray",
            high_contrast=True,
        ),
        rx.spacer(),
        rx.hstack(
            _nav_link("Evaluaciones", "/", "clipboard-list"),
            rx.cond(
                AuthState.is_admin,
                rx.fragment(
                    _nav_link("Calibración", "/calibracion", "library"),
                    _nav_link("Catálogo", "/catalogo", "list-tree"),
                ),
            ),
            rx.menu.root(
                rx.menu.trigger(
                    rx.button(rx.icon("circle-user", size=16), AuthState.user_name, variant="soft", size="2")
                ),
                rx.menu.content(
                    rx.box(
                        rx.text(AuthState.user_email, size="1"),
                        rx.text("Rol: ", AuthState.user_rol, size="1", color_scheme="gray"),
                        padding_x="8px",
                        padding_y="4px",
                    ),
                    rx.menu.separator(),
                    rx.menu.item(rx.icon("log-out", size=14), "Cerrar sesión", on_click=AuthState.logout),
                ),
            ),
            rx.color_mode.button(),
            spacing="4",
            align="center",
            wrap="wrap",
        ),
        align="center",
        wrap="wrap",
        gap="3",
        width="100%",
        padding_bottom="8px",
        border_bottom="1px solid var(--gray-a5)",
    )


def step_intro(title: str, *paragraphs: str) -> rx.Component:
    return rx.vstack(
        rx.heading(title, size="5"),
        *[rx.text(p, color_scheme="gray", size="2") for p in paragraphs],
        spacing="2",
        padding_y="8px",
    )


def table_card(*children: rx.Component) -> rx.Component:
    """Tabla desplazable en pantallas estrechas."""
    return rx.card(rx.box(*children, overflow_x="auto", width="100%"), width="100%", padding="0")


def page_shell(*children: rx.Component) -> rx.Component:
    """Página protegida: solo se muestra con sesión iniciada."""
    return rx.container(
        rx.cond(
            AuthState.is_logged_in,
            rx.vstack(header(), *children, spacing="4", width="100%"),
            rx.center(rx.spinner(size="3"), height="60vh"),
        ),
        size="4",
        padding_x="16px",
        padding_y="20px",
    )


def auth_shell(*children: rx.Component) -> rx.Component:
    return rx.center(
        rx.card(
            rx.vstack(
                rx.heading(APP_TITLE, size="7"),
                rx.text(APP_SUBTITLE, color_scheme="gray", size="2"),
                *children,
                spacing="4",
                width="100%",
            ),
            width="100%",
            max_width="420px",
            padding="24px",
        ),
        min_height="90vh",
        padding="16px",
    )
