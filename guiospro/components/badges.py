"""Insignias de color para importancia, cumplimiento, FODA y dictamen."""

import reflex as rx

from ..core.constants import Foda


def importance_badge(label: rx.Var[str] | str) -> rx.Component:
    return rx.badge(
        label,
        color_scheme=rx.match(
            label, ("Fundamental", "indigo"), ("Importante", "blue"), ("Opcional", "cyan"), "gray"
        ),
        variant="soft",
    )


def score_color(score: rx.Var[int]) -> rx.Var[str]:
    return rx.match(score, (1, "red"), (2, "gray"), (3, "amber"), (4, "green"), "gray")


def foda_color(foda: rx.Var[str]) -> rx.Var[str]:
    return rx.match(
        foda,
        (Foda.FORTALEZA.value, "green"),
        (Foda.OPORTUNIDAD.value, "green"),
        (Foda.DEBILIDAD.value, "red"),
        (Foda.AMENAZA.value, "red"),
        "gray",
    )


def foda_badge(foda: rx.Var[str]) -> rx.Component:
    return rx.badge(foda, color_scheme=foda_color(foda), variant="solid", size="2")


def recommendation_color(level: rx.Var[str]) -> rx.Var[str]:
    return rx.match(level, ("A", "green"), ("B", "amber"), ("C", "red"), "gray")


def dictamen_badge(level: rx.Var[str]) -> rx.Component:
    return rx.cond(
        level != "",
        rx.badge("Tipo ", level, color_scheme=recommendation_color(level), variant="solid", size="2"),
        rx.badge("Pendiente", color_scheme="gray", variant="soft", size="2"),
    )
