# GUIOSPRO_FLOSS — GUIOSAD

Plataforma web para evaluar la adopción de soluciones FLOSS con la metodología
**GUIOS / GUIOS PRO**, combinando un núcleo matemático determinista con IA generativa
(RAG + Gemini) y control humano (*Human-in-the-Loop*). Construida con
[Reflex](https://reflex.dev) (Python full-stack), PostgreSQL 16 + pgvector y Google AI.

## Requisitos

- Python 3.11+
- PostgreSQL 16 con la extensión `pgvector` (incluido en `docker-compose.yml`)
- Opcional: clave de Google AI (`GEMINI_API_KEY`). Sin ella la app funciona en modo manual.

## Puesta en marcha

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt

cp .env.example .env          # completar claves; .env no se versiona
docker compose up -d          # PostgreSQL 16 + pgvector (crea también guiosad_test)

alembic upgrade head          # crea las 14 tablas, la extensión vector y el índice HNSW
python -m guiospro.models.seed  # carga el catálogo GUIOS (3 dimensiones, 18 factores, 61 subfactores)

reflex run                    # http://localhost:3000
```

El primer usuario que se registra queda como **administrador** (o defina
`ADMIN_EMAIL` / `ADMIN_PASSWORD` antes del seed).

Pruebas (no requieren PostgreSQL ni red; usan SQLite y clientes simulados):

```bash
python -m pytest
```

Pruebas contra la API real de Google AI (consumen cuota; usan `GEMINI_API_KEY` de `.env`):

```bash
GEMINI_INTEGRATION=1 python -m pytest tests/test_integration_gemini.py
```

## Arquitectura

```
guiospro/
├── core/       Dominio puro (sin reflex, google-genai, sqlmodel ni httpx)
│   ├── constants.py    Escalas, matriz cartesiana, umbrales y enumeraciones
│   ├── calibration.py  r_i = c_i/n_i, cuartiles → IL, IS = M(IE=3, IL)
│   ├── evaluator.py    IR = M(ID, IS), filtro IR > 1, PM_i, FODA, dictamen A/B/C, fallback IA
│   ├── schemas.py      Contratos Pydantic del núcleo y de los servicios IA
│   └── catalog.py      Lectura del catálogo base desde data/*.csv (seed)
├── models/     SQLModel + pgvector (database.py), repositorio y seed
├── services/   Autenticación, ingesta/RAG, Gemini (pre-evaluación, dictamen, calibración)
├── state/      Estados reactivos de Reflex
├── pages/      Login, registro, dashboard, wizard de evaluación, calibración, catálogo
└── components/ Componentes de UI compartidos
alembic/        Migraciones
```

## Flujo de evaluación

1. **Contexto (opcional).** Repositorio GitHub/GitLab y/o documentos (ZIP, PDF, MD, CSV).
   Se ejecuta un análisis estático determinista (licencias SPDX, manifiestos, CI, Docker,
   pruebas) y se indexan fragmentos en pgvector. Con IA disponible, Gemini pre-evalúa los
   subfactores de los factores relevantes citando archivo, ubicación y fragmento exacto.
   Sin citas verificables o con confianza < 0.45, el puntaje queda en **2 (Desconozco)** y
   se marca para revisión prioritaria.
2. **Pasos 1-2.** El decisor asigna ID; se muestra la IS calibrada y se calcula
   `IR = M(ID, IS)`. Los factores con IR = 1 se excluyen. Solo *Soporte* tiene alcance configurable.
3. **Pasos 3-4.** Vista continua de subfactores con guardado automático, barra de progreso y
   filtros (Todos / Pendientes-Desconozco / Baja confianza IA). El evaluador decide el puntaje final.
4. **Pasos 5-6.** FODA (umbral PM ≥ 3.0) y dictamen base:
   - **A** — sin Debilidades ni Amenazas.
   - **B** — Debilidades/Amenazas solo en factores con IR = 2 (Opcional).
   - **C** — alguna Debilidad/Amenaza con IR ≥ 3, o más factores negativos que positivos.

   El dictamen ejecutivo y el plan de mitigación los redacta Gemini sin poder contradecir el
   dictamen base; sin IA se genera una versión determinista.

Si la IA no está configurada o falla en cualquier punto, la evaluación pasa a **modo manual**
sin perder datos ni bloquear el flujo.

## Administración

- **Calibración bibliográfica:** busca literatura del periodo configurado (2020–2025) en
  OpenAlex, Crossref y Semantic Scholar, filtra la pertinencia con Gemini y recalcula IL e IS.
  Cada evaluación queda ligada a la calibración vigente al crearla.
- **Catálogo:** alta/edición/activación de dimensiones, factores (incluida la cadena de
  búsqueda) y subfactores (incluida la guía de verificación que orienta el RAG).

## Cuotas de Google AI y volumen de ingesta

- Los embeddings se envían a un ritmo controlado (`GEMINI_EMBED_TPM_LIMIT`, por defecto 800.000
  tokens/minuto, ~80 % del Tier 1). Si sube de tier, aumente el valor.
- Ante un error 429 se reintenta respetando el tiempo de espera que indica la API
  (`GEMINI_RATE_LIMIT_RETRIES`). Las cuotas diarias (esperas > 2 min) no se reintentan.
- Los embeddings se guardan lote a lote: si algo falla, «Reanudar embeddings y pre-evaluar»
  continúa desde donde quedó. Sin fragmentos con embedding, la pre-evaluación no se ejecuta.
- Para acotar el volumen se excluyen carpetas de terceros (`externals/`, `third_party/`,
  `3rdparty/`, `deps/`…), se indexan como máximo `INGEST_MAX_CODE_CHUNKS` fragmentos de código
  repartidos entre archivos, y cada archivo de documentación/configuración aporta como máximo
  `INGEST_MAX_CHUNKS_PER_FILE` fragmentos. La documentación, configuración y licencias se
  procesan antes que el código.

## Modelos de Google AI

Configurables en `.env`: `gemini-3.8-flash` (pre-evaluación y dictamen),
`gemini-3.5-flash-lite` (pertinencia bibliográfica) y `gemini-embedding-2` a 768 dimensiones.
