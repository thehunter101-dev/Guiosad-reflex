"""Ingesta técnica (RF-AUTO-01..03): Git/ZIP/PDF/MD/CSV → análisis estático → chunks RAG.

Todo se procesa en un directorio temporal que se elimina siempre al terminar (RNF-04).
"""

import shutil
import stat
import tempfile
import zipfile
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse

from ..core.constants import CategoriaChunk
from ..models import repository as repo
from ..models.database import DocumentoChunk
from ..models.session import session_scope
from ..settings import Settings, get_settings
from . import licenses
from .ai_client import EMBED_BATCH, AIClient

ALLOWED_GIT_HOSTS = {"github.com", "gitlab.com", "www.github.com", "www.gitlab.com"}
DOC_UPLOAD_EXT = {".pdf", ".md", ".markdown", ".csv", ".txt", ".rst"}
MAX_FILE_BYTES = 1_000_000
STATIC_REPORT_PATH = "[análisis estático]"

# Código de terceros embebido: no describe al software evaluado y dispara el volumen RAG.
THIRD_PARTY_DIRS = {
    "externals", "external", "extern", "third_party", "thirdparty", "third-party", "3rdparty",
    "deps", "vendored", "submodules",
}  # fmt: skip
SKIP_DIRS = {
    ".git", "node_modules", "vendor", "dist", "build", "__pycache__", ".venv", "venv",
    ".tox", ".mypy_cache", ".pytest_cache", "target", ".idea", ".vscode", "bower_components",
    ".next", ".nuxt", "coverage", "site-packages",
}  # fmt: skip
LICENSE_NAMES = ("license", "licence", "copying", "notice", "unlicense")
CONFIG_NAMES = {
    "package.json", "pyproject.toml", "setup.py", "setup.cfg", "requirements.txt", "pipfile",
    "dockerfile", "docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml",
    ".gitlab-ci.yml", "makefile", "pom.xml", "build.gradle", "build.gradle.kts", "go.mod",
    "cargo.toml", "composer.json", "gemfile", "tox.ini", "helm", "chart.yaml", ".travis.yml",
    "environment.yml", "manage.py", "meson.build", "cmakelists.txt",
}  # fmt: skip
CONFIG_EXT = {".yml", ".yaml", ".toml", ".ini", ".cfg", ".conf", ".properties", ".env.example"}
DOC_DIRS = {"docs", "doc", "documentation", "documents", "documentacion", "manual", "manuals", "wiki"}
DOC_EXT = {".md", ".markdown", ".rst", ".txt", ".adoc", ".csv", ".pdf"}
CODE_EXT = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".kt", ".go", ".rs", ".rb", ".php", ".c",
    ".h", ".cpp", ".hpp", ".cs", ".swift", ".scala", ".sql", ".sh", ".vue", ".svelte",
    ".dart", ".ex", ".exs", ".erl", ".lua", ".r", ".m", ".pl",
}  # fmt: skip
LANG_BY_EXT = {
    ".py": "Python", ".js": "JavaScript", ".ts": "TypeScript", ".tsx": "TypeScript",
    ".jsx": "JavaScript", ".java": "Java", ".kt": "Kotlin", ".go": "Go", ".rs": "Rust",
    ".rb": "Ruby", ".php": "PHP", ".c": "C", ".h": "C", ".cpp": "C++", ".hpp": "C++",
    ".cs": "C#", ".swift": "Swift", ".scala": "Scala", ".vue": "Vue", ".dart": "Dart",
}  # fmt: skip


class IngestError(ValueError):
    pass


@dataclass
class IngestSource:
    kind: str  # "git" | "zip" | "file"
    url: str | None = None
    path: Path | None = None
    filename: str | None = None


