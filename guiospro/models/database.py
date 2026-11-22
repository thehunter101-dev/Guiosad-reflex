"""Modelo relacional y vectorial de GUIOSAD (PostgreSQL 16 + pgvector).

Las enumeraciones se guardan como texto con ``CHECK`` para simplificar migraciones;
los valores válidos provienen de ``core.constants``.
"""

from datetime import UTC, datetime

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.types import JSON, TypeDecorator
from sqlmodel import Field, SQLModel

from ..core.constants import (
    Alcance,
    AlcanceAplicado,
    CategoriaChunk,
    Dictamen,
    EstadoEvaluacion,
    Foda,
    ModoEvaluacion,
    Rol,
)

EMBEDDING_DIM = 768


def _now() -> datetime:
    return datetime.now(UTC)


def _in(column: str, enum) -> str:
    values = ", ".join(f"'{e.value}'" for e in enum)
    return f"{column} IN ({values})"


def _range(column: str, low: int = 1, high: int = 4, nullable: bool = False) -> str:
    check = f"{column} BETWEEN {low} AND {high}"
    return f"({column} IS NULL OR {check})" if nullable else check


class EmbeddingType(TypeDecorator):
    """``vector(768)`` en PostgreSQL; JSON en otros motores (pruebas con SQLite)."""

    impl = JSON
    cache_ok = True

    def __init__(self, dim: int = EMBEDDING_DIM):
        super().__init__()
        self.dim = dim

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(Vector(self.dim))
        return dialect.type_descriptor(JSON(none_as_null=True))

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return [float(v) for v in value]


def _fk(target: str, nullable: bool = False, **kw):
    return Field(foreign_key=target, ondelete="CASCADE", index=True, nullable=nullable, **kw)


# --- 1. Usuarios ------------------------------------------------------------

class Usuario(SQLModel, table=True):
    __tablename__ = "usuario"
    __table_args__ = (sa.CheckConstraint(_in("rol", Rol), name="ck_usuario_rol"),)

    id: int | None = Field(default=None, primary_key=True)
    nombre_completo: str = Field(max_length=200)
    email: str = Field(max_length=255, unique=True, index=True)
    password_hash: str = Field(max_length=255)
    rol: str = Field(default=Rol.DECISOR.value, max_length=20)
    organizacion: str | None = Field(default=None, max_length=200)
    activo: bool = True
    creado_en: datetime = Field(default_factory=_now, sa_type=sa.DateTime(timezone=True))


# --- 2-4. Calibración bibliográfica ----------------------------------------

class CalibracionLiteratura(SQLModel, table=True):
    __tablename__ = "calibracion_literatura"

    id: int | None = Field(default=None, primary_key=True)
    anio_inicio: int = 2020
    anio_fin: int = 2025
    usuario_id: int | None = Field(default=None, foreign_key="usuario.id", ondelete="SET NULL")
    es_vigente: bool = False
    fecha_ejecucion: datetime = Field(default_factory=_now, sa_type=sa.DateTime(timezone=True))
    observaciones: str | None = Field(default=None, sa_type=sa.Text)


class ArticuloLiteratura(SQLModel, table=True):
    __tablename__ = "articulo_literatura"

    id: int | None = Field(default=None, primary_key=True)
    calibracion_id: int = _fk("calibracion_literatura.id")
    factor_id: int = _fk("factor.id")
    titulo: str = Field(sa_type=sa.Text)
    autores: str | None = Field(default=None, sa_type=sa.Text)
    anio_publicacion: int | None = None
    fuente_indexada: str = Field(max_length=50)
    doi_o_url: str | None = Field(default=None, max_length=500)
    abstract: str | None = Field(default=None, sa_type=sa.Text)
    es_pertinente: bool = False
    razon_pertinencia_ia: str | None = Field(default=None, sa_type=sa.Text)


class FactorCalibracion(SQLModel, table=True):
    __tablename__ = "factor_calibracion"
    __table_args__ = (
        sa.UniqueConstraint("calibracion_id", "factor_id"),
        sa.CheckConstraint(_range("il_calculado"), name="ck_fc_il"),
        sa.CheckConstraint(_range("is_calculado"), name="ck_fc_is"),
    )

    id: int | None = Field(default=None, primary_key=True)
    calibracion_id: int = _fk("calibracion_literatura.id")
    factor_id: int = _fk("factor.id")
    citas_pertinentes: int = 0
    subfactores_activos: int
    ratio_normalizado: float
    il_calculado: int
    ie_fijo: int = 3
    is_calculado: int


