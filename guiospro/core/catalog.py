"""Catálogo base GUIOS (3 dimensiones, 18 factores, 61 subfactores) desde los CSV.

- ``data/factors.csv``: Codigo, Factor, Sugerida (1-4), Alcance, CadenaBusqueda.
- ``data/subfactors.csv``: Codigo, Dimensión, Factor, Subfactor, GuiaVerificacion.

Separados por tabuladores. Se usan para la carga inicial (seed) de la base de datos;
en ejecución, el catálogo vigente vive en PostgreSQL y se gestiona desde la UI.
"""

import csv
import unicodedata
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

from .constants import MAX_LEVEL, MIN_LEVEL, Alcance

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
FACTORS_FILE = DATA_DIR / "factors.csv"
SUBFACTORS_FILE = DATA_DIR / "subfactors.csv"

DIMENSION_CODES = {"Tecnológica": "TEC", "Organizacional": "ORG", "Económica": "ECO"}


@dataclass(frozen=True)
class SubfactorDef:
    codigo: str
    afirmacion: str
    guia_verificacion: str


@dataclass(frozen=True)
class FactorDef:
    codigo: str
    name: str
    dimension: str
    suggested_importance: int
    scope: Alcance
    cadena_busqueda: str
    subfactors: tuple[SubfactorDef, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class Catalog:
    factors: tuple[FactorDef, ...]

    @property
    def dimensions(self) -> list[str]:
        return list(dict.fromkeys(f.dimension for f in self.factors))

    @property
    def subfactor_count(self) -> int:
        return sum(len(f.subfactors) for f in self.factors)


def _clean(value: str) -> str:
    return unicodedata.normalize("NFC", value.strip())


def _read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as fh:
        return [
            {_clean(k): _clean(v) for k, v in row.items()}
            for row in csv.DictReader(fh, delimiter="\t")
        ]


def load_catalog(
    factors_file: Path = FACTORS_FILE, subfactors_file: Path = SUBFACTORS_FILE
) -> Catalog:
    factor_info = {row["Factor"]: row for row in _read_tsv(factors_file)}

    grouped: dict[str, tuple[str, list[SubfactorDef]]] = {}
    for row in _read_tsv(subfactors_file):
        _, subs = grouped.setdefault(row["Factor"], (row["Dimensión"], []))
        subs.append(SubfactorDef(row["Codigo"], row["Subfactor"], row["GuiaVerificacion"]))

    factors = []
    for name, (dimension, subs) in grouped.items():
        if name not in factor_info:
            raise ValueError(f"El factor '{name}' no está definido en {factors_file.name}")
        info = factor_info[name]
        suggested = int(info["Sugerida"])
        if not MIN_LEVEL <= suggested <= MAX_LEVEL:
            raise ValueError(f"Importancia sugerida fuera de rango para '{name}': {suggested}")
        factors.append(
            FactorDef(
                codigo=info["Codigo"],
                name=name,
                dimension=dimension,
                suggested_importance=suggested,
                scope=Alcance(info["Alcance"]),
                cadena_busqueda=info["CadenaBusqueda"],
                subfactors=tuple(subs),
            )
        )
    return Catalog(factors=tuple(factors))


@cache
def get_catalog() -> Catalog:
    return load_catalog()
