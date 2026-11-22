"""Calibración bibliográfica 2020–2025 (RF-BIB-01/02).

Para cada factor: búsqueda en OpenAlex, Crossref y Semantic Scholar → deduplicación →
clasificación de pertinencia con Gemini → persistencia en ``articulo_literatura`` →
``core.calibration`` (c_i, n_i, r_i, IL, IS) → ``factor.is_vigente``.
"""

import asyncio
import re
from collections.abc import Callable
from dataclasses import dataclass

import httpx
from pydantic import BaseModel, Field

from ..core.calibration import calibrate
from ..core.schemas import CalibracionFactorInput, CalibracionResultado
from ..models import repository as repo
from ..models.database import ArticuloLiteratura
from ..models.session import session_scope
from ..settings import Settings, get_settings
from .ai_client import AIClient
from .sanitizer import UNTRUSTED_NOTICE, wrap_untrusted

OPENALEX_URL = "https://api.openalex.org/works"
CROSSREF_URL = "https://api.crossref.org/works"
S2_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
USER_AGENT = "GUIOSAD-calibracion/1.0"
CLASSIFY_BATCH = 20
MAX_CONCURRENT_LLM = 4


@dataclass
class Candidate:
    titulo: str
    autores: str | None
    anio: int | None
    fuente: str
    doi_o_url: str | None
    abstract: str | None

    @property
    def key(self) -> str:
        if self.doi_o_url and "doi.org/" in self.doi_o_url.lower():
            return self.doi_o_url.lower().split("doi.org/")[-1]
        return re.sub(r"\W+", "", self.titulo.lower())[:120]


# --- Utilidades -------------------------------------------------------------