@dataclass
class StaticReport:
    total_archivos: int = 0
    lenguajes: dict[str, int] = field(default_factory=dict)
    licencias: list[licenses.LicenciaDetectada] = field(default_factory=list)
    manifiestos: list[str] = field(default_factory=list)
    tiene_ci: bool = False
    tiene_docker: bool = False
    tiene_tests: bool = False
    tiene_docs: bool = False
    archivos_clave: list[str] = field(default_factory=list)
    terceros_excluidos: list[str] = field(default_factory=list)
    fragmentos_codigo_omitidos: int = 0
    archivos_truncados: list[str] = field(default_factory=list)

    def to_text(self) -> str:
        lic = (
            "; ".join(f"{l.spdx} ({l.tipo.value}) en {l.archivo} [{l.metodo}]" for l in self.licencias)
            or "No se detectó licencia"
        )
        langs = ", ".join(f"{k}: {v}" for k, v in sorted(self.lenguajes.items(), key=lambda x: -x[1]))
        yn = lambda b: "sí" if b else "no"  # noqa: E731
        return "\n".join(
            [
                "Resultado del análisis estático determinista del repositorio:",
                f"- Total de archivos analizados: {self.total_archivos}",
                f"- Lenguajes (archivos): {langs or 'n/d'}",
                f"- Licencias: {lic}",
                f"- Manifiestos/configuración: {', '.join(self.manifiestos) or 'ninguno'}",
                f"- Integración continua: {yn(self.tiene_ci)}",
                f"- Contenedores (Docker): {yn(self.tiene_docker)}",
                f"- Pruebas automatizadas: {yn(self.tiene_tests)}",
                f"- Carpeta/sitio de documentación: {yn(self.tiene_docs)}",
                f"- Archivos clave: {', '.join(self.archivos_clave) or 'ninguno'}",
                f"- Código de terceros excluido: {', '.join(self.terceros_excluidos) or 'ninguno'}",
                f"- Fragmentos de código no indexados por el tope: {self.fragmentos_codigo_omitidos}",
                f"- Archivos grandes truncados: {', '.join(self.archivos_truncados) or 'ninguno'}",
            ]
        )


@dataclass
class IngestResult:
    chunks: list[DocumentoChunk]
    report: StaticReport
    errores: list[str]
    embebidos: bool


# --- Validación de fuentes --------------------------------------------------

def validate_git_url(url: str) -> str:
    parsed = urlparse(url.strip())
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_GIT_HOSTS:
        raise IngestError("Solo se admiten URL https de GitHub o GitLab.")
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) < 2:
        raise IngestError("La URL debe apuntar a un repositorio (usuario/proyecto).")
    if parsed.username or parsed.password:
        raise IngestError("La URL no debe incluir credenciales.")
    return url.strip()


def _clone(url: str, dest: Path, settings: Settings) -> None:
    import git

    try:
        git.Repo.clone_from(
            validate_git_url(url),
            dest,
            depth=settings.ingest_git_clone_depth,
            multi_options=["--single-branch", "--no-tags"],
            env={"GIT_TERMINAL_PROMPT": "0", "GIT_LFS_SKIP_SMUDGE": "1"},
        )
    except git.GitCommandError as exc:
        raise IngestError(f"No se pudo clonar el repositorio: {exc.stderr.strip()[:300]}") from exc


def safe_extract_zip(zip_path: Path, dest: Path, settings: Settings) -> None:
    """Extrae evitando zip-slip, enlaces simbólicos y bombas de descompresión."""
    max_bytes = settings.ingest_max_zip_mb * 1024 * 1024
    dest = dest.resolve()
    try:
        with zipfile.ZipFile(zip_path) as zf:
            infos = zf.infolist()
            if len(infos) > settings.ingest_max_files * 4:
                raise IngestError("El ZIP contiene demasiados archivos.")
            if sum(i.file_size for i in infos) > max_bytes:
                raise IngestError(f"El ZIP descomprimido supera {settings.ingest_max_zip_mb} MB.")
            for info in infos:
                if stat.S_ISLNK(info.external_attr >> 16):
                    continue
                target = (dest / info.filename).resolve()
                if not target.is_relative_to(dest):
                    raise IngestError(f"Ruta no permitida en el ZIP: {info.filename}")
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, target.open("wb") as out:
                    shutil.copyfileobj(src, out)
    except zipfile.BadZipFile as exc:
        raise IngestError("El archivo no es un ZIP válido.") from exc


# --- Clasificación y lectura ------------------------------------------------

