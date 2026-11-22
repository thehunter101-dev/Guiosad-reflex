"""Wizard de 6 pasos con persistencia, pre-evaluación IA y Human-in-the-Loop.

Si no hay artefactos o la IA falla, la evaluación sigue en modo ``manual`` sin
interrumpir el flujo (RF-AUTO-10).
"""

import asyncio
import dataclasses
import shutil
import tempfile
from pathlib import Path

import reflex as rx

from ..core.constants import (
    COMPLIANCE_LEVELS,
    DICTAMEN_CODIGO,
    DICTAMEN_TEXTO,
    IMPORTANCE_LEVELS,
    UMBRAL_CONFIANZA_IA,
    AlcanceAplicado,
    Alcance,
    Dictamen,
    EstadoEvaluacion,
    Foda,
    ModoEvaluacion,
    Rol,
    compliance_label,
    importance_label,
)
from ..core.schemas import CitationItem, EvidenciaValidada, VerdictRequest
from ..models import repository as repo
from ..models.database import Usuario
from ..models.session import session_scope
from ..services.ai_client import AIUnavailable, get_ai_client
from ..services.repo_ingestor import (
    STATIC_REPORT_PATH,
    IngestError,
    IngestSource,
    embed_pending_chunks,
    ingest,
)
from ..services.subfactor_ai import PrefillStats, prefill
from ..services.verdict_ai import MANUAL_MODEL, generate_verdict, manual_verdict
from ..settings import get_settings
from .auth_state import AuthState
from .dashboard_state import ESTADO_LABEL
from .models import (
    EvidenceRow,
    FactorRow,
    FodaCount,
    ParticipantRow,
    PlanRow,
    SubfactorCard,
    SummaryRow,
)
from .tasks import run_with_progress

def _stats_lines(stats: PrefillStats | None) -> list[str]:
    if stats is None:
        return []
    return [
        f"Pre-evaluación completada: {stats.evaluados} subfactores, {stats.con_evidencia} con evidencia, "
        f"{stats.revision_prioritaria} para revisión prioritaria.",
        f"Contexto RAG: {stats.fragmentos_con_embedding} fragmentos del repositorio/documentos.",
    ]


FILTERS = ["Todos", "Pendientes / Desconozco (2)", "Baja confianza IA"]
UPLOAD_ID = "artefactos"


