"""Filas serializables que renderiza la interfaz (construidas por los estados)."""

from dataclasses import dataclass, field


@dataclass
class EvaluationCard:
    id: int = 0
    nombre: str = ""
    version: str = ""
    organizacion: str = ""
    modo: str = ""
    estado: str = ""
    estado_label: str = ""
    dictamen: str = ""
    actualizado: str = ""
    puede_borrar: bool = False


@dataclass
class FactorRow:
    """Pasos 1 y 2."""

    ef_id: int = 0
    nombre: str = ""
    dimension: str = ""
    is_label: str = ""
    decisor_label: str = ""
    ir_label: str = ""
    relevante: bool = True
    alcance: str = ""
    alcance_editable: bool = False


@dataclass
class EvidenceRow:
    archivo: str = ""
    ubicacion: str = ""
    fragmento: str = ""


@dataclass
class SubfactorCard:
    """Pasos 3 y 4: tarjeta HITL en la vista continua."""

    es_id: int = 0
    codigo: str = ""
    factor: str = ""
    dimension: str = ""
    factor_pm: str = ""
    show_header: bool = False
    afirmacion: str = ""
    guia: str = ""
    score_label: str = ""
    score_ia: int = 0
    score_ia_label: str = ""
    confianza_pct: str = ""
    baja_confianza: bool = False
    justificacion: str = ""
    observacion: str = ""
    validado: bool = False
    revision_prioritaria: bool = False
    evidencias: list[EvidenceRow] = field(default_factory=list)


@dataclass
class SummaryRow:
    """Pasos 5 y 6."""

    nombre: str = ""
    dimension: str = ""
    ir_label: str = ""
    status: str = ""  # evaluated | pending | irrelevant
    pm: str = ""
    alcance: str = ""
    foda: str = ""


@dataclass
class FodaCount:
    foda: str = ""
    count: int = 0


@dataclass
class PlanRow:
    factor: str = ""
    tipo_foda: str = ""
    accion: str = ""
    prioridad: str = ""


@dataclass
class ParticipantRow:
    nombre: str = ""
    email: str = ""
    rol: str = ""


@dataclass
class CalibrationRow:
    factor_id: int = 0
    factor: str = ""
    citas: int = 0
    subfactores: int = 0
    ratio: str = ""
    il: int = 0
    ie: int = 3
    is_: int = 0


@dataclass
class CalibrationRun:
    id: int = 0
    fecha: str = ""
    periodo: str = ""
    vigente: bool = False
    observaciones: str = ""


@dataclass
class ArticleRow:
    titulo: str = ""
    autores: str = ""
    anio: str = ""
    fuente: str = ""
    enlace: str = ""
    pertinente: bool = False
    razon: str = ""


@dataclass
class DimensionRow:
    id: int = 0
    codigo: str = ""
    nombre: str = ""
    descripcion: str = ""
    activa: bool = True


@dataclass
class CatalogFactorRow:
    id: int = 0
    dimension_id: int = 0
    dimension: str = ""
    codigo: str = ""
    nombre: str = ""
    tipo_alcance: str = ""
    cadena_busqueda: str = ""
    is_vigente: int = 3
    activo: bool = True
    subfactores_activos: int = 0


@dataclass
class CatalogSubfactorRow:
    id: int = 0
    factor_id: int = 0
    codigo: str = ""
    afirmacion: str = ""
    guia_verificacion: str = ""
    activo: bool = True
