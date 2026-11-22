import reflex as rx


def level_select(
    options: list[str], value: rx.Var[str], on_change, **props
) -> rx.Component:
    """Selector de una escala de niveles (importancia o cumplimiento)."""
    return rx.select(options, value=value, on_change=on_change, size="2", width="100%", **props)
