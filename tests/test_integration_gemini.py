"""Pruebas contra la API real de Google AI (usan GEMINI_API_KEY de .env).

Se omiten por defecto. Ejecutar con:  GEMINI_INTEGRATION=1 python -m pytest tests/test_integration_gemini.py
"""

import os
import zipfile

import pytest
from pydantic import BaseModel

from guiospro.models import repository as repo
from guiospro.services.ai_client import EMBED_BATCH, GeminiClient
from guiospro.settings import Settings, get_settings

pytestmark = pytest.mark.skipif(
    os.environ.get("GEMINI_INTEGRATION") != "1" or not get_settings().ai_enabled,
    reason="Defina GEMINI_INTEGRATION=1 y GEMINI_API_KEY para ejecutar pruebas reales",
)


@pytest.fixture(scope="module")
def client():
    return GeminiClient()


def test_real_embeddings_one_vector_per_text(client):
    texts = [f"El software número {i} tiene documentación de usuario." for i in range(EMBED_BATCH + 20)]
    vectors = client.embed(texts, "document")
    assert len(vectors) == len(texts)
    assert all(len(v) == get_settings().gemini_embedding_dim for v in vectors)
    assert all(abs(sum(x * x for x in v) - 1.0) < 1e-6 for v in vectors)
    # Textos distintos -> vectores distintos (no un vector agregado repetido).
    assert vectors[0] != vectors[1]


def test_real_structured_output(client):
    class Respuesta(BaseModel):
        licencia: str
        es_copyleft: bool

    r = client.generate_json(
        get_settings().gemini_model_evaluacion,
        "Responde en JSON según el esquema.",
        "La licencia GPL-2.0 ¿es copyleft? Indica su identificador SPDX.",
        Respuesta,
    )
    assert "GPL" in r.licencia.upper() and r.es_copyleft is True


def test_real_end_to_end_prefill(engine, session, user, tmp_path, monkeypatch):
    from contextlib import contextmanager

    from sqlmodel import Session

    from guiospro.services.repo_ingestor import IngestSource, embed_pending_chunks, ingest
    from guiospro.services.subfactor_ai import prefill

    z = tmp_path / "demo.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("LICENSE", "MIT License\n\nPermission is hereby granted, free of charge, to any person "
                               "obtaining a copy of this software")
        zf.writestr("README.md", "# Demo\n\nDemo se instala con `docker compose up`. Incluye una interfaz "
                                 "web (GUI) y soporta Windows, macOS y Linux. Documentación en docs/.")
        zf.writestr("docs/usuario.md", "# Manual de usuario\n\nGuía completa de todas las funciones.")
        zf.writestr("Dockerfile", "FROM python:3.12-slim\nCOPY . /app\n")
    settings = Settings(ingest_tmp_dir=str(tmp_path / "tmp"))
    result = ingest([IngestSource("zip", path=z, filename="demo.zip")], None, settings)

    ev = repo.create_evaluacion(session, user.id, "Demo")
    repo.replace_chunks(session, ev.id, result.chunks)
    session.commit()

    @contextmanager
    def scope():
        with Session(engine, expire_on_commit=False) as s:
            yield s
            s.commit()

    client = GeminiClient()
    done, total = embed_pending_chunks(ev.id, client, scope=scope)
    assert done == total == len(result.chunks)

    with Session(engine, expire_on_commit=False) as s:
        stats = prefill(s, ev.id, client)
    assert stats.evaluados > 0 and stats.fragmentos_con_embedding > 0
    assert stats.con_evidencia > 0  # al menos una cita verificada contra el contenido real
    with Session(engine) as s:
        citas = repo.evidences_by_subfactor(s, ev.id)
        assert any(e.ruta_archivo != "[análisis estático]" for lst in citas.values() for e in lst)