def keywords(boolean_query: str) -> str:
    """Convierte una cadena booleana en palabras clave para APIs sin operadores."""
    text = re.sub(r"\b(AND|OR|NOT)\b", " ", boolean_query)
    text = re.sub(r"[()\"]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def openalex_abstract(inverted: dict[str, list[int]] | None) -> str | None:
    if not inverted:
        return None
    positions = [(pos, word) for word, idx in inverted.items() for pos in idx]
    return " ".join(w for _, w in sorted(positions))


def _strip_tags(text: str | None) -> str | None:
    return re.sub(r"<[^>]+>", " ", text).strip() if text else None


async def _get(client: httpx.AsyncClient, url: str, params: dict, headers: dict | None = None) -> dict:
    for attempt in range(4):
        resp = await client.get(url, params=params, headers=headers)
        if resp.status_code == 429 or resp.status_code >= 500:
            await asyncio.sleep(min(2 ** (attempt + 1), 16))
            continue
        resp.raise_for_status()
        return resp.json()
    resp.raise_for_status()
    return {}


# --- Fuentes ---------------------------------------------------------------

async def search_openalex(client: httpx.AsyncClient, query: str, s: Settings, limit: int) -> list[Candidate]:
    params = {
        "search": query,
        "filter": f"publication_year:{s.calibracion_anio_inicio}-{s.calibracion_anio_fin}",
        "per_page": min(limit, 200),
        "select": "doi,title,authorships,publication_year,abstract_inverted_index,id",
    }
    if s.openalex_mailto:
        params["mailto"] = s.openalex_mailto
    data = await _get(client, OPENALEX_URL, params)
    out = []
    for w in data.get("results", [])[:limit]:
        if not w.get("title"):
            continue
        authors = ", ".join(
            a.get("author", {}).get("display_name", "") for a in (w.get("authorships") or [])[:10]
        )
        out.append(Candidate(w["title"], authors or None, w.get("publication_year"), "OpenAlex",
                             w.get("doi") or w.get("id"), openalex_abstract(w.get("abstract_inverted_index"))))
    return out


async def search_crossref(client: httpx.AsyncClient, query: str, s: Settings, limit: int) -> list[Candidate]:
    params = {
        "query.bibliographic": keywords(query),
        "filter": f"from-pub-date:{s.calibracion_anio_inicio}-01-01,until-pub-date:{s.calibracion_anio_fin}-12-31",
        "rows": min(limit, 100),
        "select": "DOI,title,author,issued,abstract,URL",
    }
    if s.crossref_mailto:
        params["mailto"] = s.crossref_mailto
    data = await _get(client, CROSSREF_URL, params)
    out = []
    for it in data.get("message", {}).get("items", [])[:limit]:
        title = (it.get("title") or [""])[0]
        if not title:
            continue
        year = (it.get("issued", {}).get("date-parts") or [[None]])[0][0]
        authors = ", ".join(
            f"{a.get('given', '')} {a.get('family', '')}".strip() for a in (it.get("author") or [])[:10]
        )
        doi = it.get("DOI")
        out.append(Candidate(title, authors or None, year, "Crossref",
                             f"https://doi.org/{doi}" if doi else it.get("URL"), _strip_tags(it.get("abstract"))))
    return out


async def search_semantic_scholar(client: httpx.AsyncClient, query: str, s: Settings, limit: int) -> list[Candidate]:
    params = {
        "query": keywords(query)[:300],
        "year": f"{s.calibracion_anio_inicio}-{s.calibracion_anio_fin}",
        "fields": "title,authors,year,abstract,externalIds,url",
        "limit": min(limit, 100),
    }
    headers = {"x-api-key": s.semantic_scholar_api_key} if s.semantic_scholar_api_key else None
    data = await _get(client, S2_URL, params, headers)
    out = []
    for p in (data.get("data") or [])[:limit]:
        if not p.get("title"):
            continue
        doi = (p.get("externalIds") or {}).get("DOI")
        authors = ", ".join(a.get("name", "") for a in (p.get("authors") or [])[:10])
        out.append(Candidate(p["title"], authors or None, p.get("year"), "Semantic Scholar",
                             f"https://doi.org/{doi}" if doi else p.get("url"), p.get("abstract")))
    return out


async def collect(client: httpx.AsyncClient, query: str, s: Settings) -> tuple[list[Candidate], list[str]]:
    per_source = max(1, s.calibracion_max_articulos_por_factor // 3)
    tasks = [
        search_openalex(client, query, s, per_source),
        search_crossref(client, query, s, per_source),
        search_semantic_scholar(client, query, s, per_source),
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    seen: dict[str, Candidate] = {}
    errors: list[str] = []
    for name, res in zip(("OpenAlex", "Crossref", "Semantic Scholar"), results):
        if isinstance(res, Exception):
            errors.append(f"{name}: {res}")
            continue
        for c in res:
            if c.anio is None or s.calibracion_anio_inicio <= c.anio <= s.calibracion_anio_fin:
                seen.setdefault(c.key, c)
    return list(seen.values()), errors


# --- Pertinencia con Gemini -------------------------------------------------

class _Pertinencia(BaseModel):
    indice: int
    es_pertinente: bool
    razon: str = Field(description="Justificación breve en español")


class _PertinenciaLote(BaseModel):
    articulos: list[_Pertinencia]


SYSTEM_INSTRUCTION = f"""Eres un revisor sistemático de literatura científica.
Determina si cada artículo trata sobre la evaluación, selección o adopción de software de
código abierto (OSS/FLOSS) EN RELACIÓN CON el factor indicado. Marca es_pertinente=false si
el artículo no aborda software libre/abierto, no trata de adopción/evaluación, o no se
relaciona con el factor. Devuelve un elemento por cada índice recibido.
{UNTRUSTED_NOTICE}"""


async def classify(client: AIClient, factor: str, candidates: list[Candidate], sem: asyncio.Semaphore) -> list[_Pertinencia]:
    model = get_settings().gemini_model_calibracion

    async def one_batch(start: int) -> list[_Pertinencia]:
        batch = candidates[start : start + CLASSIFY_BATCH]
        body = "\n".join(
            wrap_untrusted(f"Título: {c.titulo}\nAño: {c.anio}\nResumen: {(c.abstract or 'n/d')[:1500]}", indice=start + i)
            for i, c in enumerate(batch)
        )
        async with sem:
            res = await client.agenerate_json(model, SYSTEM_INSTRUCTION, f"Factor: {factor}\n\n{body}", _PertinenciaLote)
        return res.articulos

    lotes = await asyncio.gather(*(one_batch(i) for i in range(0, len(candidates), CLASSIFY_BATCH)))
    return [p for lote in lotes for p in lote]


# --- Orquestación -----------------------------------------------------------

async def run_calibration(
    usuario_id: int | None,
    client: AIClient,
    progress: Callable[[str], None] | None = None,
    http_client: httpx.AsyncClient | None = None,
) -> tuple[int, CalibracionResultado, list[str]]:
    """Ejecuta una calibración completa y la marca como vigente.

    Devuelve (id de calibración, resultado, avisos). Lanza ``AIUnavailable`` si falla Gemini.
    """
    s = get_settings()
    notify = progress or (lambda _m: None)
    warnings: list[str] = []
    with session_scope() as session:
        factors = [(f.id, f.nombre, f.cadena_busqueda) for f in repo.list_factors(session, only_active=True)]
        n_active = repo.active_subfactor_counts(session)
        cal_id = repo.create_calibracion(session, usuario_id, s.calibracion_anio_inicio, s.calibracion_anio_fin).id

    sem = asyncio.Semaphore(MAX_CONCURRENT_LLM)
    owns_client = http_client is None
    http = http_client or httpx.AsyncClient(timeout=s.http_timeout_seconds, headers={"User-Agent": USER_AGENT})
    inputs: list[CalibracionFactorInput] = []
    try:
        for i, (fid, nombre, query) in enumerate(factors, start=1):
            notify(f"[{i}/{len(factors)}] Buscando literatura para «{nombre}»…")
            candidates, errs = await collect(http, query, s)
            warnings += [f"{nombre} — {e}" for e in errs]
            notify(f"[{i}/{len(factors)}] Clasificando {len(candidates)} artículos de «{nombre}»…")
            verdicts = {p.indice: p for p in await classify(client, nombre, candidates, sem)} if candidates else {}
            pertinentes = 0
            articulos = []
            for idx, c in enumerate(candidates):
                v = verdicts.get(idx)
                es_p = bool(v and v.es_pertinente)
                pertinentes += es_p
                articulos.append(
                    ArticuloLiteratura(
                        calibracion_id=cal_id, factor_id=fid, titulo=c.titulo, autores=c.autores,
                        anio_publicacion=c.anio, fuente_indexada=c.fuente, doi_o_url=(c.doi_o_url or "")[:500] or None,
                        abstract=c.abstract, es_pertinente=es_p, razon_pertinencia_ia=v.razon if v else "Sin clasificar",
                    )
                )
            with session_scope() as session:
                repo.save_articulos(session, articulos)
            if fid not in n_active:
                warnings.append(f"{nombre}: sin subfactores activos, se omite.")
                continue
            inputs.append(CalibracionFactorInput(factor_id=fid, citas_pertinentes=pertinentes, subfactores_activos=n_active[fid]))
    finally:
        if owns_client:
            await http.aclose()

    result = calibrate(inputs)
    with session_scope() as session:
        repo.apply_calibration(session, cal_id, result, "; ".join(warnings)[:2000])
    notify("Calibración completada.")
    return cal_id, result, warnings
