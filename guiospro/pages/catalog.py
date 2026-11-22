"""Gestor del catálogo GUIOS: dimensiones, factores y subfactores (solo administradores)."""

import reflex as rx

from ..components import page_shell, step_intro, table_card
from ..state.catalog_state import ALCANCES, CatalogState as S
from ..state.models import CatalogFactorRow, CatalogSubfactorRow, DimensionRow


def _toggle(active, on_click) -> rx.Component:
    return rx.switch(checked=active, on_change=lambda _v: on_click)


def _labeled(label: str, control: rx.Component) -> rx.Component:
    return rx.vstack(rx.text(label, size="2", weight="medium"), control, spacing="1", width="100%")


def _form_error() -> rx.Component:
    return rx.cond(S.form_error != "", rx.callout(S.form_error, icon="triangle-alert", color_scheme="red", size="1"))


def _dialog_actions() -> rx.Component:
    return rx.flex(
        rx.dialog.close(rx.button("Cancelar", variant="soft", color_scheme="gray", type="button")),
        rx.button("Guardar", type="submit"),
        spacing="3",
        justify="end",
        width="100%",
    )


def _dimension_dialog() -> rx.Component:
    return rx.dialog.root(
        rx.dialog.content(
            rx.dialog.title(rx.cond(S.dim_edit.id > 0, "Editar dimensión", "Nueva dimensión")),
            rx.form(
                rx.vstack(
                    _labeled("Código", rx.input(name="codigo", default_value=S.dim_edit.codigo, required=True)),
                    _labeled("Nombre", rx.input(name="nombre", default_value=S.dim_edit.nombre, required=True)),
                    _labeled("Descripción", rx.text_area(name="descripcion", default_value=S.dim_edit.descripcion)),
                    _form_error(),
                    _dialog_actions(),
                    spacing="3",
                ),
                on_submit=S.save_dimension,
                reset_on_submit=False,
                key=S.dim_edit.id,
            ),
        ),
        open=S.dim_dialog,
        on_open_change=S.set_dim_dialog,
    )


def _factor_dialog() -> rx.Component:
    return rx.dialog.root(
        rx.dialog.content(
            rx.dialog.title(rx.cond(S.factor_edit.id > 0, "Editar factor", "Nuevo factor")),
            rx.form(
                rx.vstack(
                    _labeled("Código", rx.input(name="codigo", default_value=S.factor_edit.codigo, required=True)),
                    _labeled("Nombre", rx.input(name="nombre", default_value=S.factor_edit.nombre, required=True)),
                    _labeled("Dimensión", rx.select(S.dimension_names, name="dimension",
                                                    default_value=S.factor_dimension_name)),
                    _labeled("Alcance", rx.select(ALCANCES, name="tipo_alcance",
                                                  default_value=S.factor_edit.tipo_alcance)),
                    _labeled("Cadena de búsqueda bibliográfica",
                             rx.text_area(name="cadena_busqueda", default_value=S.factor_edit.cadena_busqueda,
                                          rows="4")),
                    _form_error(),
                    _dialog_actions(),
                    spacing="3",
                ),
                on_submit=S.save_factor,
                reset_on_submit=False,
                key=S.factor_edit.id,
            ),
            max_width="640px",
        ),
        open=S.factor_dialog,
        on_open_change=S.set_factor_dialog,
    )


def _subfactor_dialog() -> rx.Component:
    return rx.dialog.root(
        rx.dialog.content(
            rx.dialog.title(rx.cond(S.sub_edit.id > 0, "Editar subfactor", "Nuevo subfactor")),
            rx.form(
                rx.vstack(
                    _labeled("Código", rx.input(name="codigo", default_value=S.sub_edit.codigo, required=True)),
                    _labeled("Afirmación", rx.text_area(name="afirmacion", default_value=S.sub_edit.afirmacion,
                                                        required=True)),
                    _labeled("Guía de verificación (orienta la búsqueda RAG)",
                             rx.text_area(name="guia_verificacion", default_value=S.sub_edit.guia_verificacion)),
                    _form_error(),
                    _dialog_actions(),
                    spacing="3",
                ),
                on_submit=S.save_subfactor,
                reset_on_submit=False,
                key=S.sub_edit.id,
            ),
            max_width="640px",
        ),
        open=S.sub_dialog,
        on_open_change=S.set_sub_dialog,
    )