def categorize(rel: PurePosixPath) -> CategoriaChunk | None:
    name = rel.name.lower()
    suffix = rel.suffix.lower()
    # LICENSE*, COPYING*… y la carpeta LICENSES/ de la convención REUSE.
    if name.startswith(LICENSE_NAMES) or (len(rel.parts) > 1 and rel.parts[-2].lower() in {"licenses", "licences"}):
        return CategoriaChunk.LICENCIA
    if (
        name in CONFIG_NAMES
        or name.startswith(("requirements", "dockerfile", "docker-compose"))
        or ".github/workflows" in rel.as_posix()
        or (suffix in CONFIG_EXT and len(rel.parts) <= 2)
    ):
        return CategoriaChunk.CONFIGURACION
    if suffix in DOC_EXT or (rel.parts and rel.parts[0].lower() in DOC_DIRS):
        return CategoriaChunk.DOCUMENTACION
    if suffix in CODE_EXT:
        return CategoriaChunk.CODIGO
    return None


def _read_text(path: Path) -> str | None:
    try:
        raw = path.read_bytes()[:MAX_FILE_BYTES]
    except OSError:
        return None
    if b"\x00" in raw[:4096]:
        return None
    return raw.decode("utf-8", errors="replace")


def _read_pdf(path: Path) -> list[tuple[str, str]]:
    import pymupdf

    pages = []
    with pymupdf.open(path) as doc:
        for i, page in enumerate(doc, start=1):
            text = page.get_text().strip()
            if text:
                pages.append((f"p. {i}", text))
    return pages


def chunk_lines(text: str, max_chars: int, overlap_chars: int) -> list[tuple[str, str]]:
    """Divide por líneas conservando el rango ``L{inicio}-{fin}``."""
    lines = text.splitlines()
    chunks: list[tuple[str, str]] = []
    start = 0
    while start < len(lines):
        size, end = 0, start
        while end < len(lines) and (size + len(lines[end]) + 1 <= max_chars or end == start):
            size += len(lines[end]) + 1
            end += 1
        body = "\n".join(lines[start:end]).strip()
        if body:
            chunks.append((f"L{start + 1}-{end}", body))
        if end >= len(lines):
            break
        back, back_size = end, 0
        while back > start + 1 and back_size < overlap_chars:
            back -= 1
            back_size += len(lines[back]) + 1
        start = back if back > start else end
    return chunks


# --- Proceso principal ------------------------------------------------------

def _walk(root: Path, limit: int, third_party: set[str] | None = None) -> list[Path]:
    files: list[Path] = []
    for p in sorted(root.rglob("*")):
        if len(files) >= limit:
            break
        rel_parts = p.relative_to(root).parts
        if any(part in SKIP_DIRS for part in rel_parts) or p.is_symlink():
            continue
        tp = next((i for i, part in enumerate(rel_parts) if part.lower() in THIRD_PARTY_DIRS), None)
        if tp is not None:
            if third_party is not None:
                third_party.add("/".join(rel_parts[: tp + 1]))
            continue
        if p.is_file():
            files.append(p)
    return files


def _round_robin(per_file: list[list[DocumentoChunk]], limit: int) -> tuple[list[DocumentoChunk], int]:
    """Selecciona fragmentos de código repartidos entre archivos (primero el inicio de cada uno)."""
    selected: list[DocumentoChunk] = []
    depth = 0
    while len(selected) < limit and any(depth < len(c) for c in per_file):
        for chunks in per_file:
            if depth < len(chunks):
                selected.append(chunks[depth])
                if len(selected) >= limit:
                    break
        depth += 1
    total = sum(len(c) for c in per_file)
    return selected, total - len(selected)


