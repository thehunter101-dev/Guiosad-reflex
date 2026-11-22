"""Wizard de evaluación: contexto IA, pasos 1-2, 3-4, 5-6 y equipo."""

import reflex as rx

from ..components import (
    dictamen_badge,
    foda_badge,
    foda_color,
    importance_badge,
    level_select,
    page_shell,
    recommendation_color,
    score_color,
    step_intro,
    table_card,
)
from ..core.constants import COMPLIANCE_LEVELS, IMPORTANCE_LEVELS, AlcanceAplicado, Rol
from ..state.evaluation_state import FILTERS, UPLOAD_ID, EvaluationState as S
from ..state.models import (
    EvidenceRow,
    FactorRow,
    FodaCount,
    ParticipantRow,
    PlanRow,
    SubfactorCard,
    SummaryRow,
)

UPLOAD_ACCEPT = {
    "application/zip": [".zip"],
    "application/pdf": [".pdf"],
    "text/markdown": [".md", ".markdown"],
    "text/csv": [".csv"],
    "text/plain": [".txt", ".rst"],
}


# --- Cabecera ---------------------------------------------------------------

def _header() -> rx.Component:
    return rx.flex(
        rx.vstack(
            rx.hstack(
                rx.link(rx.icon("arrow-left", size=18), href="/", color_scheme="gray"),
                rx.heading(S.nombre_software, " ", S.version, size="6"),
                align="center",
            ),
            rx.text(S.organizacion, size="2", color_scheme="gray"),
            spacing="1",
        ),
        rx.spacer(),
        rx.hstack(
            rx.badge(rx.icon("cpu", size=12), S.modo_label, variant="surface", size="2"),
            rx.badge(S.estado_label, variant="soft", size="2"),
            dictamen_badge(S.dictamen),
            rx.badge("Rol: ", S.my_role, variant="outline", size="2"),
            spacing="2",
            wrap="wrap",
        ),
        align="center",
        wrap="wrap",
        gap="3",
        width="100%",
    )


def _task_panel() -> rx.Component:
    return rx.cond(
        S.task_log.length() > 0,
        rx.card(
            rx.hstack(
                rx.cond(S.busy, rx.spinner(size="2"), rx.icon("circle-check", color="var(--green-9)")),
                rx.vstack(rx.foreach(S.task_log, lambda m: rx.text(m, size="2")), spacing="1"),
                align="start",
            ),
            width="100%",
        ),
    )


def _ai_notice() -> rx.Component:
    return rx.cond(
        S.ai_notice != "",
        rx.callout(S.ai_notice, icon="info", color_scheme="amber", size="1", width="100%"),
    )


# --- Contexto (ingesta + IA) ------------------------------------------------