def _dimension_row(d: DimensionRow) -> rx.Component:
    return rx.table.row(
        rx.table.cell(rx.code(d.codigo)),
        rx.table.row_header_cell(d.nombre),
        rx.table.cell(_toggle(d.activa, S.toggle_dimension(d.id))),
        rx.table.cell(rx.icon_button(rx.icon("pencil", size=14), size="1", variant="ghost",
                                     on_click=S.open_dimension(d.id))),
        align="center",
    )


def _factor_row(f: CatalogFactorRow) -> rx.Component:
    return rx.table.row(
        rx.table.cell(rx.code(f.codigo)),
        rx.table.row_header_cell(
            rx.link(f.nombre, on_click=S.select_factor(f.id), cursor="pointer",
                    weight=rx.cond(f.id == S.selected_factor_id, "bold", "regular"))
        ),
        rx.table.cell(f.dimension),
        rx.table.cell(f.tipo_alcance),
        rx.table.cell(f.is_vigente),
        rx.table.cell(f.subfactores_activos),
        rx.table.cell(_toggle(f.activo, S.toggle_factor(f.id))),
        rx.table.cell(
            rx.hstack(
                rx.icon_button(rx.icon("pencil", size=14), size="1", variant="ghost", on_click=S.open_factor(f.id)),
                rx.icon_button(rx.icon("trash-2", size=14), size="1", variant="ghost", color_scheme="red",
                               on_click=S.delete_factor(f.id)),
            )
        ),
        align="center",
    )


def _subfactor_row(s: CatalogSubfactorRow) -> rx.Component:
    return rx.table.row(
        rx.table.cell(rx.code(s.codigo)),
        rx.table.cell(rx.vstack(rx.text(s.afirmacion, size="2"),
                                rx.text(s.guia_verificacion, size="1", color_scheme="gray"), spacing="0")),
        rx.table.cell(_toggle(s.activo, S.toggle_subfactor(s.id))),
        rx.table.cell(
            rx.hstack(
                rx.icon_button(rx.icon("pencil", size=14), size="1", variant="ghost", on_click=S.open_subfactor(s.id)),
                rx.icon_button(rx.icon("trash-2", size=14), size="1", variant="ghost", color_scheme="red",
                               on_click=S.delete_subfactor(s.id)),
            )
        ),
        align="center",
    )


def _section(title: str, on_new, *children) -> rx.Component:
    return rx.vstack(
        rx.hstack(rx.heading(title, size="4"), rx.spacer(),
                  rx.button(rx.icon("plus", size=14), "Nuevo", size="1", on_click=on_new), width="100%"),
        *children,
        width="100%",
        spacing="2",
    )


def _table(headers: tuple[str, ...], items, render) -> rx.Component:
    return table_card(
        rx.table.root(
            rx.table.header(rx.table.row(*[rx.table.column_header_cell(h) for h in headers])),
            rx.table.body(rx.foreach(items, render)),
            width="100%",
            size="1",
        )
    )


def catalog_page() -> rx.Component:
    return page_shell(
        step_intro(
            "Catálogo GUIOS",
            "Gestione dimensiones, factores y subfactores sin modificar código. Los cambios aplican a las "
            "evaluaciones nuevas; desactive en lugar de eliminar los elementos ya usados en evaluaciones.",
        ),
        _section("Dimensiones", S.open_dimension(0),
                 _table(("Código", "Nombre", "Activa", ""), S.dimensions, _dimension_row)),
        _section("Factores", S.open_factor(0),
                 _table(("Código", "Factor", "Dimensión", "Alcance", "IS vigente", "Subf. activos", "Activo", ""),
                        S.factors, _factor_row)),
        _section(
            "Subfactores",
            S.open_subfactor(0),
            rx.text("Factor seleccionado: ", rx.text.strong(S.selected_factor_name), size="2"),
            _table(("Código", "Afirmación / guía", "Activo", ""), S.subfactors, _subfactor_row),
        ),
        _dimension_dialog(),
        _factor_dialog(),
        _subfactor_dialog(),
    )
