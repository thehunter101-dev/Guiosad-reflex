"""Contratos Pydantic puros de entrada/salida del núcleo y de los servicios IA."""

from typing import Annotated, Literal

from pydantic import BaseModel, Field

from .constants import AlcanceAplicado, Dictamen, Foda

Nivel = Annotated[int, Field(ge=1, le=4)]
Confianza = Annotated[float, Field(ge=0.0, le=1.0)]


# --- Evaluación (pasos 1-6) -------------------------------------------------

class FactorInput(BaseModel):
    factor_id: int
    nombre: str
    is_aplicado: Nivel
    id_decisor: Nivel
    alcance: AlcanceAplicado
    # PS de cada subfactor activo; ``None`` = aún sin puntuar.
    scores: list[Nivel | None] = Field(default_factory=list)


class EvaluacionInput(BaseModel):
    factores: list[FactorInput]


class FactorResultado(BaseModel):
    factor_id: int
    nombre: str
    is_aplicado: int
    id_decisor: int
    ir: int
    alcance: AlcanceAplicado
    es_relevante: bool
    pendiente: bool  # Relevante pero con subfactores sin puntuar.
    pm: float | None = None
    foda: Foda | None = None  # ``Excluido`` si no es relevante; ``None`` si pendiente.


class ResultadoEvaluacion(BaseModel):
    factores: list[FactorResultado]
    relevantes: int
    pendientes: int
    conteo_foda: dict[Foda, int]
    # Dictamen definitivo: solo cuando todos los factores relevantes están evaluados.
    dictamen: Dictamen | None = None
    # Dictamen con los factores evaluados hasta ahora (vista previa).
    dictamen_provisional: Dictamen | None = None

    @property
    def completo(self) -> bool:
        return self.dictamen is not None


# --- Calibración bibliográfica ---------------------------------------------

class CalibracionFactorInput(BaseModel):
    factor_id: int
    citas_pertinentes: Annotated[int, Field(ge=0)]  # c_i
    subfactores_activos: Annotated[int, Field(gt=0)]  # n_i


class CalibracionFactorResultado(CalibracionFactorInput):
    ratio_normalizado: float  # r_i
    il_calculado: int
    ie_fijo: int
    is_calculado: int


class CalibracionResultado(BaseModel):
    q1: float
    q2: float
    q3: float
    factores: list[CalibracionFactorResultado]


# --- Contratos IA -----------------------------------------------------------

class CitationItem(BaseModel):
    archivo: str
    ubicacion: str = Field(description="Línea, rango de líneas, página o sección")
    fragmento: str = Field(description="Fragmento exacto citado del archivo")


class SubfactorAISuggestion(BaseModel):
    subfactor_id: int
    score_ia: Literal[1, 2, 3, 4]
    nivel_confianza: Confianza
    justificacion: str
    citas: list[CitationItem] = Field(default_factory=list)


class SubfactorPropuesta(SubfactorAISuggestion):
    """Sugerencia tras aplicar la regla de fallback del núcleo."""

    requiere_revision: bool = False


class EvidenciaValidada(BaseModel):
    factor_id: int
    afirmacion: str
    score_evaluador: Nivel
    observacion: str | None = None
    citas: list[CitationItem] = Field(default_factory=list)


class VerdictRequest(BaseModel):
    nombre_software: str
    version: str | None = None
    organizacion: str | None = None
    resultado: ResultadoEvaluacion
    evidencias: list[EvidenciaValidada] = Field(default_factory=list)


class PlanAccionItem(BaseModel):
    factor_id: int
    factor_nombre: str
    tipo_foda: Literal["Debilidad", "Amenaza"]
    accion: str
    prioridad: Literal["Alta", "Media", "Baja"]


class VerdictResponse(BaseModel):
    dictamen_base: Dictamen
    resumen_ejecutivo: str
    plan_accion: list[PlanAccionItem] = Field(default_factory=list)