def _context_tab() -> rx.Component:
    return rx.vstack(
        step_intro(
            "Contexto técnico (opcional)",
            "Aporte el repositorio y/o documentación del software. GUIOSAD realiza un análisis "
            "estático (licencias, configuración, estructura) y, si Google AI está disponible, "
            "pre-evalúa los subfactores de los factores relevantes con citas verificables.",
            "Sin artefactos o si la IA falla, la evaluación continúa en modo manual sin perder datos.",
        ),
        rx.cond(
            ~S.ai_configured,
            rx.callout("GEMINI_API_KEY no configurada: solo se ejecutará el análisis estático.",
                       icon="triangle-alert", color_scheme="amber", size="1"),
        ),
        rx.cond(
            S.can_edit_decisor,
            rx.vstack(
                rx.text("Repositorio GitHub/GitLab", size="2", weight="medium"),
                rx.input(
                    value=S.repo_url_input,
                    on_change=S.set_repo_url_input,
                    placeholder="https://github.com/org/proyecto",
                    width="100%",
                ),
                rx.text("Documentos (ZIP, PDF, MD, CSV, TXT)", size="2", weight="medium"),
                rx.upload(
                    rx.vstack(
                        rx.icon("upload", size=24, color="var(--gray-10)"),
                        rx.text("Arrastre archivos aquí o haga clic para seleccionarlos", size="2"),
                        align="center",
                        spacing="1",
                    ),
                    id=UPLOAD_ID,
                    accept=UPLOAD_ACCEPT,
                    max_size=200 * 1024 * 1024,
                    multiple=True,
                    border="1px dashed var(--gray-a7)",
                    border_radius="8px",
                    padding="20px",
                    width="100%",
                    on_drop=S.handle_upload(rx.upload_files(upload_id=UPLOAD_ID)),
                ),
                rx.hstack(
                    rx.foreach(
                        S.pending_uploads,
                        lambda name: rx.badge(
                            name,
                            rx.icon("x", size=12, cursor="pointer", on_click=S.remove_upload(name)),
                            variant="surface",
                        ),
                    ),
                    wrap="wrap",
                ),
                rx.hstack(
                    rx.button(
                        rx.icon("scan-search", size=16),
                        "Analizar y pre-evaluar",
                        on_click=S.start_ingest,
                        loading=S.busy,
                    ),
                    rx.cond(
                        S.chunk_count > 0,
                        rx.button(
                            rx.icon("refresh-cw", size=16),
                            rx.cond(S.embedded_count < S.chunk_count, "Reanudar embeddings y pre-evaluar",
                                    "Re-ejecutar pre-evaluación IA"),
                            on_click=S.rerun_prefill,
                            variant="soft",
                            disabled=S.busy | ~S.ai_configured,
                        ),
                    ),
                    wrap="wrap",
                ),
                spacing="2",
                width="100%",
            ),
        ),
        _task_panel(),
        _ai_notice(),
        rx.cond(
            S.static_report.length() > 0,
            rx.card(
                rx.vstack(
                    rx.hstack(rx.icon("file-search", size=16), rx.text("Análisis estático", weight="bold")),
                    rx.foreach(S.static_report, lambda line: rx.text(line, size="2")),
                    rx.text(S.embedded_count.to_string() + " de " + S.chunk_count.to_string()
                            + " fragmentos con embedding para RAG", size="1",
                            color_scheme="gray"),
                    spacing="1",
                ),
                width="100%",
            ),
        ),
        width="100%",
        spacing="3",
    )


# --- Pasos 1 y 2 ------------------------------------------------------------

def _scope_cell(row: FactorRow) -> rx.Component:
    return rx.cond(
        row.alcance_editable & S.can_edit_decisor,
        level_select(
            [AlcanceAplicado.INTERNO.value, AlcanceAplicado.EXTERNO.value],
            value=row.alcance,
            on_change=lambda v: S.set_alcance(row.ef_id, v),
        ),
        rx.text(row.alcance, size="2"),
    )


def _factor_row(row: FactorRow) -> rx.Component:
    return rx.table.row(
        rx.table.row_header_cell(
            rx.vstack(
                rx.text(row.nombre, weight="medium"),
                rx.text(row.dimension, size="1", color_scheme="gray"),
                spacing="0",
            )
        ),
        rx.table.cell(importance_badge(row.is_label)),
        rx.table.cell(
            level_select(
                IMPORTANCE_LEVELS,
                value=row.decisor_label,
                on_change=lambda v: S.set_decisor(row.ef_id, v),
                disabled=~S.can_edit_decisor,
            ),
            min_width="150px",
        ),
        rx.table.cell(
            rx.hstack(
                importance_badge(row.ir_label),
                rx.cond(~row.relevante, rx.badge("Excluido", color_scheme="gray", variant="outline")),
            )
        ),
        rx.table.cell(_scope_cell(row), min_width="120px"),
        opacity=rx.cond(row.relevante, "1", "0.55"),
        align="center",
    )


def _relevance_tab() -> rx.Component:
    return rx.vstack(
        step_intro(
            "Pasos 1 y 2. Importancia del decisor y factores relevantes",
            "Asigne la importancia que cada factor tiene para su organización (ID). La importancia "
            "relativa se obtiene con la matriz cartesiana IR = M(ID, IS), donde IS es la importancia "
            "sugerida calibrada con la literatura. Los factores con IR «Irrelevante» se excluyen.",
            "Solo el factor Soporte permite elegir alcance Interno (equipo propio) o Externo "
            "(comunidad/proveedores).",
        ),
        table_card(
            rx.table.root(
                rx.table.header(
                    rx.table.row(
                        *[rx.table.column_header_cell(h) for h in
                          ("Factor", "Imp. sugerida (IS)", "Imp. decisor (ID)", "Imp. relativa (IR)", "Alcance")]
                    )
                ),
                rx.table.body(rx.foreach(S.factors, _factor_row)),
                width="100%",
            )
        ),
        width="100%",
    )


# --- Pasos 3 y 4 (vista continua + HITL) -----------------------------------

