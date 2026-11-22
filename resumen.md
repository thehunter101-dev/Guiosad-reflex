# Resumen general de módulos — GUIOSPRO_FLOSS (GUIOSAD)

Plataforma web para evaluar la adopción de soluciones FLOSS con la metodología **GUIOS / GUIOS PRO**.
Combina un **núcleo matemático determinista**, **IA generativa** (RAG + Google Gemini) y **control humano**
(*Human-in-the-Loop*). Si la IA no está disponible o falla, la app sigue funcionando en **modo manual**.

**Stack:** Reflex 0.11 (Python full-stack) · PostgreSQL 16 + pgvector · SQLModel/SQLAlchemy · Alembic ·
google-genai · httpx · PyMuPDF · GitPython · bcrypt · itsdangerous.

---

## 1. Arquitectura por capas

```
guiospro/
├── core/        Dominio puro (sin Reflex, IA, BD ni red): reglas y fórmulas GUIOS
├── models/      Persistencia: tablas SQLModel + pgvector, repositorio, seed, sesiones
├── services/    Infraestructura: auth, ingesta/RAG, licencias, Gemini, literatura
├── state/       Estados reactivos de Reflex (lógica de la UI)
├── pages/       Pantallas (login, dashboard, wizard, calibración, catálogo)
├── components/  Componentes de UI reutilizables
├── data/        Catálogo base en CSV (factores y subfactores)
├── settings.py  Configuración desde .env
└── guiospro.py  Punto de entrada y rutas
alembic/         Migraciones (esquema inicial con 14 tablas + índice HNSW)
tests/           Pruebas (SQLite + clientes IA simulados; integración opcional con Gemini real)
```

Dependencias permitidas: `pages → state → services/models → core`. El `core` no importa nada externo
(lo verifica `tests/test_core.py::test_core_is_pure_python`).

---

## 2. Punto de entrada y configuración

| Archivo | Función |
|---|---|
| `guiospro/guiospro.py` | Crea `rx.App()` y registra las rutas: `/login`, `/registro`, `/` (dashboard), `/evaluacion`, `/calibracion` (admin), `/catalogo` (admin), cada una con sus `on_load` de control de acceso y carga. |
| `guiospro/settings.py` | `Settings` (pydantic-settings) leído de `.env`: BD, auth, modelos Gemini (`gemini-3.8-flash`, `gemini-3.5-flash-lite`, `gemini-embedding-2` a 768 dim), límites de cuota, parámetros de ingesta/RAG y de calibración bibliográfica. `ai_enabled` indica si hay clave de Gemini. |
| `rxconfig.py` | Configuración de Reflex (URL de BD). |
| `docker-compose.yml` + `docker/initdb/` | PostgreSQL 16 con pgvector y extensiones iniciales. |

---

## 3. `core/` — Dominio GUIOS (Python puro)

| Módulo | Contenido |
|---|---|
| `constants.py` | Escalas 1–4 de **importancia** (Irrelevante → Fundamental) y **cumplimiento** (No cumple → Cumple). **Matriz cartesiana** `M(y, x)` de doble uso. Umbrales: `IE_FIJO = 3`, `UMBRAL_FODA = 3.0`, `UMBRAL_CONFIANZA_IA = 0.45`, `SCORE_DESCONOZCO = 2`. Enumeraciones: `Alcance`, `Foda`, `Dictamen` (A/B/C con textos), `Rol` (admin/decisor/evaluador), `ModoEvaluacion`, `EstadoEvaluacion`, `CategoriaChunk`. |
| `calibration.py` | Calibración bibliográfica: `r_i = c_i / n_i` (citas pertinentes / subfactores activos), **cuartiles** Q1–Q3 → `IL` (1–4), e `IS = M(IE=3, IL)`. |
| `evaluator.py` | Núcleo de evaluación: `IR = M(ID, IS)`; filtro de relevancia `IR > 1`; ponderación media `PM_i`; clasificación **FODA** (PM ≥ 3 → Fortaleza/Oportunidad según alcance interno/externo; si no, Debilidad/Amenaza); **dictamen base**: **A** sin negativos, **B** negativos solo con IR = 2, **C** algún negativo con IR ≥ 3 o más negativos que positivos. `apply_ai_fallback`: sin citas o confianza < 0.45 → puntaje 2 y revisión prioritaria. |
| `schemas.py` | Contratos Pydantic de entrada/salida del núcleo (`EvaluacionInput`, `ResultadoEvaluacion`, calibración) y de los servicios IA (`SubfactorAISuggestion`, `CitationItem`, `VerdictRequest/Response`, `PlanAccionItem`). |
| `catalog.py` | Lee el catálogo base desde `data/factors.csv` y `data/subfactors.csv` (TSV): **3 dimensiones, 18 factores, 61 subfactores**, con cadena de búsqueda bibliográfica y guía de verificación. Solo se usa para el seed. |

