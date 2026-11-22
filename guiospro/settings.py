"""Configuración de la aplicación leída desde variables de entorno / ``.env``."""

from functools import cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    # Base de datos
    database_url: str = "sqlite:///guiosad.db"
    test_database_url: str = ""

    # Autenticación
    auth_secret_key: str = ""
    auth_session_minutes: int = 480
    admin_email: str = ""
    admin_password: str = ""

    # Google AI
    gemini_api_key: str = ""
    gemini_model_evaluacion: str = "gemini-3.8-flash"
    gemini_model_dictamen: str = "gemini-3.8-flash"
    gemini_model_calibracion: str = "gemini-3.5-flash-lite"
    gemini_embedding_model: str = "gemini-embedding-2"
    gemini_embedding_dim: int = 768
    gemini_temperature: float = 0.0
    gemini_timeout_seconds: int = 60
    gemini_max_retries: int = 2
    # Reintentos ante 429 (cuota) respetando el retryDelay de la API.
    gemini_rate_limit_retries: int = 5
    # Tokens por minuto para embeddings (Tier 1 = 1.000.000; se deja margen).
    gemini_embed_tpm_limit: int = 800_000

    # Ingesta y RAG
    ingest_tmp_dir: str = "/tmp/guiosad"
    ingest_max_zip_mb: int = 200
    ingest_max_files: int = 5000
    ingest_max_code_chunks: int = 400
    ingest_max_chunks_per_file: int = 20
    ingest_git_clone_depth: int = 1
    rag_chunk_tokens: int = 800
    rag_chunk_overlap: int = 100
    rag_top_k: int = 8

    # Calibración bibliográfica
    calibracion_anio_inicio: int = 2020
    calibracion_anio_fin: int = 2025
    calibracion_max_articulos_por_factor: int = 200
    openalex_mailto: str = ""
    crossref_mailto: str = ""
    semantic_scholar_api_key: str = ""
    http_timeout_seconds: int = 30

    @property
    def ai_enabled(self) -> bool:
        return bool(self.gemini_api_key.strip())


@cache
def get_settings() -> Settings:
    return Settings()
