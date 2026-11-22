"""Panel de calibración bibliográfica (solo administradores)."""

import reflex as rx

from ..components import importance_badge, page_shell, step_intro, table_card
from ..core.constants import IMPORTANCE_LEVELS
from ..state.calibration_state import CalibrationState as S
from ..state.models import ArticleRow, CalibrationRow, CalibrationRun


def _level(value) -> rx.Component:
    return importance_badge(rx.match(value, *[(i + 1, l) for i, l in enumerate(IMPORTANCE_LEVELS)], ""))


def _row(r: CalibrationRow) -> rx.Component:
    return rx.table.row(
        rx.table.row_header_cell(r.factor),
        rx.table.cell(r.citas),
        rx.table.cell(r.subfactores),
        rx.table.cell(rx.code(r.ratio)),
        rx.table.cell(_level(r.il)),
        rx.table.cell(_level(r.ie)),
        rx.table.cell(_level(r.is_)),
        rx.table.cell(
            rx.button(rx.icon("book-open", size=14), "Artículos", size="1", variant="soft",
                      on_click=S.open_articles(r.factor_id, r.factor))
        ),
        align="center",
    )


def _article(a: ArticleRow) -> rx.Component:
    return rx.card(
        rx.vstack(
            rx.hstack(
                rx.badge(rx.cond(a.pertinente, "Pertinente", "No pertinente"),
                         color_scheme=rx.cond(a.pertinente, "green", "gray")),
                rx.badge(a.fuente, variant="outline"),
                rx.text(a.anio, size="1", color_scheme="gray"),
                wrap="wrap",
            ),
            rx.cond(a.enlace != "", rx.link(a.titulo, href=a.enlace, is_external=True, weight="medium"),
                    rx.text(a.titulo, weight="medium")),
            rx.text(a.autores, size="1", color_scheme="gray"),
            rx.text(a.razon, size="2"),
            spacing="1",
        ),
        width="100%",
    )


def _articles_dialog() -> rx.Component:
    return rx.dialog.root(
        rx.dialog.content(
            rx.dialog.title("Auditoría bibliográfica · ", S.articles_factor),
            rx.scroll_area(
                rx.vstack(rx.foreach(S.articles, _article), spacing="2", width="100%"),
                max_height="65vh",
                type="auto",
            ),
            rx.flex(rx.dialog.close(rx.button("Cerrar", variant="soft")), justify="end", margin_top="12px"),
            max_width="760px",
        ),
        open=S.articles_open,
        on_open_change=S.set_articles_open,
    )


def calibration_page() -> rx.Component:
    return page_shell(
        step_intro(
            "Calibración bibliográfica",
            "Recupera artículos sobre adopción/evaluación de software open source publicados en el periodo "
            "configurado (OpenAlex, Crossref y Semantic Scholar), filtra su pertinencia con Google AI y calcula "
            "r = c / n, el cuartil IL y la importancia sugerida IS = M(IE = 3, IL) de cada factor.",
        ),
        rx.flex(
            rx.button(rx.icon("play", size=16), "Ejecutar calibración ", S.periodo, on_click=S.run,
                      loading=S.running, disabled=~S.ai_configured),
            rx.cond(
                S.runs.length() > 0,
                rx.select.root(
                    rx.select.trigger(placeholder="Calibración"),
                    rx.select.content(
                        rx.foreach(
                            S.runs,
                            lambda r: rx.select.item(
                                "#" + r.id.to_string() + " · " + r.fecha + rx.cond(r.vigente, " (vigente)", ""),
                                value=r.id.to_string(),
                            ),
                        )
                    ),
                    value=S.selected_run.to_string(),
                    on_change=S.select_run,
                ),
            ),
            rx.text(S.quartiles, size="2", color_scheme="gray"),
            gap="3",
            wrap="wrap",
            align="center",
        ),
        rx.cond(~S.ai_configured, rx.callout("Configure GEMINI_API_KEY para ejecutar la calibración.",
                                             icon="triangle-alert", color_scheme="amber", size="1")),
        rx.cond(
            S.log.length() > 0,
            rx.card(rx.hstack(rx.cond(S.running, rx.spinner()),
                              rx.vstack(rx.foreach(S.log, lambda m: rx.text(m, size="2")), spacing="1")),
                    width="100%"),
        ),
        rx.cond(
            S.rows.length() > 0,
            table_card(
                rx.table.root(
                    rx.table.header(rx.table.row(*[rx.table.column_header_cell(h) for h in
                                                   ("Factor", "cᵢ", "nᵢ", "rᵢ", "IL", "IE", "IS", "")])),
                    rx.table.body(rx.foreach(S.rows, _row)),
                    width="100%",
                )
            ),
            rx.callout("Aún no hay calibraciones: la IS vigente proviene del catálogo base.", icon="info"),
        ),
        _articles_dialog(),
    )
