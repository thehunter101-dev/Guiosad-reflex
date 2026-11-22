"""Acceso a datos. El ``state/`` y los servicios no construyen consultas directamente."""

import math
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlmodel import Session, col, select

from ..core.catalog import DIMENSION_CODES, Catalog
from ..core.constants import (
    Alcance,
    AlcanceAplicado,
    EstadoEvaluacion,
    ModoEvaluacion,
    Rol,
)
from ..core.evaluator import evaluate, relative_importance
from ..core.schemas import (
    CalibracionResultado,
    EvaluacionInput,
    FactorInput,
    ResultadoEvaluacion,
    SubfactorPropuesta,
    VerdictResponse,
)
from .database import (
    ArticuloLiteratura,
    CalibracionLiteratura,
    Dimension,
    DocumentoChunk,
    Evaluacion,
    EvaluacionFactor,
    EvaluacionParticipante,
    EvaluacionSubfactor,
    EvidenciaTecnica,
    Factor,
    FactorCalibracion,
    RecomendacionEjecutiva,
    Subfactor,
    Usuario,
)


def _now() -> datetime:
    return datetime.now(UTC)


# =============================================================================
# Catálogo
# =============================================================================

def seed_catalog(session: Session, catalog: Catalog) -> int:
    """Inserta el catálogo base si la tabla ``factor`` está vacía. Devuelve factores creados."""
    if session.exec(select(Factor.id).limit(1)).first() is not None:
        return 0
    dims: dict[str, Dimension] = {}
    for name in catalog.dimensions:
        d = Dimension(codigo=DIMENSION_CODES.get(name, name[:3].upper()), nombre=name)
        session.add(d)
        dims[name] = d
    session.flush()
    for i, f in enumerate(catalog.factors):
        factor = Factor(
            dimension_id=dims[f.dimension].id,
            codigo=f.codigo,
            nombre=f.name,
            tipo_alcance=f.scope.value,
            cadena_busqueda=f.cadena_busqueda,
            is_vigente=f.suggested_importance,
            orden=i,
        )
        session.add(factor)
        session.flush()
        for j, s in enumerate(f.subfactors):
            session.add(
                Subfactor(
                    factor_id=factor.id,
                    codigo=s.codigo,
                    afirmacion=s.afirmacion,
                    guia_verificacion=s.guia_verificacion,
                    orden=j,
                )
            )
    session.flush()
    return len(catalog.factors)


def list_dimensions(session: Session, only_active: bool = False) -> Sequence[Dimension]:
    q = select(Dimension).order_by(Dimension.id)
    if only_active:
        q = q.where(Dimension.activa == True)  # noqa: E712
    return session.exec(q).all()


def list_factors(session: Session, only_active: bool = False) -> Sequence[Factor]:
    q = select(Factor).join(Dimension).order_by(Dimension.id, Factor.orden, Factor.id)
    if only_active:
        q = q.where(Factor.activo == True, Dimension.activa == True)  # noqa: E712
    return session.exec(q).all()


def list_subfactors(
    session: Session, factor_id: int | None = None, only_active: bool = False
) -> Sequence[Subfactor]:
    q = select(Subfactor).order_by(Subfactor.factor_id, Subfactor.orden, Subfactor.id)
    if factor_id is not None:
        q = q.where(Subfactor.factor_id == factor_id)
    if only_active:
        q = q.where(Subfactor.subfactor_activo == True)  # noqa: E712
    return session.exec(q).all()


def active_subfactor_counts(session: Session) -> dict[int, int]:
    rows = session.exec(
        select(Subfactor.factor_id, sa.func.count(Subfactor.id))
        .where(Subfactor.subfactor_activo == True)  # noqa: E712
        .group_by(Subfactor.factor_id)
    ).all()
    return {fid: n for fid, n in rows}


def save_entity(session: Session, obj):
    session.add(obj)
    session.flush()
    session.refresh(obj)
    return obj


def delete_entity(session: Session, model, entity_id: int) -> None:
    obj = session.get(model, entity_id)
    if obj is not None:
        session.delete(obj)
        session.flush()