def analyze_and_chunk(
    roots: list[tuple[str, Path]], settings: Settings
) -> tuple[list[DocumentoChunk], StaticReport, list[str]]:
    max_chars = settings.rag_chunk_tokens * 4
    overlap = settings.rag_chunk_overlap * 4
    report = StaticReport()
    langs: Counter[str] = Counter()
    chunks: list[DocumentoChunk] = []
    code_per_file: list[list[DocumentoChunk]] = []
    errores: list[str] = []

    for label, root in roots:
        excluded: set[str] = set()
        for path in _walk(root, settings.ingest_max_files, excluded):
            rel = PurePosixPath(path.relative_to(root).as_posix())
            display = f"{label}/{rel}" if label else str(rel)
            report.total_archivos += 1
            suffix = rel.suffix.lower()
            if suffix in LANG_BY_EXT:
                langs[LANG_BY_EXT[suffix]] += 1
            lower = rel.as_posix().lower()
            if ".github/workflows" in lower or rel.name in {".gitlab-ci.yml", ".travis.yml", "Jenkinsfile"}:
                report.tiene_ci = True
            if rel.name.lower().startswith(("dockerfile", "docker-compose", "compose.y")):
                report.tiene_docker = True
            if any(p.lower() in {"test", "tests", "spec", "__tests__"} for p in rel.parts[:-1]) or rel.name.startswith("test_"):
                report.tiene_tests = True
            if rel.parts and rel.parts[0].lower() in DOC_DIRS:
                report.tiene_docs = True
            if rel.name.upper().split(".")[0] in {"README", "CONTRIBUTING", "SECURITY", "CHANGELOG", "CODE_OF_CONDUCT", "ADOPTERS"} and len(rel.parts) == 1:
                report.archivos_clave.append(display)

            cat = categorize(rel)
            if cat is None:
                continue
            if cat == CategoriaChunk.CONFIGURACION:
                report.manifiestos.append(display)

            if suffix == ".pdf":
                try:
                    pieces = [(loc, txt) for loc, txt in _read_pdf(path)]
                except Exception as exc:  # PDF corrupto
                    errores.append(f"{display}: no se pudo leer el PDF ({exc})")
                    continue
                full_text = "\n".join(t for _, t in pieces)
                split = [(loc, part) for loc, t in pieces for _, part in chunk_lines(t, max_chars, overlap)]
            else:
                text = _read_text(path)
                if text is None:
                    continue
                full_text = text
                split = chunk_lines(text, max_chars, overlap)

            if cat == CategoriaChunk.LICENCIA:
                spdx = licenses.detect_from_filename(rel.name) or licenses.detect_from_text(full_text)
                if spdx:
                    report.licencias.append(licenses.make(spdx, display, "texto"))
            elif cat == CategoriaChunk.CONFIGURACION:
                spdx = licenses.detect_from_manifest(rel.name, full_text)
                if spdx:
                    report.licencias.append(licenses.make(spdx, display, "manifiesto"))
            elif cat == CategoriaChunk.CODIGO:
                spdx = licenses.detect_spdx_header(full_text)
                if spdx and not any(l.spdx == licenses.normalize_spdx(spdx) for l in report.licencias):
                    report.licencias.append(licenses.make(spdx, display, "cabecera-spdx"))

            file_chunks = [
                DocumentoChunk(
                    evaluacion_id=0,
                    ruta_archivo=display[:1000],
                    ubicacion=loc,
                    categoria=cat.value,
                    contenido_texto=body,
                )
                for loc, body in split
            ]
            if cat == CategoriaChunk.CODIGO:
                code_per_file.append(file_chunks)
            else:
                # Archivos enormes (listas de datos, volcados) no aportan más evidencia.
                if len(file_chunks) > settings.ingest_max_chunks_per_file:
                    report.archivos_truncados.append(f"{display} ({len(file_chunks)} fragmentos)")
                    file_chunks = file_chunks[: settings.ingest_max_chunks_per_file]
                chunks.extend(file_chunks)
        report.terceros_excluidos += sorted(f"{label}/{d}" if label else d for d in excluded)

    code, report.fragmentos_codigo_omitidos = _round_robin(code_per_file, settings.ingest_max_code_chunks)
    chunks.extend(code)
    report.lenguajes = dict(langs)
    chunks.insert(
        0,
        DocumentoChunk(
            evaluacion_id=0,
            ruta_archivo=STATIC_REPORT_PATH,
            ubicacion="resumen",
            categoria=CategoriaChunk.CONFIGURACION.value,
            contenido_texto=report.to_text(),
        ),
    )
    return chunks, report, errores