---

## 4. `models/` — Persistencia

| Módulo | Contenido |
|---|---|
| `database.py` | Modelo relacional + vectorial (14 tablas): `Usuario`, `Dimension`, `Factor`, `Subfactor`, `CalibracionLiteratura`, `ArticuloLiteratura`, `FactorCalibracion`, `Evaluacion`, `EvaluacionParticipante`, `EvaluacionFactor`, `EvaluacionSubfactor`, `DocumentoChunk` (con embedding), `EvidenciaTecnica`, `RecomendacionEjecutiva`. `EmbeddingType` = `vector(768)` en PostgreSQL y JSON en SQLite (pruebas). Enumeraciones como texto con `CHECK`. |
| `repository.py` | **Única capa de acceso a datos.** Catálogo (listar/guardar/borrar), usuarios (el primero es admin), evaluaciones (crear, permisos por rol, participantes, ID del decisor, alcance, puntajes y observaciones, `recompute` que ejecuta el núcleo y persiste IR/PM/FODA/dictamen, finalizar/reabrir/borrar), chunks RAG (reemplazo, embeddings pendientes, `search_chunks` por coseno con pgvector o en memoria), propuestas IA, recomendaciones ejecutivas y calibraciones (`apply_calibration` actualiza la IS vigente). |
| `session.py` | Motor SQLAlchemy y `session_scope()` transaccional. |
| `seed.py` | `python -m guiospro.models.seed`: carga el catálogo (idempotente) y un admin opcional (`ADMIN_EMAIL`/`ADMIN_PASSWORD`). |

---

## 5. `services/` — Infraestructura e IA

| Módulo | Contenido |
|---|---|
| `auth.py` | Hash de contraseñas con **bcrypt** y tokens de sesión firmados con **itsdangerous**. |
| `ai_client.py` | Cliente Gemini: `generate_json` / `agenerate_json` con *Structured Outputs* y `embed`. **Limitador de tokens por minuto** compartido (ventana de 60 s), reintentos en 429 respetando `retryDelay` (no reintenta cuotas diarias > 2 min) y en 5xx con *backoff* exponencial. Todo fallo definitivo → `AIUnavailable` (dispara el modo manual). |
| `repo_ingestor.py` | Ingesta técnica: clona Git (GitHub/GitLab, URL validada) o extrae ZIP de forma segura (anti zip-slip, symlinks y bombas), lee PDF/MD/CSV, hace **análisis estático** (licencias, manifiestos, CI, Docker, pruebas), categoriza y divide en fragmentos con rango de líneas. Excluye carpetas de terceros, limita fragmentos de código (reparto *round-robin*) y por archivo, prioriza docs/config/licencias. Embeddings por lotes reanudables (`embed_pending_chunks`). Directorio temporal siempre eliminado. |
| `licenses.py` | Detección determinista de licencias: identificadores SPDX en texto, manifiestos, cabeceras y convención REUSE (`LICENSES/<SPDX>.txt`); clasificación por tipo (permisiva, copyleft, etc.). |
| `sanitizer.py` | Defensa contra **prompt injection**: limpia el texto no confiable y lo envuelve en delimitadores que no se pueden cerrar desde el contenido. |
| `subfactor_ai.py` | **Pre-evaluación RAG** de subfactores activos de factores relevantes: recupera fragmentos, pide a Gemini puntaje + citas, **verifica que cada cita exista literalmente** en el fragmento, descarta las inventadas y aplica el fallback del núcleo. Persiste propuestas y evidencias. |
| `verdict_ai.py` | **Dictamen ejecutivo y plan de mitigación FODA.** El LLM redacta pero **no decide**: el dictamen base siempre es el del núcleo y el plan solo cubre Debilidades/Amenazas reales. `manual_verdict` genera una versión determinista sin IA. |
| `literature_ai.py` | **Calibración bibliográfica 2020–2025:** busca por factor en OpenAlex, Crossref y Semantic Scholar, deduplica, clasifica pertinencia con Gemini (lotes), guarda artículos, calcula `c_i, n_i, r_i, IL, IS` y marca la calibración como vigente. Tolera fallos de fuentes individuales. |

---

## 6. `state/` — Lógica reactiva de la UI (Reflex)