# =============================================================================
# Usuarios
# =============================================================================

def get_user_by_email(session: Session, email: str) -> Usuario | None:
    return session.exec(select(Usuario).where(Usuario.email == email.strip().lower())).first()


def create_user(
    session: Session,
    nombre: str,
    email: str,
    password_hash: str,
    organizacion: str | None = None,
    rol: Rol | None = None,
) -> Usuario:
    """Crea un usuario. El primer usuario registrado es administrador."""
    if rol is None:
        first = session.exec(select(Usuario.id).limit(1)).first() is None
        rol = Rol.ADMIN if first else Rol.DECISOR
    user = Usuario(
        nombre_completo=nombre.strip(),
        email=email.strip().lower(),
        password_hash=password_hash,
        organizacion=(organizacion or "").strip() or None,
        rol=rol.value,
    )
    return save_entity(session, user)


def list_users(session: Session) -> Sequence[Usuario]:
    return session.exec(select(Usuario).order_by(Usuario.id)).all()


# =============================================================================
# Evaluaciones
# =============================================================================

def _default_alcance(tipo: str) -> str:
    return AlcanceAplicado.INTERNO.value if tipo == Alcance.CONFIGURABLE else tipo


def vigente_calibration(session: Session) -> CalibracionLiteratura | None:
    return session.exec(
        select(CalibracionLiteratura).where(CalibracionLiteratura.es_vigente == True)  # noqa: E712
    ).first()


def create_evaluacion(
    session: Session,
    owner_id: int,
    nombre_software: str,
    version: str | None = None,
    url_repositorio: str | None = None,
    organizacion: str | None = None,
) -> Evaluacion:
    cal = vigente_calibration(session)
    ev = save_entity(
        session,
        Evaluacion(
            usuario_propietario_id=owner_id,
            calibracion_id=cal.id if cal else None,
            nombre_software=nombre_software.strip(),
            version=(version or "").strip() or None,
            url_repositorio=(url_repositorio or "").strip() or None,
            organizacion=(organizacion or "").strip() or None,
        ),
    )
    for f in list_factors(session, only_active=True):
        ef = EvaluacionFactor(
            evaluacion_id=ev.id,
            factor_id=f.id,
            id_decisor=1,
            is_aplicado=f.is_vigente,
            ir_calculado=relative_importance(1, f.is_vigente),
            alcance_aplicado=_default_alcance(f.tipo_alcance),
        )
        session.add(ef)
        session.flush()
        for s in list_subfactors(session, f.id, only_active=True):
            session.add(EvaluacionSubfactor(evaluacion_factor_id=ef.id, subfactor_id=s.id))
    session.flush()
    recompute(session, ev.id)
    return ev


def get_evaluacion(session: Session, evaluacion_id: int) -> Evaluacion | None:
    return session.get(Evaluacion, evaluacion_id)


def participant_role(session: Session, evaluacion_id: int, user: Usuario) -> str | None:
    """Rol efectivo del usuario en la evaluación, o ``None`` si no tiene acceso."""
    ev = session.get(Evaluacion, evaluacion_id)
    if ev is None:
        return None
    if user.rol == Rol.ADMIN or ev.usuario_propietario_id == user.id:
        return Rol.DECISOR.value
    p = session.exec(
        select(EvaluacionParticipante).where(
            EvaluacionParticipante.evaluacion_id == evaluacion_id,
            EvaluacionParticipante.usuario_id == user.id,
        )
    ).first()
    return p.rol_participacion if p else None


def list_evaluaciones_for_user(session: Session, user: Usuario) -> Sequence[Evaluacion]:
    q = select(Evaluacion).order_by(col(Evaluacion.actualizado_en).desc())
    if user.rol != Rol.ADMIN:
        shared = select(EvaluacionParticipante.evaluacion_id).where(
            EvaluacionParticipante.usuario_id == user.id
        )
        q = q.where(
            sa.or_(Evaluacion.usuario_propietario_id == user.id, col(Evaluacion.id).in_(shared))
        )
    return session.exec(q).all()