# --- 5-7. Catálogo GUIOS ----------------------------------------------------

class Dimension(SQLModel, table=True):
    __tablename__ = "dimension"

    id: int | None = Field(default=None, primary_key=True)
    codigo: str = Field(max_length=10, unique=True)
    nombre: str = Field(max_length=100, unique=True)
    descripcion: str | None = Field(default=None, sa_type=sa.Text)
    activa: bool = True


class Factor(SQLModel, table=True):
    __tablename__ = "factor"
    __table_args__ = (
        sa.CheckConstraint(_in("tipo_alcance", Alcance), name="ck_factor_alcance"),
        sa.CheckConstraint(_range("is_vigente"), name="ck_factor_is"),
        sa.CheckConstraint(_range("ie_base"), name="ck_factor_ie"),
    )

    id: int | None = Field(default=None, primary_key=True)
    dimension_id: int = _fk("dimension.id")
    codigo: str = Field(max_length=20, unique=True)
    nombre: str = Field(max_length=150)
    tipo_alcance: str = Field(max_length=20)
    cadena_busqueda: str = Field(default="", sa_type=sa.Text)
    ie_base: int = 3
    is_vigente: int = 3
    activo: bool = True
    orden: int = 0


class Subfactor(SQLModel, table=True):
    __tablename__ = "subfactor"

    id: int | None = Field(default=None, primary_key=True)
    factor_id: int = _fk("factor.id")
    codigo: str = Field(max_length=20, unique=True)
    afirmacion: str = Field(sa_type=sa.Text)
    guia_verificacion: str | None = Field(default=None, sa_type=sa.Text)
    subfactor_activo: bool = True
    orden: int = 0


# --- 8-11. Evaluación -------------------------------------------------------

