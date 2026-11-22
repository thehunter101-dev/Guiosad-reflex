"""Panel principal: «Mis evaluaciones»."""

import reflex as rx

from ..components import dictamen_badge, page_shell, table_card
from ..state.dashboard_state import DashboardState
from ..state.models import EvaluationCard


def _field(label: str, name: str, placeholder: str = "", **props) -> rx.Component:
    return rx.vstack(
        rx.text(label, size="2", weight="medium"),
        rx.input(name=name, placeholder=placeholder, width="100%", **props),
        spacing="1",
        width="100%",
    )


def _create_dialog() -> rx.Component:
    return rx.dialog.root(
        rx.dialog.trigger(rx.button(rx.icon("plus", size=16), "Nueva evaluación")),
        rx.dialog.content(
            rx.dialog.title("Nueva evaluación"),
            rx.dialog.description(
                "El repositorio es opcional: sin artefactos la evaluación se realiza en modo manual.",
                size="2",
            ),
            rx.form(
                rx.vstack(
                    _field("Software *", "nombre_software", "p. ej. Moodle", required=True),
                    _field("Versión", "version", "p. ej. 4.4"),
                    _field("Repositorio GitHub/GitLab", "url_repositorio", "https://github.com/org/proyecto"),
                    _field("Organización", "organizacion"),
                    rx.cond(
                        DashboardState.form_error != "",
                        rx.callout(DashboardState.form_error, icon="triangle-alert", color_scheme="red", size="1"),
                    ),
                    rx.flex(
                        rx.dialog.close(rx.button("Cancelar", variant="soft", color_scheme="gray", type="button")),
                        rx.button("Crear", type="submit"),
                        spacing="3",
                        justify="end",
                        width="100%",
                    ),
                    spacing="3",
                ),
                on_submit=DashboardState.create,
                reset_on_submit=False,
            ),
        ),
        open=DashboardState.create_open,
        on_open_change=DashboardState.set_create_open,
    )


def _row(e: EvaluationCard) -> rx.Component:
    return rx.table.row(
        rx.table.row_header_cell(
            rx.link(
                rx.vstack(
                    rx.text(e.nombre, " ", e.version, weight="medium"),
                    rx.text(e.organizacion, size="1", color_scheme="gray"),
                    spacing="0",
                ),
                href="/evaluacion?id=" + e.id.to_string(),
            )
        ),
        rx.table.cell(rx.badge(e.modo, variant="surface")),
        rx.table.cell(rx.text(e.estado_label, size="2")),
        rx.table.cell(dictamen_badge(e.dictamen)),
        rx.table.cell(rx.text(e.actualizado, size="1", color_scheme="gray")),
        rx.table.cell(
            rx.cond(
                e.puede_borrar,
                rx.alert_dialog.root(
                    rx.alert_dialog.trigger(
                        rx.icon_button(rx.icon("trash-2", size=14), variant="ghost", color_scheme="red")
                    ),
                    rx.alert_dialog.content(
                        rx.alert_dialog.title("Eliminar evaluación"),
                        rx.alert_dialog.description("Se eliminarán todos sus datos, evidencias y dictámenes."),
                        rx.flex(
                            rx.alert_dialog.cancel(rx.button("Cancelar", variant="soft", color_scheme="gray")),
                            rx.alert_dialog.action(
                                rx.button("Eliminar", color_scheme="red", on_click=DashboardState.delete(e.id))
                            ),
                            spacing="3",
                            justify="end",
                            margin_top="16px",
                        ),
                    ),
                ),
            )
        ),
        align="center",
    )


def dashboard_page() -> rx.Component:
    return page_shell(
        rx.flex(
            rx.heading("Mis evaluaciones", size="5"),
            rx.spacer(),
            _create_dialog(),
            align="center",
            width="100%",
        ),
        rx.cond(
            DashboardState.evaluations.length() > 0,
            table_card(
                rx.table.root(
                    rx.table.header(
                        rx.table.row(
                            *[rx.table.column_header_cell(h) for h in
                              ("Software", "Modo", "Estado", "Dictamen", "Actualizado", "")]
                        )
                    ),
                    rx.table.body(rx.foreach(DashboardState.evaluations, _row)),
                    width="100%",
                )
            ),
            rx.callout(
                "Aún no hay evaluaciones. Cree una para comenzar el flujo GUIOS de 6 pasos.",
                icon="info",
            ),
        ),
    )