def add_participant(session: Session, evaluacion_id: int, email: str, rol: Rol) -> Usuario:
    user = get_user_by_email(session, email)
    if user is None:
        raise ValueError(f"No existe un usuario con el correo {email}.")
    existing = session.exec(
        select(EvaluacionParticipante).where(
            EvaluacionParticipante.evaluacion_id == evaluacion_id,
            EvaluacionParticipante.usuario_id == user.id,
        )
    ).first()
    if existing:
        existing.rol_participacion = rol.value
        session.add(existing)
    else:
        session.add(
            EvaluacionParticipante(
                evaluacion_id=evaluacion_id, usuario_id=user.id, rol_participacion=rol.value
            )
        )
    session.flush()
    return user


def list_participants(session: Session, evaluacion_id: int) -> list[tuple[Usuario, str]]:
    rows = session.exec(
        select(Usuario, EvaluacionParticipante.rol_participacion)
        .join(EvaluacionParticipante, EvaluacionParticipante.usuario_id == Usuario.id)
        .where(EvaluacionParticipante.evaluacion_id == evaluacion_id)
    ).all()
    return [(u, r) for u, r in rows]


def evaluation_factors(
    session: Session, evaluacion_id: int
) -> list[tuple[EvaluacionFactor, Factor, Dimension]]:
    rows = session.exec(
        select(EvaluacionFactor, Factor, Dimension)
        .join(Factor, Factor.id == EvaluacionFactor.factor_id)
        .join(Dimension, Dimension.id == Factor.dimension_id)
        .where(EvaluacionFactor.evaluacion_id == evaluacion_id)
        .order_by(Dimension.id, Factor.orden, Factor.id)
    ).all()
    return [tuple(r) for r in rows]


def evaluation_subfactors(
    session: Session, evaluacion_id: int
) -> list[tuple[EvaluacionSubfactor, Subfactor, EvaluacionFactor]]:
    rows = session.exec(
        select(EvaluacionSubfactor, Subfactor, EvaluacionFactor)
        .join(Subfactor, Subfactor.id == EvaluacionSubfactor.subfactor_id)
        .join(EvaluacionFactor, EvaluacionFactor.id == EvaluacionSubfactor.evaluacion_factor_id)
        .where(EvaluacionFactor.evaluacion_id == evaluacion_id)
        .order_by(Subfactor.factor_id, Subfactor.orden, Subfactor.id)
    ).all()
    return [tuple(r) for r in rows]


def evidences_by_subfactor(
    session: Session, evaluacion_id: int
) -> dict[int, list[EvidenciaTecnica]]:
    rows = session.exec(
        select(EvidenciaTecnica)
        .join(EvaluacionSubfactor, EvaluacionSubfactor.id == EvidenciaTecnica.evaluacion_subfactor_id)
        .join(EvaluacionFactor, EvaluacionFactor.id == EvaluacionSubfactor.evaluacion_factor_id)
        .where(EvaluacionFactor.evaluacion_id == evaluacion_id)
        .order_by(EvidenciaTecnica.id)
    ).all()
    out: dict[int, list[EvidenciaTecnica]] = {}
    for e in rows:
        out.setdefault(e.evaluacion_subfactor_id, []).append(e)
    return out


def _touch(session: Session, evaluacion_id: int, **changes) -> None:
    ev = session.get(Evaluacion, evaluacion_id)
    if ev is None:
        return
    for k, v in changes.items():
        setattr(ev, k, v)
    ev.actualizado_en = _now()
    session.add(ev)


def set_decisor_importance(session: Session, ef_id: int, value: int) -> None:
    ef = session.get(EvaluacionFactor, ef_id)
    if ef is None:
        raise ValueError("Factor de evaluación inexistente.")
    ef.id_decisor = value
    session.add(ef)
    session.flush()
    recompute(session, ef.evaluacion_id)


def set_alcance(session: Session, ef_id: int, alcance: AlcanceAplicado) -> None:
    ef = session.get(EvaluacionFactor, ef_id)
    if ef is None:
        raise ValueError("Factor de evaluación inexistente.")
    factor = session.get(Factor, ef.factor_id)
    if factor is None or factor.tipo_alcance != Alcance.CONFIGURABLE:
        raise ValueError("El alcance de este factor no es configurable.")
    ef.alcance_aplicado = alcance.value
    session.add(ef)
    session.flush()
    recompute(session, ef.evaluacion_id)