class Evaluacion(SQLModel, table=True):
    __tablename__ = "evaluacion"
    __table_args__ = (
        sa.CheckConstraint(_in("modo", ModoEvaluacion), name="ck_eval_modo"),
        sa.CheckConstraint(_in("estado", EstadoEvaluacion), name="ck_eval_estado"),
        sa.CheckConstraint(
            f"dictamen_base IS NULL OR {_in('dictamen_base', Dictamen)}", name="ck_eval_dictamen"
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    usuario_propietario_id: int = _fk("usuario.id")
    calibracion_id: int | None = Field(
        default=None, foreign_key="calibracion_literatura.id", ondelete="SET NULL"
    )
    nombre_software: str = Field(max_length=200)
    version: str | None = Field(default=None, max_length=50)
    url_repositorio: str | None = Field(default=None, max_length=500)
    organizacion: str | None = Field(default=None, max_length=200)
    modo: str = Field(default=ModoEvaluacion.MANUAL.value, max_length=20)
    estado: str = Field(default=EstadoEvaluacion.PASO_1.value, max_length=20)
    dictamen_base: str | None = Field(default=None, max_length=1)
    creado_en: datetime = Field(default_factory=_now, sa_type=sa.DateTime(timezone=True))
    actualizado_en: datetime = Field(default_factory=_now, sa_type=sa.DateTime(timezone=True))


class EvaluacionParticipante(SQLModel, table=True):
    __tablename__ = "evaluacion_participante"
    __table_args__ = (
        sa.UniqueConstraint("evaluacion_id", "usuario_id"),
        sa.CheckConstraint(_in("rol_participacion", Rol), name="ck_part_rol"),
    )

    id: int | None = Field(default=None, primary_key=True)
    evaluacion_id: int = _fk("evaluacion.id")
    usuario_id: int = _fk("usuario.id")
    rol_participacion: str = Field(default=Rol.EVALUADOR.value, max_length=20)


class EvaluacionFactor(SQLModel, table=True):
    __tablename__ = "evaluacion_factor"
    __table_args__ = (
        sa.UniqueConstraint("evaluacion_id", "factor_id"),
        sa.CheckConstraint(_range("id_decisor"), name="ck_ef_id"),
        sa.CheckConstraint(_range("is_aplicado"), name="ck_ef_is"),
        sa.CheckConstraint(_range("ir_calculado"), name="ck_ef_ir"),
        sa.CheckConstraint(_in("alcance_aplicado", AlcanceAplicado), name="ck_ef_alcance"),
        sa.CheckConstraint(
            f"clasificacion_foda IS NULL OR {_in('clasificacion_foda', Foda)}", name="ck_ef_foda"
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    evaluacion_id: int = _fk("evaluacion.id")
    factor_id: int = _fk("factor.id")
    id_decisor: int = 1
    is_aplicado: int
    ir_calculado: int
    alcance_aplicado: str = Field(max_length=10)
    es_relevante: bool = False
    pm_calculado: float | None = None
    clasificacion_foda: str | None = Field(default=None, max_length=15)


class EvaluacionSubfactor(SQLModel, table=True):
    __tablename__ = "evaluacion_subfactor"
    __table_args__ = (
        sa.UniqueConstraint("evaluacion_factor_id", "subfactor_id"),
        sa.CheckConstraint(_range("score_ia", nullable=True), name="ck_es_score_ia"),
        sa.CheckConstraint(_range("score_evaluador", nullable=True), name="ck_es_score_ev"),
        sa.CheckConstraint(
            "nivel_confianza IS NULL OR nivel_confianza BETWEEN 0 AND 1", name="ck_es_conf"
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    evaluacion_factor_id: int = _fk("evaluacion_factor.id")
    subfactor_id: int = _fk("subfactor.id")
    score_ia: int | None = None
    nivel_confianza: float | None = None
    justificacion_ia: str | None = Field(default=None, sa_type=sa.Text)
    # Nulo hasta que el evaluador (o la precarga IA) asigna un valor.
    score_evaluador: int | None = None
    observacion_evaluador: str | None = Field(default=None, sa_type=sa.Text)
    validado_por_humano: bool = False
    revision_prioritaria: bool = False


# --- 12-14. RAG, evidencias y salida ---------------------------------------

class DocumentoChunk(SQLModel, table=True):
    __tablename__ = "documento_chunk"
    __table_args__ = (sa.CheckConstraint(_in("categoria", CategoriaChunk), name="ck_chunk_cat"),)

    id: int | None = Field(default=None, primary_key=True)
    evaluacion_id: int = _fk("evaluacion.id")
    ruta_archivo: str = Field(max_length=1000)
    ubicacion: str | None = Field(default=None, max_length=100)
    categoria: str = Field(max_length=20)
    contenido_texto: str = Field(sa_type=sa.Text)
    embedding: list[float] | None = Field(default=None, sa_type=EmbeddingType(EMBEDDING_DIM))


class EvidenciaTecnica(SQLModel, table=True):
    __tablename__ = "evidencia_tecnica"

    id: int | None = Field(default=None, primary_key=True)
    evaluacion_subfactor_id: int = _fk("evaluacion_subfactor.id")
    ruta_archivo: str = Field(max_length=1000)
    ubicacion_exacta: str = Field(max_length=200)
    fragmento_evidencia: str = Field(sa_type=sa.Text)


class RecomendacionEjecutiva(SQLModel, table=True):
    __tablename__ = "recomendacion_ejecutiva"
    __table_args__ = (sa.CheckConstraint(_in("dictamen_base", Dictamen), name="ck_rec_dictamen"),)

    id: int | None = Field(default=None, primary_key=True)
    evaluacion_id: int = _fk("evaluacion.id")
    dictamen_base: str = Field(max_length=1)
    resumen_ejecutivo: str = Field(sa_type=sa.Text)
    plan_accion_foda_json: list[dict] = Field(default_factory=list, sa_type=JSON)
    modelo_utilizado: str = Field(max_length=100)
    creado_en: datetime = Field(default_factory=_now, sa_type=sa.DateTime(timezone=True))


ALL_TABLES = [
    Usuario, CalibracionLiteratura, ArticuloLiteratura, FactorCalibracion, Dimension, Factor,
    Subfactor, Evaluacion, EvaluacionParticipante, EvaluacionFactor, EvaluacionSubfactor,
    DocumentoChunk, EvidenciaTecnica, RecomendacionEjecutiva,
]  # fmt: skip