def embed_chunks(
    chunks: list[DocumentoChunk], client: AIClient, progress: Callable[[str], None] | None = None
) -> None:
    """Calcula los embeddings de los chunks. Lanza ``AIUnavailable`` si falla la API."""
    if progress:
        progress(f"Generando embeddings de {len(chunks)} fragmentos…")
    vectors = client.embed(
        [f"{c.ruta_archivo} ({c.ubicacion})\n{c.contenido_texto}" for c in chunks], "document", progress
    )
    for c, v in zip(chunks, vectors):
        c.embedding = v


def embed_pending_chunks(
    evaluacion_id: int,
    client: AIClient,
    progress: Callable[[str], None] | None = None,
    scope=session_scope,
) -> tuple[int, int]:
    """Genera embeddings de los fragmentos guardados que aún no los tienen.

    Persiste cada lote al terminarlo: si la API falla (``AIUnavailable``), lo ya
    procesado se conserva y una nueva ejecución reanuda desde ahí.
    Devuelve (fragmentos con embedding, total).
    """
    notify = progress or (lambda _m: None)
    while True:
        with scope() as session:
            batch = repo.pending_embedding_chunks(session, evaluacion_id, EMBED_BATCH)
            items = [(c.id, f"{c.ruta_archivo} ({c.ubicacion})\n{c.contenido_texto}") for c in batch]
            done, total = repo.embedding_stats(session, evaluacion_id)
        if not items:
            return done, total
        notify(f"Embeddings: {done}/{total} fragmentos…")
        vectors = client.embed([text for _, text in items], "document", notify)
        with scope() as session:
            repo.set_chunk_embeddings(session, {cid: v for (cid, _), v in zip(items, vectors)})


def ingest(
    sources: list[IngestSource],
    client: AIClient | None = None,
    settings: Settings | None = None,
    progress: Callable[[str], None] | None = None,
) -> IngestResult:
    """Procesa las fuentes y devuelve chunks (con embeddings si hay cliente IA).

    Lanza ``IngestError`` ante fuentes inválidas y ``AIUnavailable`` si fallan los
    embeddings; en ese caso el estado reintenta sin IA (modo manual).
    """
    settings = settings or get_settings()
    notify = progress or (lambda _msg: None)
    base = Path(settings.ingest_tmp_dir)
    base.mkdir(parents=True, exist_ok=True)
    workdir = Path(tempfile.mkdtemp(prefix="ingesta-", dir=base))
    try:
        roots: list[tuple[str, Path]] = []
        docs_dir = workdir / "documentos"
        for i, src in enumerate(sources):
            if src.kind == "git":
                notify(f"Clonando {src.url}…")
                dest = workdir / f"repo{i}"
                _clone(src.url or "", dest, settings)
                roots.append((PurePosixPath(urlparse(src.url or "").path).name.removesuffix(".git"), dest))
            elif src.kind == "zip":
                notify(f"Extrayendo {src.filename}…")
                dest = workdir / f"zip{i}"
                dest.mkdir()
                safe_extract_zip(src.path, dest, settings)
                roots.append((Path(src.filename or f"zip{i}").stem, dest))
            elif src.kind == "file":
                name = Path(src.filename or "documento").name
                if Path(name).suffix.lower() not in DOC_UPLOAD_EXT and not name.lower().startswith(LICENSE_NAMES):
                    raise IngestError(f"Tipo de archivo no admitido: {name}")
                docs_dir.mkdir(exist_ok=True)
                shutil.copy(src.path, docs_dir / name)
            else:
                raise IngestError(f"Fuente desconocida: {src.kind}")
        if docs_dir.exists():
            roots.append(("documentos", docs_dir))

        notify("Analizando archivos…")
        chunks, report, errores = analyze_and_chunk(roots, settings)

        embebidos = False
        if client is not None and chunks:
            embed_chunks(chunks, client, notify)
            embebidos = True
        return IngestResult(chunks=chunks, report=report, errores=errores, embebidos=embebidos)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
        for src in sources:  # Archivos subidos: también se eliminan.
            if src.path is not None and src.path.exists():
                src.path.unlink(missing_ok=True)