def set_subfactor_score(session: Session, es_id: int, score: int | None) -> int:
    es = session.get(EvaluacionSubfactor, es_id)
    if es is None:
        raise ValueError("Subfactor de evaluación inexistente.")
    es.score_evaluador = score
    es.validado_por_humano = score is not None
    session.add(es)
    session.flush()
    ef = session.get(EvaluacionFactor, es.evaluacion_factor_id)
    recompute(session, ef.evaluacion_id)
    return ef.evaluacion_id


def set_subfactor_observation(session: Session, es_id: int, text: str) -> None:
    es = session.get(EvaluacionSubfactor, es_id)
    if es is None:
        raise ValueError("Subfactor de evaluación inexistente.")
    es.observacion_evaluador = text.strip() or None
    session.add(es)
    session.flush()


def set_modo(session: Session, evaluacion_id: int, modo: ModoEvaluacion) -> None:
    _touch(session, evaluacion_id, modo=modo.value)
    session.flush()


def build_input(session: Session, evaluacion_id: int) -> EvaluacionInput:
    scores: dict[int, list[int | None]] = {}
    for es, _, ef in evaluation_subfactors(session, evaluacion_id):
        scores.setdefault(ef.id, []).append(es.score_evaluador)
    return EvaluacionInput(
        factores=[
            FactorInput(
                factor_id=ef.id,  # id de evaluacion_factor para mapear el resultado
                nombre=f.nombre,
                is_aplicado=ef.is_aplicado,
                id_decisor=ef.id_decisor,
                alcance=AlcanceAplicado(ef.alcance_aplicado),
                scores=scores.get(ef.id, []),
            )
            for ef, f, _ in evaluation_factors(session, evaluacion_id)
        ]
    )


def recompute(session: Session, evaluacion_id: int) -> ResultadoEvaluacion:
    """Ejecuta ``core.evaluator`` y persiste IR, relevancia, PM, FODA, dictamen y estado."""
    result = evaluate(build_input(session, evaluacion_id))
    by_ef = {r.factor_id: r for r in result.factores}
    for ef, _, _ in evaluation_factors(session, evaluacion_id):
        r = by_ef[ef.id]
        ef.ir_calculado = r.ir
        ef.es_relevante = r.es_relevante
        ef.pm_calculado = r.pm
        ef.clasificacion_foda = r.foda.value if r.foda else None
        session.add(ef)

    ev = session.get(Evaluacion, evaluacion_id)
    if ev.estado != EstadoEvaluacion.FINALIZADA:
        answered = any(
            es.score_evaluador is not None for es, _, _ in evaluation_subfactors(session, evaluacion_id)
        )
        if result.dictamen is not None:
            estado = EstadoEvaluacion.REVISION
        elif answered:
            estado = EstadoEvaluacion.PASO_3
        elif any(ef.id_decisor != 1 for ef, _, _ in evaluation_factors(session, evaluacion_id)):
            estado = EstadoEvaluacion.PASO_2
        else:
            estado = EstadoEvaluacion.PASO_1
        ev.estado = estado.value
    ev.dictamen_base = result.dictamen.value if result.dictamen else None
    ev.actualizado_en = _now()
    session.add(ev)
    session.flush()
    return result


def finalize(session: Session, evaluacion_id: int) -> None:
    result = recompute(session, evaluacion_id)
    if result.dictamen is None:
        raise ValueError("Faltan factores relevantes por evaluar.")
    _touch(session, evaluacion_id, estado=EstadoEvaluacion.FINALIZADA.value)
    session.flush()


def reopen(session: Session, evaluacion_id: int) -> None:
    _touch(session, evaluacion_id, estado=EstadoEvaluacion.REVISION.value)
    session.flush()
    recompute(session, evaluacion_id)


def delete_evaluacion(session: Session, evaluacion_id: int) -> None:
    delete_entity(session, Evaluacion, evaluacion_id)


