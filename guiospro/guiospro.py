"""Punto de entrada de la aplicación Reflex GUIOSAD."""

import reflex as rx

from .components.layout import APP_TITLE
from .pages import (
    calibration_page,
    catalog_page,
    dashboard_page,
    evaluation_page,
    login_page,
    register_page,
)
from .state import AuthState, CalibrationState, CatalogState, DashboardState, EvaluationState

app = rx.App()
app.add_page(login_page, route="/login", title=f"{APP_TITLE} · Iniciar sesión",
             on_load=AuthState.redirect_if_logged)
app.add_page(register_page, route="/registro", title=f"{APP_TITLE} · Registro",
             on_load=AuthState.redirect_if_logged)
app.add_page(dashboard_page, route="/", title=APP_TITLE,
             on_load=[AuthState.require_login, DashboardState.load])
app.add_page(evaluation_page, route="/evaluacion", title=f"{APP_TITLE} · Evaluación",
             on_load=[AuthState.require_login, EvaluationState.load])
app.add_page(calibration_page, route="/calibracion", title=f"{APP_TITLE} · Calibración",
             on_load=[AuthState.require_admin, CalibrationState.load])
app.add_page(catalog_page, route="/catalogo", title=f"{APP_TITLE} · Catálogo",
             on_load=[AuthState.require_admin, CatalogState.load])
