"""Detección determinista de licencias FLOSS y su clasificación."""

import json
import re
import tomllib
from dataclasses import dataclass
from enum import StrEnum


class TipoLicencia(StrEnum):
    PERMISIVA = "Permisiva"
    COPYLEFT_DEBIL = "Copyleft débil"
    COPYLEFT_FUERTE = "Copyleft fuerte"
    COPYLEFT_RED = "Copyleft de red"
    DOMINIO_PUBLICO = "Dominio público"
    DESCONOCIDA = "Desconocida"


SPDX_TIPO: dict[str, TipoLicencia] = {
    "MIT": TipoLicencia.PERMISIVA,
    "Apache-2.0": TipoLicencia.PERMISIVA,
    "BSD-2-Clause": TipoLicencia.PERMISIVA,
    "BSD-3-Clause": TipoLicencia.PERMISIVA,
    "ISC": TipoLicencia.PERMISIVA,
    "Zlib": TipoLicencia.PERMISIVA,
    "PostgreSQL": TipoLicencia.PERMISIVA,
    "BSL-1.0": TipoLicencia.PERMISIVA,
    "OFL-1.1": TipoLicencia.COPYLEFT_DEBIL,
    "LGPL-2.1": TipoLicencia.COPYLEFT_DEBIL,
    "LGPL-3.0": TipoLicencia.COPYLEFT_DEBIL,
    "MPL-2.0": TipoLicencia.COPYLEFT_DEBIL,
    "EPL-2.0": TipoLicencia.COPYLEFT_DEBIL,
    "GPL-2.0": TipoLicencia.COPYLEFT_FUERTE,
    "GPL-3.0": TipoLicencia.COPYLEFT_FUERTE,
    "AGPL-3.0": TipoLicencia.COPYLEFT_RED,
    "Unlicense": TipoLicencia.DOMINIO_PUBLICO,
    "CC0-1.0": TipoLicencia.DOMINIO_PUBLICO,
}

# Firmas de texto ordenadas de más a menos específicas.
_SIGNATURES: list[tuple[str, re.Pattern]] = [
    ("AGPL-3.0", re.compile(r"GNU AFFERO GENERAL PUBLIC LICENSE", re.I)),
    ("LGPL-3.0", re.compile(r"GNU LESSER GENERAL PUBLIC LICENSE\s+Version 3", re.I)),
    ("LGPL-2.1", re.compile(r"GNU LESSER GENERAL PUBLIC LICENSE\s+Version 2\.1", re.I)),
    ("GPL-3.0", re.compile(r"GNU GENERAL PUBLIC LICENSE\s+Version 3", re.I)),
    ("GPL-2.0", re.compile(r"GNU GENERAL PUBLIC LICENSE\s+Version 2", re.I)),
    ("MPL-2.0", re.compile(r"Mozilla Public License,?\s+(?:Version|v\.?)\s*2\.0", re.I)),
    ("EPL-2.0", re.compile(r"Eclipse Public License\s*-?\s*v?\s*2\.0", re.I)),
    ("Apache-2.0", re.compile(r"Apache License,?\s+Version 2\.0", re.I)),
    ("BSL-1.0", re.compile(r"Boost Software License\s*-?\s*Version 1\.0", re.I)),
    ("OFL-1.1", re.compile(r"SIL OPEN FONT LICENSE\s*Version 1\.1", re.I)),
    ("MIT", re.compile(r"Permission is hereby granted, free of charge", re.I)),
    ("BSD-3-Clause", re.compile(r"Neither the name of .{1,200} nor the names of", re.I | re.S)),
    ("BSD-2-Clause", re.compile(r"Redistributions in binary form must reproduce", re.I)),
    ("ISC", re.compile(r"Permission to use, copy, modify, and/or distribute this software", re.I)),
    ("Unlicense", re.compile(r"This is free and unencumbered software released into the public domain", re.I)),
    ("CC0-1.0", re.compile(r"CC0 1\.0 Universal", re.I)),
]
_SPDX_HEADER = re.compile(r"SPDX-License-Identifier:\s*([A-Za-z0-9.+\-]+)")


@dataclass(frozen=True)
class LicenciaDetectada:
    spdx: str
    tipo: TipoLicencia
    archivo: str
    metodo: str  # texto | manifiesto | cabecera-spdx


def normalize_spdx(identifier: str) -> str:
    ident = identifier.strip().removesuffix("-only").removesuffix("-or-later").removesuffix("+")
    for known in SPDX_TIPO:
        if ident.lower() == known.lower():
            return known
    return ident


def classify(spdx: str) -> TipoLicencia:
    return SPDX_TIPO.get(normalize_spdx(spdx), TipoLicencia.DESCONOCIDA)


def detect_from_text(text: str) -> str | None:
    head = text[:20000]
    for spdx, pattern in _SIGNATURES:
        if pattern.search(head):
            # BSD-3 también contiene la cláusula de BSD-2; la firma de BSD-3 va antes.
            return spdx
    return None


def detect_from_manifest(filename: str, text: str) -> str | None:
    try:
        if filename == "package.json" or filename == "composer.json":
            lic = json.loads(text).get("license")
            return lic if isinstance(lic, str) else None
        if filename == "pyproject.toml":
            project = tomllib.loads(text).get("project", {})
            lic = project.get("license")
            if isinstance(lic, str):
                return lic
            if isinstance(lic, dict):
                return lic.get("text") if len(lic.get("text", "")) < 40 else None
        if filename == "Cargo.toml":
            return tomllib.loads(text).get("package", {}).get("license")
    except (ValueError, tomllib.TOMLDecodeError, AttributeError):
        return None
    return None


def detect_from_filename(filename: str) -> str | None:
    """``LICENSES/<SPDX>.txt`` (convención REUSE): el nombre del archivo es el identificador."""
    stem = filename.rsplit(".", 1)[0]
    norm = normalize_spdx(stem)
    return norm if norm in SPDX_TIPO else None


def detect_spdx_header(text: str) -> str | None:
    m = _SPDX_HEADER.search(text[:2000])
    return m.group(1) if m else None


def make(spdx: str, archivo: str, metodo: str) -> LicenciaDetectada:
    norm = normalize_spdx(spdx)
    return LicenciaDetectada(spdx=norm, tipo=classify(norm), archivo=archivo, metodo=metodo)