def _evidence(e: EvidenceRow) -> rx.Component:
    return rx.vstack(
        rx.text(rx.code(e.archivo), " · ", e.ubicacion, size="1", color_scheme="gray"),
        rx.box(
            rx.text(e.fragmento, size="1", white_space="pre-wrap", font_family="var(--code-font-family)"),
            padding="8px",
            background="var(--gray-a3)",
            border_radius="6px",
            width="100%",
            overflow_x="auto",
        ),
        spacing="1",
        width="100%",
    )


def _ai_panel(card: SubfactorCard) -> rx.Component:
    return rx.cond(
        card.score_ia > 0,
        rx.vstack(
            rx.hstack(
                rx.badge(rx.icon("sparkles", size=12), "IA: ", card.score_ia_label,
                         color_scheme=score_color(card.score_ia), variant="soft"),
                rx.badge("Confianza ", card.confianza_pct,
                         color_scheme=rx.cond(card.baja_confianza, "orange", "gray"), variant="outline"),
                rx.cond(card.revision_prioritaria,
                        rx.badge(rx.icon("flag", size=12), "Revisión prioritaria", color_scheme="orange")),
                wrap="wrap",
                spacing="2",
            ),
            rx.accordion.root(
                rx.accordion.item(
                    header=rx.text("Ver justificación y evidencia (", card.evidencias.length().to_string(), ")",
                                   size="2"),
                    content=rx.vstack(
                        rx.text(card.justificacion, size="2", color_scheme="gray"),
                        rx.foreach(card.evidencias, _evidence),
                        spacing="2",
                        width="100%",
                    ),
                    value="ev",
                ),
                collapsible=True,
                type="single",
                variant="ghost",
                width="100%",
            ),
            spacing="2",
            width="100%",
        ),
    )


def _subfactor_card(card: SubfactorCard) -> rx.Component:
    return rx.fragment(
        rx.cond(
            card.show_header,
            rx.hstack(
                rx.heading(card.factor, size="4"),
                rx.text(card.dimension, size="1", color_scheme="gray"),
                rx.spacer(),
                rx.text("PM: ", rx.code(card.factor_pm), size="2"),
                align="baseline",
                width="100%",
                padding_top="12px",
            ),
        ),
        rx.card(
            rx.flex(
                rx.vstack(
                    rx.hstack(
                        rx.badge(card.codigo, variant="outline", size="1"),
                        rx.cond(card.validado, rx.badge(rx.icon("user-check", size=12), "Validado",
                                                        color_scheme="green", size="1")),
                        spacing="2",
                    ),
                    rx.text(card.afirmacion, weight="medium", size="3"),
                    rx.cond(card.guia != "", rx.text(card.guia, size="1", color_scheme="gray")),
                    _ai_panel(card),
                    spacing="2",
                    flex="1 1 360px",
                    min_width="0",
                ),
                rx.vstack(
                    rx.text("Puntaje del evaluador", size="1", weight="medium"),
                    rx.select(
                        COMPLIANCE_LEVELS,
                        value=card.score_label,
                        placeholder="Sin evaluar",
                        on_change=lambda v: S.set_score(card.es_id, v),
                        disabled=~S.can_edit_scores,
                        width="100%",
                    ),
                    rx.text_area(
                        default_value=card.observacion,
                        placeholder="Observación (opcional)",
                        on_blur=lambda v: S.set_observation(card.es_id, v),
                        disabled=~S.can_edit_scores,
                        rows="2",
                        width="100%",
                    ),
                    spacing="1",
                    flex="0 1 280px",
                    min_width="220px",
                ),
                gap="4",
                wrap="wrap",
                width="100%",
            ),
            width="100%",
            key=card.es_id,
        ),
    )