| Módulo | Contenido |
|---|---|
| `auth_state.py` | Sesión, login, registro, logout; guardas `require_login`, `require_admin`, `redirect_if_logged`; `is_admin`. |
| `dashboard_state.py` | «Mis evaluaciones»: listado, creación y borrado. |
| `evaluation_state.py` | **Wizard de 6 pasos** con autoguardado: contexto IA (subidas, repositorio, ingesta, pre-evaluación en segundo plano), ID y alcance (decisor), puntajes y observaciones (evaluador), filtros (Todos / Pendientes / Baja confianza), aceptar todas las propuestas IA, progreso, FODA, dictamen, finalizar/reabrir, equipo. Permisos por rol. Conmuta a modo manual ante fallos. |
| `calibration_state.py` | Panel de calibración: historial de ejecuciones, filas por factor, artículos, ejecución en vivo. |
| `catalog_state.py` | CRUD de dimensiones, factores y subfactores con activación/desactivación y validación. |
| `tasks.py` | `run_with_progress`: ejecuta tareas largas (síncronas en hilo) como eventos *background* con mensajes de progreso. |
| `models.py` | Filas serializables para la UI (`FactorRow`, `SubfactorCard`, `EvidenceRow`, `SummaryRow`, `PlanRow`, `CalibrationRow`, etc.). |

---

## 7. `pages/` y `components/` — Interfaz

| Módulo | Pantalla / componente |
|---|---|
| `pages/auth.py` | Login y registro. |
| `pages/dashboard.py` | Lista de evaluaciones y diálogo de alta. |
| `pages/evaluation.py` | Wizard en pestañas: **Contexto** (repo/documentos, panel de tareas), **Pasos 1-2** (ID, IS, IR, alcance de *Soporte*), **Pasos 3-4** (tarjetas de subfactor con propuesta IA, evidencias citadas y decisión humana), **Pasos 5-6** (resumen, FODA, dictamen y plan), **Equipo**. |
| `pages/calibration.py` | Panel de calibración bibliográfica (solo admin). |
| `pages/catalog.py` | Gestor del catálogo con diálogos de edición (solo admin). |
| `components/layout.py` | Cabecera con navegación y menú de usuario, `page_shell` protegido, `auth_shell`, tablas desplazables. |
| `components/badges.py` | Insignias de color para importancia, cumplimiento, FODA y dictamen. |
| `components/level_select.py` | Selector de escala 1–4. |

---

## 8. Flujo de una evaluación

1. **Contexto (opcional):** repo y/o documentos → análisis estático → fragmentos en pgvector → pre-evaluación Gemini con citas verificables.
2. **Pasos 1-2:** el decisor asigna **ID**; con la **IS** calibrada se calcula `IR = M(ID, IS)`; los factores con IR = 1 se excluyen.
3. **Pasos 3-4:** el evaluador revisa cada subfactor (propuesta IA + evidencia) y fija el puntaje final.
4. **Pasos 5-6:** `PM_i` → FODA → dictamen **A/B/C**; Gemini redacta el resumen ejecutivo y el plan de mitigación sin contradecir el dictamen.

**Roles:** *admin* (catálogo y calibración), *decisor* (ID y alcance), *evaluador* (puntajes).

---

## 9. Pruebas (`tests/`)

| Archivo | Cobertura |
|---|---|
| `test_core.py` | Pureza del core, catálogo 3/18/61, matriz cartesiana, cuartiles e IL, PM/FODA, reglas de dictamen, fallback IA. |
| `test_repository.py` | Seed idempotente, primer usuario admin, flujo manual completo, exclusión por IR, permisos, borrado en cascada, propuestas IA, búsqueda vectorial, calibración. |
| `test_services.py` | Sanitizer, licencias, validación de URLs, ZIP seguro, ingesta, verificación de citas, prefill, dictamen, literatura, límites de ingesta, reanudación de embeddings. |
| `test_ai_client.py` | Embeddings contra un SDK simulado, limitador de tasa, reintentos 429/5xx. |
| `test_state_flow.py` | Recorrido de la UI llamando a los manejadores reales de Reflex (auth, wizard, roles, CRUD del catálogo). |
| `test_integration_gemini.py` | Contra la API real (se activa con `GEMINI_INTEGRATION=1`). |
| `fakes.py` / `conftest.py` | Cliente IA falso y fixtures (SQLite en memoria). |

---

## 10. Puesta en marcha rápida

```bash
pip install -r requirements-dev.txt
cp .env.example .env
docker compose up -d
alembic upgrade head
python -m guiospro.models.seed
reflex run            # http://localhost:3000
python -m pytest      # pruebas sin red ni PostgreSQL
```