# =============================================================================
# RAG: chunks y búsqueda vectorial
# =============================================================================

def replace_chunks(session: Session, evaluacion_id: int, chunks: Iterable[DocumentoChunk]) -> int:
    session.exec(sa.delete(DocumentoChunk).where(DocumentoChunk.evaluacion_id == evaluacion_id))
    n = 0
    for c in chunks:
        c.evaluacion_id = evaluacion_id
        session.add(c)
        n += 1
    session.flush()
    return n


def count_chunks(session: Session, evaluacion_id: int) -> int:
    return session.exec(
        select(sa.func.count(DocumentoChunk.id)).where(DocumentoChunk.evaluacion_id == evaluacion_id)
    ).one()


# Orden de embedding: lo más informativo primero (si se corta la cuota, queda lo útil).
_CATEGORY_PRIORITY = sa.case(
    {"licencia": 0, "configuracion": 1, "documentacion": 2, "codigo": 3},
    value=DocumentoChunk.categoria,
    else_=4,
)


def embedding_stats(session: Session, evaluacion_id: int) -> tuple[int, int]:
    """(fragmentos con embedding, total de fragmentos)."""
    total, embedded = session.exec(
        select(sa.func.count(DocumentoChunk.id), sa.func.count(DocumentoChunk.embedding)).where(
            DocumentoChunk.evaluacion_id == evaluacion_id
        )
    ).one()
    return embedded, total


def pending_embedding_chunks(session: Session, evaluacion_id: int, limit: int) -> list[DocumentoChunk]:
    return list(
        session.exec(
            select(DocumentoChunk)
            .where(DocumentoChunk.evaluacion_id == evaluacion_id, col(DocumentoChunk.embedding).is_(None))
            .order_by(_CATEGORY_PRIORITY, DocumentoChunk.id)
            .limit(limit)
        ).all()
    )


def set_chunk_embeddings(session: Session, vectors: dict[int, list[float]]) -> None:
    for chunk_id, vector in vectors.items():
        chunk = session.get(DocumentoChunk, chunk_id)
        if chunk is not None:
            chunk.embedding = vector
            session.add(chunk)
    session.flush()


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return 1.0 - dot / (na * nb)


def search_chunks(
    session: Session, evaluacion_id: int, embedding: Sequence[float], k: int
) -> list[DocumentoChunk]:
    """Top-k por distancia coseno (pgvector en PostgreSQL; en memoria en otros motores)."""
    base = select(DocumentoChunk).where(
        DocumentoChunk.evaluacion_id == evaluacion_id, col(DocumentoChunk.embedding).is_not(None)
    )
    if session.get_bind().dialect.name == "postgresql":
        from pgvector.sqlalchemy import Vector

        vec = sa.cast(list(embedding), Vector(len(embedding)))
        distance = sa.cast(DocumentoChunk.embedding, Vector(len(embedding))).cosine_distance(vec)
        return list(session.exec(base.order_by(distance).limit(k)).all())
    rows = session.exec(base).all()
    return sorted(rows, key=lambda c: _cosine(c.embedding, embedding))[:k]


def chunks_by_category(session: Session, evaluacion_id: int, categoria: str) -> list[DocumentoChunk]:
    return list(
        session.exec(
            select(DocumentoChunk).where(
                DocumentoChunk.evaluacion_id == evaluacion_id, DocumentoChunk.categoria == categoria
            )
        ).all()
    )


# =============================================================================
# Pre-evaluación IA y dictamen
# =============================================================================

def save_ai_proposal(session: Session, es_id: int, p: SubfactorPropuesta) -> None:
    es = session.get(EvaluacionSubfactor, es_id)
    if es is None:
        return
    es.score_ia = p.score_ia
    es.nivel_confianza = p.nivel_confianza
    es.justificacion_ia = p.justificacion
    es.revision_prioritaria = p.requiere_revision
    if not es.validado_por_humano:
        es.score_evaluador = p.score_ia  # Precarga editable por el evaluador.
    session.add(es)
    session.exec(sa.delete(EvidenciaTecnica).where(EvidenciaTecnica.evaluacion_subfactor_id == es_id))
    for c in p.citas:
        session.add(
            EvidenciaTecnica(
                evaluacion_subfactor_id=es_id,
                ruta_archivo=c.archivo[:1000],
                ubicacion_exacta=c.ubicacion[:200],
                fragmento_evidencia=c.fragmento,
            )
        )
    session.flush()


