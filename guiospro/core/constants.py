"""Escalas, matriz cartesiana y enumeraciones de la metodología GUIOS.

Todas las escalas usan enteros de 1 a 4; la posición en cada lista es ``valor - 1``.
Este módulo es Python puro: no importa reflex, google-genai, sqlmodel ni httpx.
"""

from enum import StrEnum

MIN_LEVEL = 1
MAX_LEVEL = 4

# Escala de importancia (IE, IL, IS, ID, IR).
IMPORTANCE_LEVELS: list[str] = ["Irrelevante", "Opcional", "Importante", "Fundamental"]

# Escala de cumplimiento de subfactor (PS).
COMPLIANCE_LEVELS: list[str] = [
    "No cumple el requisito",
    "Desconozco si cumple el requisito",
    "Cumple parcialmente el requisito",
    "Cumple el requisito",
]

# Matriz cartesiana de doble uso: IS = M(IE, IL) e IR = M(ID, IS).
# Clave: (eje Y = IE o ID, eje X = IL o IS).
CARTESIAN_MATRIX: dict[tuple[int, int], int] = {
    (4, 1): 2, (4, 2): 3, (4, 3): 3, (4, 4): 4,
    (3, 1): 2, (3, 2): 2, (3, 3): 3, (3, 4): 3,
    (2, 1): 1, (2, 2): 2, (2, 3): 2, (2, 4): 3,
    (1, 1): 1, (1, 2): 1, (1, 3): 2, (1, 4): 2,
}  # fmt: skip

# Importancia del experto: fija en "Importante" para los 18 factores.
IE_FIJO = 3
# Desde "Importante", una debilidad/amenaza lleva el dictamen a Tipo C.
IMPORTANT_LEVEL = 3
# Ponderación media a partir de la cual un factor es favorable.
UMBRAL_FODA = 3.0
# Por debajo de esta confianza la propuesta IA se degrada a "Desconozco" (2).
UMBRAL_CONFIANZA_IA = 0.45
SCORE_DESCONOZCO = 2


class Alcance(StrEnum):
    """Alcance definido en el catálogo."""

    INTERNO = "Interno"
    EXTERNO = "Externo"
    CONFIGURABLE = "Configurable"  # Solo Soporte: el decisor elige.


class AlcanceAplicado(StrEnum):
    INTERNO = "Interno"
    EXTERNO = "Externo"


class Foda(StrEnum):
    FORTALEZA = "Fortaleza"
    OPORTUNIDAD = "Oportunidad"
    DEBILIDAD = "Debilidad"
    AMENAZA = "Amenaza"
    EXCLUIDO = "Excluido"


FODA_POSITIVOS = frozenset({Foda.FORTALEZA, Foda.OPORTUNIDAD})
FODA_NEGATIVOS = frozenset({Foda.DEBILIDAD, Foda.AMENAZA})


class Dictamen(StrEnum):
    A = "A"
    B = "B"
    C = "C"


DICTAMEN_CODIGO: dict[Dictamen, str] = {
    Dictamen.A: "ADOPTAR_SIN_OBSERVACIONES",
    Dictamen.B: "ADOPTAR_CON_MATICES",
    Dictamen.C: "ANALIZAR_O_POSPONER",
}

DICTAMEN_TEXTO: dict[Dictamen, str] = {
    Dictamen.A: (
        "Adoptar. Todos los factores relevantes han sido identificados como Oportunidades "
        "y/o Fortalezas: la organización cumple satisfactoriamente los requisitos para "
        "adoptar la solución FLOSS."
    ),
    Dictamen.B: (
        "Es posible adoptar con matices. Se detectaron Debilidades y/o Amenazas únicamente "
        "en factores de importancia relativa Opcional; se sugiere revisar los criterios que "
        "no alcanzan lo mínimo requerido."
    ),
    Dictamen.C: (
        "Analizar o posponer. Existen Debilidades y/o Amenazas en factores Importantes o "
        "Fundamentales, o los factores negativos superan a los positivos. La organización "
        "debe proveer recursos: mejoras internas para factores internos y recursos de "
        "ingeniería para factores externos."
    ),
}


class Rol(StrEnum):
    ADMIN = "admin"
    DECISOR = "decisor"
    EVALUADOR = "evaluador"


class ModoEvaluacion(StrEnum):
    HIBRIDO_IA = "hibrido_ia"
    MANUAL = "manual"


class EstadoEvaluacion(StrEnum):
    PASO_1 = "paso_1"
    PASO_2 = "paso_2"
    PASO_3 = "paso_3"
    REVISION = "revision"
    FINALIZADA = "finalizada"


class CategoriaChunk(StrEnum):
    CODIGO = "codigo"
    LICENCIA = "licencia"
    DOCUMENTACION = "documentacion"
    CONFIGURACION = "configuracion"


def importance_label(level: int) -> str:
    return IMPORTANCE_LEVELS[level - 1]


def compliance_label(level: int) -> str:
    return COMPLIANCE_LEVELS[level - 1]


def cartesian(y: int, x: int) -> int:
    """Aplica la matriz cartesiana M(y, x)."""
    try:
        return CARTESIAN_MATRIX[(y, x)]
    except KeyError:
        raise ValueError(f"Valores fuera de escala 1..4: ({y}, {x})") from None