class EvaluationState(AuthState):
    eval_id: int = 0
    not_found: bool = False
    nombre_software: str = ""
    version: str = ""
    organizacion: str = ""
    url_repositorio: str = ""
    modo: str = ModoEvaluacion.MANUAL.value
    estado: str = ""
    my_role: str = ""

    factors: list[FactorRow] = []
    subfactors: list[SubfactorCard] = []
    summary: list[SummaryRow] = []
    foda_counts: list[FodaCount] = []
    relevantes: int = 0
    pendientes: int = 0
    dictamen: str = ""
    dictamen_provisional: str = ""

    filtro: str = FILTERS[0]

    # Contexto / IA
    repo_url_input: str = ""
    pending_uploads: list[str] = []
    busy: bool = False
    task_log: list[str] = []
    static_report: list[str] = []
    chunk_count: int = 0
    embedded_count: int = 0
    ai_notice: str = ""

    # Dictamen ejecutivo
    resumen_ejecutivo: str = ""
    plan_accion: list[PlanRow] = []
    modelo_utilizado: str = ""
    fecha_recomendacion: str = ""

    # Equipo
    participants: list[ParticipantRow] = []

    _upload_paths: dict[str, str] = {}

    # --- Permisos -----------------------------------------------------------

    @rx.var
    def is_final(self) -> bool:
        return self.estado == EstadoEvaluacion.FINALIZADA.value

    @rx.var
    def can_edit_decisor(self) -> bool:
        return self.my_role == Rol.DECISOR.value and self.estado != EstadoEvaluacion.FINALIZADA.value

    @rx.var
    def can_edit_scores(self) -> bool:
        return self.my_role in (Rol.DECISOR.value, Rol.EVALUADOR.value) and (
            self.estado != EstadoEvaluacion.FINALIZADA.value
        )

    @rx.var
    def estado_label(self) -> str:
        return ESTADO_LABEL.get(self.estado, self.estado)

    @rx.var
    def modo_label(self) -> str:
        return "Híbrido IA" if self.modo == ModoEvaluacion.HIBRIDO_IA.value else "Manual"

    @rx.var
    def ai_configured(self) -> bool:
        return get_settings().ai_enabled

    # --- Derivados de pasos 3-4 ---------------------------------------------

    @rx.var
    def scored_count(self) -> int:
        return sum(1 for s in self.subfactors if s.score_label)

    @rx.var
    def total_count(self) -> int:
        return len(self.subfactors)

    @rx.var
    def progress_pct(self) -> int:
        total = len(self.subfactors)
        return round(100 * sum(1 for s in self.subfactors if s.score_label) / total) if total else 0

    @rx.var
    def visible_subfactors(self) -> list[SubfactorCard]:
        if self.filtro == FILTERS[1]:
            items = [s for s in self.subfactors if not s.score_label or s.score_label == COMPLIANCE_LEVELS[1]]
        elif self.filtro == FILTERS[2]:
            items = [s for s in self.subfactors if s.baja_confianza]
        else:
            items = list(self.subfactors)
        out, last = [], None
        for s in items:
            show = s.factor != last
            last = s.factor
            out.append(dataclasses.replace(s, show_header=show))
        return out

    @rx.var
    def dictamen_codigo(self) -> str:
        return DICTAMEN_CODIGO[Dictamen(self.dictamen)] if self.dictamen else ""

    @rx.var
    def dictamen_texto(self) -> str:
        return DICTAMEN_TEXTO[Dictamen(self.dictamen)] if self.dictamen else ""

    # --- Carga --------------------------------------------------------------

    @rx.event
    def load(self):
        if not self.user_id:
            return
        raw = self.router.url.query_parameters.get("id", "")
        self.not_found = False
        self.task_log, self.ai_notice = [], ""
        self.resumen_ejecutivo, self.plan_accion = "", []
        self.filtro = FILTERS[0]
        if not raw.isdigit():
            self.not_found = True
            return
        self.eval_id = int(raw)
        with session_scope() as session:
            user = session.get(Usuario, self.user_id)
            role = repo.participant_role(session, self.eval_id, user)
            if role is None:
                self.not_found = True
                return
            self.my_role = role
            self._reload(session)
            ev = repo.get_evaluacion(session, self.eval_id)
            self.repo_url_input = ev.url_repositorio or ""

    def _reload(self, session) -> None:
        ev = repo.get_evaluacion(session, self.eval_id)
        self.nombre_software = ev.nombre_software
        self.version = ev.version or ""
        self.organizacion = ev.organizacion or ""
        self.url_repositorio = ev.url_repositorio or ""
        self.modo = ev.modo
        self.estado = ev.estado

        result = repo.recompute(session, self.eval_id)
        by_ef = {r.factor_id: r for r in result.factores}
        factor_rows = repo.evaluation_factors(session, self.eval_id)
        names = {ef.id: (f.nombre, d.nombre) for ef, f, d in factor_rows}

        self.factors = [
            FactorRow(
                ef_id=ef.id,
                nombre=f.nombre,
                dimension=d.nombre,
                is_label=importance_label(ef.is_aplicado),
                decisor_label=importance_label(ef.id_decisor),
                ir_label=importance_label(by_ef[ef.id].ir),
                relevante=by_ef[ef.id].es_relevante,
                alcance=ef.alcance_aplicado,
                alcance_editable=f.tipo_alcance == Alcance.CONFIGURABLE,
            )
            for ef, f, d in factor_rows
        ]

        evidences = repo.evidences_by_subfactor(session, self.eval_id)
        cards = []
        for es, sub, ef in repo.evaluation_subfactors(session, self.eval_id):
            r = by_ef[ef.id]
            if not r.es_relevante:
                continue
            fname, dname = names[ef.id]
            conf = es.nivel_confianza
            cards.append(
                SubfactorCard(
                    es_id=es.id,
                    codigo=sub.codigo,
                    factor=fname,
                    dimension=dname,
                    factor_pm=f"{r.pm:.2f}" if r.pm is not None else "—",
                    afirmacion=sub.afirmacion,
                    guia=sub.guia_verificacion or "",
                    score_label=compliance_label(es.score_evaluador) if es.score_evaluador else "",
                    score_ia=es.score_ia or 0,
                    score_ia_label=compliance_label(es.score_ia) if es.score_ia else "",
                    confianza_pct=f"{conf * 100:.0f}%" if conf is not None else "",
                    baja_confianza=es.score_ia is not None and (conf or 0) < UMBRAL_CONFIANZA_IA,
                    justificacion=es.justificacion_ia or "",
                    observacion=es.observacion_evaluador or "",
                    validado=es.validado_por_humano,
                    revision_prioritaria=es.revision_prioritaria,
                    evidencias=[
                        EvidenceRow(archivo=e.ruta_archivo, ubicacion=e.ubicacion_exacta, fragmento=e.fragmento_evidencia)
                        for e in evidences.get(es.id, [])
                    ],
                )
            )
        self.subfactors = cards

        self.summary = []
        for ef, f, d in factor_rows:
            r = by_ef[ef.id]
            status = "irrelevant" if not r.es_relevante else "pending" if r.pendiente else "evaluated"
            self.summary.append(
                SummaryRow(
                    nombre=f.nombre,
                    dimension=d.nombre,
                    ir_label=importance_label(r.ir),
                    status=status,
                    pm=f"{r.pm:.2f}" if r.pm is not None else "",
                    alcance=r.alcance.value,
                    foda=r.foda.value if r.foda and r.foda != Foda.EXCLUIDO else "",
                )
            )
        self.foda_counts = [
            FodaCount(foda=k.value, count=v) for k, v in result.conteo_foda.items() if k != Foda.EXCLUIDO
        ]
        self.relevantes = result.relevantes
        self.pendientes = result.pendientes
        self.dictamen = result.dictamen.value if result.dictamen else ""
        self.dictamen_provisional = result.dictamen_provisional.value if result.dictamen_provisional else ""
        self.embedded_count, self.chunk_count = repo.embedding_stats(session, self.eval_id)
        static = [c for c in repo.chunks_by_category(session, self.eval_id, "configuracion")
                  if c.ruta_archivo == STATIC_REPORT_PATH]
        self.static_report = static[0].contenido_texto.splitlines()[1:] if static else []

        rec = repo.latest_recomendacion(session, self.eval_id)
        if rec and rec.dictamen_base == self.dictamen:
            self.resumen_ejecutivo = rec.resumen_ejecutivo
            self.modelo_utilizado = rec.modelo_utilizado
            self.fecha_recomendacion = rec.creado_en.strftime("%Y-%m-%d %H:%M")
            self.plan_accion = [
                PlanRow(factor=p.get("factor_nombre", ""), tipo_foda=p.get("tipo_foda", ""),
                        accion=p.get("accion", ""), prioridad=p.get("prioridad", ""))
                for p in rec.plan_accion_foda_json
            ]
        else:
            self.resumen_ejecutivo, self.plan_accion, self.modelo_utilizado = "", [], ""

        self.participants = [
            ParticipantRow(nombre=u.nombre_completo, email=u.email, rol=rol)
            for u, rol in repo.list_participants(session, self.eval_id)
        ]

    def _refresh(self) -> None:
        with session_scope() as session:
            self._reload(session)

    # --- Pasos 1 y 2 --------------------------------------------------------

    @rx.event
    def set_decisor(self, ef_id: int, label: str):
        if not self.can_edit_decisor:
            return rx.toast.error("No puede modificar la importancia en esta evaluación.")
        with session_scope() as session:
            repo.set_decisor_importance(session, ef_id, IMPORTANCE_LEVELS.index(label) + 1)
            self._reload(session)

    @rx.event
    def set_alcance(self, ef_id: int, value: str):
        if not self.can_edit_decisor:
            return
        with session_scope() as session:
            repo.set_alcance(session, ef_id, AlcanceAplicado(value))
            self._reload(session)

    # --- Pasos 3 y 4 (guardado reactivo) ------------------------------------

    @rx.event
    def set_filtro(self, value: str | list[str]):
        self.filtro = value if isinstance(value, str) else (value[0] if value else FILTERS[0])

    @rx.event
    def set_score(self, es_id: int, label: str):
        if not self.can_edit_scores:
            return rx.toast.error("Esta evaluación es de solo lectura.")
        score = COMPLIANCE_LEVELS.index(label) + 1 if label in COMPLIANCE_LEVELS else None
        with session_scope() as session:
            repo.set_subfactor_score(session, es_id, score)
            self._reload(session)

    @rx.event
    def set_observation(self, es_id: int, text: str):
        if not self.can_edit_scores:
            return
        with session_scope() as session:
            repo.set_subfactor_observation(session, es_id, text)
        for s in self.subfactors:
            if s.es_id == es_id:
                s.observacion = text.strip()

    @rx.event
    def accept_all_ai(self):
        """Valida en bloque las propuestas IA con evidencia (no toca las ya revisadas)."""
        if not self.can_edit_scores:
            return
        with session_scope() as session:
            for es, _, ef in repo.evaluation_subfactors(session, self.eval_id):
                if ef.es_relevante and es.score_ia and not es.validado_por_humano and not es.revision_prioritaria:
                    repo.set_subfactor_score(session, es.id, es.score_ia)
            self._reload(session)
        return rx.toast.success("Propuestas con evidencia validadas.")

    # --- Pasos 5 y 6 --------------------------------------------------------

    @rx.event
    def finalize(self):
        if not self.can_edit_decisor:
            return
        try:
            with session_scope() as session:
                repo.finalize(session, self.eval_id)
                self._reload(session)
        except ValueError as exc:
            return rx.toast.error(str(exc))
        return rx.toast.success("Evaluación finalizada.")

    @rx.event
    def reopen(self):
        if self.my_role != Rol.DECISOR.value:
            return
        with session_scope() as session:
            repo.reopen(session, self.eval_id)
            self._reload(session)

    def _verdict_request(self, session) -> VerdictRequest:
        result = repo.recompute(session, self.eval_id)
        ev = repo.get_evaluacion(session, self.eval_id)
        evid = repo.evidences_by_subfactor(session, self.eval_id)
        evidencias = [
            EvidenciaValidada(
                factor_id=ef.id,
                afirmacion=sub.afirmacion,
                score_evaluador=es.score_evaluador,
                observacion=es.observacion_evaluador,
                citas=[CitationItem(archivo=e.ruta_archivo, ubicacion=e.ubicacion_exacta,
                                    fragmento=e.fragmento_evidencia[:500]) for e in evid.get(es.id, [])],
            )
            for es, sub, ef in repo.evaluation_subfactors(session, self.eval_id)
            if ef.es_relevante and es.score_evaluador and (es.validado_por_humano or es.observacion_evaluador)
            and (evid.get(es.id) or es.observacion_evaluador)
        ]
        return VerdictRequest(nombre_software=ev.nombre_software, version=ev.version,
                              organizacion=ev.organizacion, resultado=result, evidencias=evidencias)

    @rx.event(background=True)
    async def generate_executive_verdict(self):
        async with self:
            if self.busy or not self.dictamen or self.my_role != Rol.DECISOR.value:
                return
            self.busy = True
            self.task_log = ["Generando dictamen ejecutivo…"]
            eval_id = self.eval_id
        notice = ""
        try:
            with session_scope() as session:
                req = self._verdict_request(session)
            model = MANUAL_MODEL
            try:
                client = get_ai_client()
                verdict = await asyncio.to_thread(generate_verdict, req, client)
                model = get_settings().gemini_model_dictamen
            except AIUnavailable as exc:
                notice = f"IA no disponible ({exc}). Se generó el dictamen determinista."
                verdict = manual_verdict(req)
            with session_scope() as session:
                repo.save_recomendacion(session, eval_id, verdict, model)
        finally:
            async with self:
                self.busy = False
                self.task_log = []
                if notice:
                    self.ai_notice = notice
                self._refresh()
        return rx.toast.warning(notice) if notice else rx.toast.success("Dictamen ejecutivo generado.")

    # --- Contexto: ingesta y pre-evaluación IA ------------------------------

    @rx.event
    def set_repo_url_input(self, value: str):
        self.repo_url_input = value

    @rx.event
    async def handle_upload(self, files: list[rx.UploadFile]):
        base = Path(get_settings().ingest_tmp_dir) / "uploads"
        base.mkdir(parents=True, exist_ok=True)
        for f in files:
            name = Path(f.name or "archivo").name
            tmp = Path(tempfile.mkstemp(prefix="up-", suffix=f"-{name}", dir=base)[1])
            with tmp.open("wb") as out:
                out.write(await f.read())
            self._upload_paths[name] = str(tmp)
        self.pending_uploads = sorted(self._upload_paths)

    @rx.event
    def remove_upload(self, name: str):
        path = self._upload_paths.pop(name, None)
        if path:
            Path(path).unlink(missing_ok=True)
        self.pending_uploads = sorted(self._upload_paths)

    def _switch_manual(self, reason: str) -> None:
        with session_scope() as session:
            repo.set_modo(session, self.eval_id, ModoEvaluacion.MANUAL)
        self.modo = ModoEvaluacion.MANUAL.value
        self.ai_notice = f"Modo manual activado: {reason}"

    @rx.event(background=True)
    async def start_ingest(self):
        async with self:
            if self.busy or not self.can_edit_decisor:
                return
            url = self.repo_url_input.strip()
            uploads = dict(self._upload_paths)
            if not url and not uploads:
                self._switch_manual("no se proporcionó repositorio ni documentos.")
                return rx.toast.info("Sin artefactos: continúe con la evaluación manual de 6 pasos.")
            self.busy = True
            self.ai_notice = ""
            self.task_log = ["Preparando ingesta…"]
            self._upload_paths = {}
            self.pending_uploads = []
            eval_id = self.eval_id

        sources = [IngestSource("git", url=url)] if url else []
        for name, path in uploads.items():
            kind = "zip" if name.lower().endswith(".zip") else "file"
            sources.append(IngestSource(kind, path=Path(path), filename=name))

        result, error, notice, stats = None, "", "", None
        try:
            # 1) Ingesta y análisis estático deterministas (no dependen de la IA).
            result = await run_with_progress(self, "task_log", lambda n: ingest(sources, None, progress=n))
            # Los fragmentos se guardan antes de los embeddings: un fallo de la IA no los pierde.
            with session_scope() as session:
                repo.replace_chunks(session, eval_id, result.chunks)
                if url:
                    ev = repo.get_evaluacion(session, eval_id)
                    ev.url_repositorio = url
                    session.add(ev)
            # 2) Embeddings (por lotes, reanudables) + pre-evaluación IA.
            stats, notice = await self._embed_and_prefill(eval_id)
        except IngestError as exc:
            error = str(exc)
        except Exception as exc:  # noqa: BLE001 - nunca romper el flujo manual
            error = f"Error inesperado en la ingesta: {exc}"
        finally:
            for path in uploads.values():
                Path(path).unlink(missing_ok=True)
            async with self:
                self.busy = False
                self.task_log = _stats_lines(stats)
                if result is not None and result.errores:
                    self.task_log += [f"Aviso: {e}" for e in result.errores[:10]]
                if notice or error:
                    self._switch_manual(error or notice)
                self._refresh()
        if error:
            return rx.toast.error(error)
        if notice:
            return rx.toast.warning("La pre-evaluación IA no se completó: revise el aviso.")
        return rx.toast.success("Contexto procesado y subfactores pre-evaluados.")

    async def _embed_and_prefill(self, eval_id: int) -> tuple[PrefillStats | None, str]:
        """Reanuda embeddings pendientes y ejecuta la pre-evaluación. Devuelve (stats, aviso)."""
        try:
            client = get_ai_client()
        except AIUnavailable as exc:
            return None, str(exc)
        try:
            embedded, total = await run_with_progress(
                self, "task_log", lambda n: embed_pending_chunks(eval_id, client, n)
            )
        except AIUnavailable as exc:
            with session_scope() as session:
                done, total = repo.embedding_stats(session, eval_id)
            return None, (
                f"embeddings incompletos ({done}/{total} fragmentos guardados): {exc}. "
                "Pulse «Re-ejecutar pre-evaluación IA» para reanudar."
            )
        if embedded <= 1:  # Solo el resumen del análisis estático.
            return None, "no hay fragmentos del repositorio o documentos con embedding: la IA no tendría contexto."

        def _prefill(notify):
            with session_scope() as session:
                return prefill(session, eval_id, client, notify)

        try:
            stats = await run_with_progress(self, "task_log", _prefill)
        except AIUnavailable as exc:
            return None, f"la pre-evaluación IA falló ({exc}); lo ya procesado se conservó."
        with session_scope() as session:
            repo.set_modo(session, eval_id, ModoEvaluacion.HIBRIDO_IA)
        return stats, ""

    @rx.event(background=True)
    async def rerun_prefill(self):
        async with self:
            if self.busy or not self.can_edit_decisor or not self.chunk_count:
                return
            self.busy = True
            eval_id = self.eval_id
        stats, notice = None, ""
        try:
            stats, notice = await self._embed_and_prefill(eval_id)
        finally:
            async with self:
                self.busy = False
                self.task_log = _stats_lines(stats)
                if notice:
                    self._switch_manual(notice)
                self._refresh()
        return rx.toast.warning("La pre-evaluación IA no se completó: revise el aviso.") if notice else rx.toast.success("Pre-evaluación actualizada.")

    # --- Equipo -------------------------------------------------------------

    @rx.event
    def invite(self, form: dict):
        if self.my_role != Rol.DECISOR.value:
            return rx.toast.error("Solo el decisor puede invitar participantes.")
        email = str(form.get("email", "")).strip()
        rol = Rol(str(form.get("rol", Rol.EVALUADOR.value)))
        try:
            with session_scope() as session:
                repo.add_participant(session, self.eval_id, email, rol)
                self._reload(session)
        except ValueError as exc:
            return rx.toast.error(str(exc))
        return rx.toast.success(f"{email} añadido como {rol.value}.")


def cleanup_uploads() -> None:
    """Elimina restos de subidas (p. ej., al reiniciar el servidor)."""
    shutil.rmtree(Path(get_settings().ingest_tmp_dir) / "uploads", ignore_errors=True)