def _weighting_tab() -> rx.Component:
    return rx.vstack(
        step_intro(
            "Pasos 3 y 4. Ponderación de subfactores",
            "Valore el cumplimiento de cada subfactor de los factores relevantes. Cada cambio se guarda "
            "automáticamente. Las propuestas de la IA muestran su confianza y el fragmento exacto citado; "
            "usted decide el puntaje final.",
        ),
        rx.cond(
            S.total_count > 0,
            rx.vstack(
                rx.flex(
                    rx.vstack(
                        rx.text(S.scored_count.to_string() + " de " + S.total_count.to_string()
                                + " subfactores evaluados", size="2"),
                        rx.progress(value=S.progress_pct, width="100%"),
                        spacing="1",
                        flex="1 1 260px",
                    ),
                    rx.segmented_control.root(
                        *[rx.segmented_control.item(f, value=f) for f in FILTERS],
                        value=S.filtro,
                        on_change=S.set_filtro,
                        size="1",
                    ),
                    rx.cond(
                        S.can_edit_scores & (S.modo == "hibrido_ia"),
                        rx.button(rx.icon("check-check", size=14), "Validar propuestas con evidencia",
                                  variant="soft", size="1", on_click=S.accept_all_ai),
                    ),
                    gap="3",
                    wrap="wrap",
                    align="center",
                    width="100%",
                ),
                rx.foreach(S.visible_subfactors, _subfactor_card),
                rx.cond(
                    S.visible_subfactors.length() == 0,
                    rx.callout("No hay subfactores para este filtro.", icon="info", size="1"),
                ),
                spacing="3",
                width="100%",
            ),
            rx.callout("No hay factores relevantes. Ajuste la importancia del decisor en los pasos 1 y 2.",
                       icon="info"),
        ),
        width="100%",
    )


# --- Pasos 5 y 6 ------------------------------------------------------------

def _summary_row(row: SummaryRow) -> rx.Component:
    return rx.table.row(
        rx.table.row_header_cell(
            rx.vstack(rx.text(row.nombre, weight="medium"), rx.text(row.dimension, size="1", color_scheme="gray"),
                      spacing="0")
        ),
        rx.table.cell(importance_badge(row.ir_label)),
        rx.table.cell(rx.code(row.pm)),
        rx.table.cell(row.alcance),
        rx.table.cell(
            rx.match(
                row.status,
                ("evaluated", foda_badge(row.foda)),
                ("pending", rx.badge("Pendiente", color_scheme="amber", variant="soft")),
                rx.badge("Excluido", color_scheme="gray", variant="outline"),
            )
        ),
        opacity=rx.cond(row.status == "irrelevant", "0.55", "1"),
        align="center",
    )


def _foda_tile(c: FodaCount) -> rx.Component:
    return rx.card(
        rx.vstack(
            rx.text(c.foda, size="2", color_scheme="gray"),
            rx.heading(c.count.to_string(), size="7", color=rx.color(foda_color(c.foda), 11)),
            spacing="0",
            align="center",
        ),
        flex="1 1 120px",
    )


def _plan_row(p: PlanRow) -> rx.Component:
    return rx.table.row(
        rx.table.cell(rx.text(p.factor, weight="medium")),
        rx.table.cell(foda_badge(p.tipo_foda)),
        rx.table.cell(rx.text(p.accion, size="2")),
        rx.table.cell(rx.badge(p.prioridad, color_scheme=rx.match(p.prioridad, ("Alta", "red"), ("Media", "amber"),
                                                                    "gray"))),
        align="center",
    )


