"""Panel de calibración bibliográfica en vivo (RF-AUTH-02)."""

import reflex as rx

from ..models import repository as repo
from ..models.session import session_scope
from ..services.ai_client import AIUnavailable, get_ai_client
from ..services.literature_ai import run_calibration
from ..settings import get_settings
from .auth_state import AuthState
from .models import ArticleRow, CalibrationRow, CalibrationRun
from .tasks import run_with_progress


class CalibrationState(AuthState):
    runs: list[CalibrationRun] = []
    selected_run: int = 0
    rows: list[CalibrationRow] = []
    quartiles: str = ""
    running: bool = False
    log: list[str] = []
    articles_open: bool = False
    articles_factor: str = ""
    articles: list[ArticleRow] = []

    @rx.var
    def periodo(self) -> str:
        s = get_settings()
        return f"{s.calibracion_anio_inicio}–{s.calibracion_anio_fin}"

    @rx.var
    def ai_configured(self) -> bool:
        return get_settings().ai_enabled

    @rx.event
    def load(self):
        if not self.is_admin:
            return
        with session_scope() as session:
            self.runs = [
                CalibrationRun(
                    id=c.id,
                    fecha=c.fecha_ejecucion.strftime("%Y-%m-%d %H:%M"),
                    periodo=f"{c.anio_inicio}–{c.anio_fin}",
                    vigente=c.es_vigente,
                    observaciones=c.observaciones or "",
                )
                for c in repo.list_calibraciones(session)
            ]
            vigente = next((r.id for r in self.runs if r.vigente), 0)
            self._select(session, self.selected_run or vigente)

    def _select(self, session, run_id: int) -> None:
        self.selected_run = run_id
        self.rows = [
            CalibrationRow(
                factor_id=f.id, factor=f.nombre, citas=fc.citas_pertinentes, subfactores=fc.subfactores_activos,
                ratio=f"{fc.ratio_normalizado:.2f}", il=fc.il_calculado, ie=fc.ie_fijo, is_=fc.is_calculado,
            )
            for fc, f in repo.calibration_rows(session, run_id)
        ] if run_id else []
        run = next((r for r in self.runs if r.id == run_id), None)
        self.quartiles = run.observaciones.split(".")[0] if run and run.observaciones else ""

    @rx.event
    def select_run(self, value: str):
        with session_scope() as session:
            self._select(session, int(value))

    @rx.event
    def open_articles(self, factor_id: int, factor: str):
        with session_scope() as session:
            self.articles = [
                ArticleRow(
                    titulo=a.titulo, autores=a.autores or "", anio=str(a.anio_publicacion or ""),
                    fuente=a.fuente_indexada, enlace=a.doi_o_url or "", pertinente=a.es_pertinente,
                    razon=a.razon_pertinencia_ia or "",
                )
                for a in repo.articles_for(session, self.selected_run, factor_id)
            ]
        self.articles_factor = factor
        self.articles_open = True

    @rx.event
    def set_articles_open(self, value: bool):
        self.articles_open = value

    @rx.event(background=True)
    async def run(self):
        async with self:
            if self.running or not self.is_admin:
                return
            self.running = True
            self.log = ["Iniciando calibración…"]
            user_id = self.user_id
        error = ""
        try:
            client = get_ai_client()
            cal_id, _, warnings = await run_with_progress(
                self, "log", lambda notify: run_calibration(user_id, client, notify), is_async=True
            )
        except AIUnavailable as exc:
            error = f"Google AI no disponible: {exc}. Se mantiene la IS vigente."
        except Exception as exc:  # noqa: BLE001
            error = f"La calibración falló: {exc}. Se mantiene la IS vigente."
        finally:
            async with self:
                self.running = False
                if not error:
                    self.selected_run = cal_id
                    self.log = [f"Calibración #{cal_id} vigente."] + warnings[:5]
                else:
                    self.log = [error]
        async with self:
            self.load()
        return rx.toast.error(error) if error else rx.toast.success("IL e IS recalculadas.")