def save_recomendacion(
    session: Session, evaluacion_id: int, verdict: VerdictResponse, modelo: str
) -> RecomendacionEjecutiva:
    return save_entity(
        session,
        RecomendacionEjecutiva(
            evaluacion_id=evaluacion_id,
            dictamen_base=verdict.dictamen_base.value,
            resumen_ejecutivo=verdict.resumen_ejecutivo,
            plan_accion_foda_json=[i.model_dump() for i in verdict.plan_accion],
            modelo_utilizado=modelo,
        ),
    )


def latest_recomendacion(session: Session, evaluacion_id: int) -> RecomendacionEjecutiva | None:
    return session.exec(
        select(RecomendacionEjecutiva)
        .where(RecomendacionEjecutiva.evaluacion_id == evaluacion_id)
        .order_by(col(RecomendacionEjecutiva.id).desc())
    ).first()


# =============================================================================
# Calibración bibliográfica
# =============================================================================

def create_calibracion(
    session: Session, usuario_id: int | None, anio_inicio: int, anio_fin: int
) -> CalibracionLiteratura:
    return save_entity(
        session,
        CalibracionLiteratura(usuario_id=usuario_id, anio_inicio=anio_inicio, anio_fin=anio_fin),
    )


def save_articulos(session: Session, articulos: Iterable[ArticuloLiteratura]) -> None:
    for a in articulos:
        session.add(a)
    session.flush()


def apply_calibration(
    session: Session, calibracion_id: int, result: CalibracionResultado, observaciones: str = ""
) -> None:
    """Persiste ``factor_calibracion``, marca la calibración vigente y actualiza IS."""
    for fr in result.factores:
        session.add(
            FactorCalibracion(
                calibracion_id=calibracion_id,
                factor_id=fr.factor_id,
                citas_pertinentes=fr.citas_pertinentes,
                subfactores_activos=fr.subfactores_activos,
                ratio_normalizado=fr.ratio_normalizado,
                il_calculado=fr.il_calculado,
                ie_fijo=fr.ie_fijo,
                is_calculado=fr.is_calculado,
            )
        )
        factor = session.get(Factor, fr.factor_id)
        if factor:
            factor.is_vigente = fr.is_calculado
            session.add(factor)
    session.exec(sa.update(CalibracionLiteratura).values(es_vigente=False))
    cal = session.get(CalibracionLiteratura, calibracion_id)
    cal.es_vigente = True
    cal.observaciones = (
        f"Q1={result.q1:.3f}; Q2={result.q2:.3f}; Q3={result.q3:.3f}. {observaciones}".strip()
    )
    session.add(cal)
    session.flush()


def list_calibraciones(session: Session) -> Sequence[CalibracionLiteratura]:
    return session.exec(
        select(CalibracionLiteratura).order_by(col(CalibracionLiteratura.id).desc())
    ).all()


def calibration_rows(session: Session, calibracion_id: int) -> list[tuple[FactorCalibracion, Factor]]:
    rows = session.exec(
        select(FactorCalibracion, Factor)
        .join(Factor, Factor.id == FactorCalibracion.factor_id)
        .where(FactorCalibracion.calibracion_id == calibracion_id)
        .order_by(Factor.dimension_id, Factor.orden)
    ).all()
    return [tuple(r) for r in rows]


def articles_for(session: Session, calibracion_id: int, factor_id: int) -> Sequence[ArticuloLiteratura]:
    return session.exec(
        select(ArticuloLiteratura)
        .where(
            ArticuloLiteratura.calibracion_id == calibracion_id,
            ArticuloLiteratura.factor_id == factor_id,
        )
        .order_by(col(ArticuloLiteratura.es_pertinente).desc(), ArticuloLiteratura.id)
    ).all()