def _verdict_tab() -> rx.Component:
    return rx.vstack(
        step_intro(
            "Pasos 5 y 6. Matriz FODA y dictamen",
            "Con PM ≥ 3.0 un factor interno es Fortaleza (si no, Debilidad) y uno externo es Oportunidad "
            "(si no, Amenaza). El dictamen base A/B/C se calcula de forma determinista; la IA solo redacta "
            "la justificación y el plan de mitigación.",
        ),
        rx.flex(rx.foreach(S.foda_counts, _foda_tile), gap="3", wrap="wrap", width="100%"),
        table_card(
            rx.table.root(
                rx.table.header(rx.table.row(*[rx.table.column_header_cell(h) for h in
                                               ("Factor", "IR", "PM", "Alcance", "FODA")])),
                rx.table.body(rx.foreach(S.summary, _summary_row)),
                width="100%",
            )
        ),
        rx.cond(
            S.dictamen != "",
            rx.callout(
                rx.vstack(
                    rx.text("Tipo ", S.dictamen, " · ", S.dictamen_codigo, weight="bold"),
                    rx.text(S.dictamen_texto, size="2"),
                    spacing="1",
                ),
                icon="clipboard-check",
                color_scheme=recommendation_color(S.dictamen),
                width="100%",
            ),
            rx.callout(
                rx.text(
                    S.pendientes.to_string() + " factor(es) relevante(s) pendientes de evaluar. ",
                    rx.cond(S.dictamen_provisional != "",
                            rx.text.span("Dictamen provisional: Tipo ", S.dictamen_provisional, ".")),
                ),
                icon="hourglass",
                color_scheme="gray",
                width="100%",
            ),
        ),
        rx.hstack(
            rx.cond(
                (S.dictamen != "") & (S.my_role == Rol.DECISOR.value),
                rx.button(rx.icon("sparkles", size=16), "Generar dictamen ejecutivo",
                          on_click=S.generate_executive_verdict, loading=S.busy),
            ),
            rx.cond(
                (S.dictamen != "") & S.can_edit_decisor,
                rx.button(rx.icon("lock", size=16), "Finalizar evaluación", variant="soft", on_click=S.finalize),
            ),
            rx.cond(
                S.is_final & (S.my_role == Rol.DECISOR.value),
                rx.button(rx.icon("lock-open", size=16), "Reabrir", variant="soft", color_scheme="gray",
                          on_click=S.reopen),
            ),
            wrap="wrap",
        ),
        _task_panel(),
        rx.cond(
            S.resumen_ejecutivo != "",
            rx.card(
                rx.vstack(
                    rx.hstack(rx.heading("Dictamen ejecutivo", size="4"), rx.spacer(),
                              rx.text(S.modelo_utilizado, " · ", S.fecha_recomendacion, size="1",
                                      color_scheme="gray"), width="100%", wrap="wrap"),
                    rx.markdown(S.resumen_ejecutivo),
                    rx.cond(
                        S.plan_accion.length() > 0,
                        rx.vstack(
                            rx.heading("Plan de acción FODA", size="3"),
                            table_card(
                                rx.table.root(
                                    rx.table.header(rx.table.row(*[rx.table.column_header_cell(h) for h in
                                                                   ("Factor", "Tipo", "Acción", "Prioridad")])),
                                    rx.table.body(rx.foreach(S.plan_accion, _plan_row)),
                                    width="100%",
                                )
                            ),
                            width="100%",
                        ),
                    ),
                    spacing="3",
                    width="100%",
                ),
                width="100%",
            ),
        ),
        width="100%",
        spacing="3",
    )


# --- Equipo -----------------------------------------------------------------

def _participant(p: ParticipantRow) -> rx.Component:
    return rx.table.row(rx.table.cell(p.nombre), rx.table.cell(p.email), rx.table.cell(rx.badge(p.rol)))


def _team_tab() -> rx.Component:
    return rx.vstack(
        step_intro(
            "Equipo de evaluación",
            "Invite a otros usuarios registrados. Los decisores editan todo el flujo; los evaluadores "
            "solo puntúan subfactores y registran observaciones.",
        ),
        rx.cond(
            S.my_role == Rol.DECISOR.value,
            rx.form(
                rx.flex(
                    rx.input(name="email", type="email", placeholder="correo@organizacion.org", required=True,
                             flex="1 1 240px"),
                    rx.select([Rol.EVALUADOR.value, Rol.DECISOR.value], name="rol",
                              default_value=Rol.EVALUADOR.value),
                    rx.button(rx.icon("user-plus", size=16), "Invitar", type="submit"),
                    gap="2",
                    wrap="wrap",
                    width="100%",
                ),
                on_submit=S.invite,
                reset_on_submit=True,
                width="100%",
            ),
        ),
        table_card(
            rx.table.root(
                rx.table.header(rx.table.row(*[rx.table.column_header_cell(h) for h in ("Nombre", "Correo", "Rol")])),
                rx.table.body(rx.foreach(S.participants, _participant)),
                width="100%",
            )
        ),
        width="100%",
    )


TABS = [
    ("contexto", "Contexto IA", _context_tab),
    ("relevancia", "1-2 · Relevancia", _relevance_tab),
    ("ponderacion", "3-4 · Ponderación", _weighting_tab),
    ("dictamen", "5-6 · FODA y dictamen", _verdict_tab),
    ("equipo", "Equipo", _team_tab),
]


def evaluation_page() -> rx.Component:
    return page_shell(
        rx.cond(
            S.not_found,
            rx.callout("Evaluación no encontrada o sin acceso.", icon="triangle-alert", color_scheme="red"),
            rx.vstack(
                _header(),
                rx.tabs.root(
                    rx.tabs.list(*[rx.tabs.trigger(label, value=key) for key, label, _ in TABS], overflow_x="auto"),
                    *[rx.tabs.content(view(), value=key, padding_top="8px") for key, _, view in TABS],
                    default_value="relevancia",
                    width="100%",
                ),
                width="100%",
                spacing="3",
            ),
        )
    )
