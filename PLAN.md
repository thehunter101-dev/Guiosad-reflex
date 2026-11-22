# GUIOSAD — Plan de implementación

Basado en `skill.md` (guiosad-architect-developer). Estado: **implementado (fases 0–9)** sobre el paquete `guiospro/` (sin renombrar). 65 pruebas automatizadas.

## Decisiones tomadas

| Tema | Decisión |
|---|---|
| Subfactores | **61** (40 Tecnológica, 19 Organizacional, 2 Económica). El CSV ya tiene 61; el conteo de 60 se debía a que la última línea no termina en salto de línea. |
| Cuartiles | `statistics.quantiles(r, n=4)` con su método por defecto (`exclusive`). No existía un método previo en el código, el manual ni el Excel. |
| Modelos Gemini | `gemini-3.8-flash` (estable) para pre-evaluación y dictamen; `gemini-3.5-flash-lite` (estable) para el filtrado masivo de artículos. |
| Embeddings | `gemini-embedding-2` a 768 dimensiones (no hay modelo de embeddings en la familia 3). |
| UI pasos 1–2 | Solo se muestra **IS** al decisor (IL/IE quedan en el panel de calibración del admin). |
| Configuración | Variables en `.env` (plantilla: `.env.example`); `.env` está en `.gitignore`. |
| Nombre del paquete | Se mantiene `guiospro/` (decisión del usuario). |

## Correcciones detectadas en el código actual

1. **Tipo C incompleto:** falta la condición «negativos > positivos» (`core/evaluation.py::recommend`).
2. **Tipo A prematuro:** el dictamen se calcula solo con factores evaluados; debe quedar *pendiente* mientras falte algún factor relevante.
3. **IS fija desde CSV:** debe salir de `M(IE=3, IL)` con la calibración vigente (la columna `Sugerida` queda como valor inicial).
4. **IR:** la media entera actual coincide con `CARTESIAN_MATRIX` en las 16 celdas; se sustituye por la tabla explícita (se reutiliza para IS).
5. **Pasos 3–4:** reemplazar «seleccionar factor + Guardar» por vista continua con autoguardado `on_change`, progreso y filtros.
6. **Alcance:** `Ambos` → `Configurable` (solo Soporte).

## Limpieza de datos en `subfactors.csv` (durante el seed)

- Línea 11: «fácilmente» usa un acento combinante (U+0301) → normalizar a NFC.
- Línea 13: «códigofuente» → «código fuente».
- Línea 30: «es una sistemas de administración de base de datos independiente» → «es independiente del sistema de administración de base de datos».
- Línea 62: «alternativa patentada» → «alternativa propietaria» (coherente con el resto).
- Añadir salto de línea final, columna `codigo` estable (p. ej. `TEC-COMP-01`) y columna `guia_verificacion`.
- `factors.csv`: añadir `codigo` y `cadena_busqueda` por factor.

## Fases

### Fase 0 — Reestructura y base
- Paquete `guiosad/` con `core/`, `models/`, `services/`, `state/`, `pages/` (componentes en `pages/components/`).
- `requirements.txt`: `reflex`, `pydantic>=2`, `pydantic-settings`, `sqlmodel`, `alembic`, `psycopg[binary]`, `pgvector`, `google-genai`, `httpx`, `pymupdf`, `gitpython`, `bcrypt`; dev: `pytest`, `pytest-asyncio`, `respx`.
- `guiosad/settings.py` (pydantic-settings) leyendo `.env`; `rxconfig.py` con `db_url`.
- `docker-compose.yml` con `pgvector/pgvector:pg16`.
- Test de arquitectura: `core/` no importa `reflex`, `google.genai`, `sqlmodel`, `httpx`.

### Fase 1 — Núcleo matemático (`core/`, Python puro)
- `constants.py`: escalas, `CARTESIAN_MATRIX`, `IE_FIJO=3`, `UMBRAL_FODA=3.0`, `UMBRAL_CONFIANZA_IA=0.45`, enums `Alcance`, `Foda`, `Dictamen` (A/B/C + códigos), `Rol`.
- `schemas.py` (Pydantic v2): `FactorInput`, `EvaluacionInput`, `FactorResultado`, `ResultadoEvaluacion`, `CalibracionInput/Resultado`, `SubfactorAISuggestion`, `CitationItem`, `VerdictRequest`, `VerdictResponse`.
- `calibration.py`: `r_i = c_i/n_i` (n_i = subfactores activos; n_i = 0 → error), cuartiles con `statistics.quantiles(n=4)`, IL por umbrales `≤Q1, ≤Q2, ≤Q3, >Q3`, `IS = M(3, IL)`.
- `evaluator.py`: `IR = M(ID, IS)`, filtro `IR > 1`, `PM_i`, FODA, dictamen A/B/C completo o *pendiente*.
- Tests: 16 celdas de la matriz, cuartiles con empates, todos los caminos A/B/C (incl. negativos > positivos), rango de PM.

### Fase 2 — Persistencia (`models/database.py`)
- 14 entidades SQLModel del §5 de `skill.md`, con FK, `CHECK` (1..4, 0..1), enums, `UNIQUE(email)`, `Vector(768)` + índice HNSW.
- Migración Alembic inicial (`CREATE EXTENSION vector`).
- Seed: CSV limpios → `dimension`/`factor`/`subfactor`; `is_vigente` inicial desde `Sugerida`; usuario admin desde `ADMIN_EMAIL`/`ADMIN_PASSWORD`.
- Repositorios de acceso a datos (el `state/` no arma consultas).

### Fase 3 — Autenticación y multiusuario
- `auth_state.py`: login/registro/logout, bcrypt, sesión firmada con `AUTH_SECRET_KEY`.
- Roles `admin | decisor | evaluador`, guardias por página.
- `evaluacion_participante` para evaluaciones colaborativas.

### Fase 4 — Wizard de 6 pasos sobre BD (modo manual completo)
*Al terminar, la app es usable sin IA.*
- Dashboard «Mis evaluaciones» y alta de evaluación (software, versión, repo opcional).
- Pasos 1–2: ID por factor, se muestra **solo IS**, IR calculada, alcance editable solo en Soporte, excluidos visibles.
- Pasos 3–4: vista continua por Dimensión/Factor, autoguardado `on_change`, barra de progreso, filtros (Todos / Pendientes-2 / Baja confianza).
- Pasos 5–6: matriz FODA, PM/IR, dictamen base, transición de `estado` hasta `finalizada`.

### Fase 5 — Ingesta y RAG (`services/repo_ingestor.py`)
- Git (clon superficial), ZIP (anti zip-slip, límites de `.env`), PDF, MD, CSV, manifiestos.
- Análisis estático determinista: licencias SPDX (permisiva vs copyleft), `package.json`, `pyproject.toml`, `Dockerfile`, CI.
- Chunking por categoría con ruta + línea/página; embeddings `gemini-embedding-2` (768, prefijos de tarea) → `documento_chunk`.
- Sanitización anti prompt-injection (contenido como datos, fuera de `system_instruction`); borrado de temporales con `try/finally`; evento en background con progreso.

### Fase 6 — Pre-evaluación IA (`services/subfactor_ai.py`)
- Solo subfactores activos de factores con `IR > 1`: top-k pgvector → `gemini-3.8-flash` con `response_schema=SubfactorAISuggestion`, `temperature=0`.
- **Fallback:** sin citas o confianza < 0.45 → `score_ia = 2` y revisión prioritaria.
- Verificar que cada cita exista en los chunks recuperados (anti alucinación).
- Persistir en `evaluacion_subfactor` + `evidencia_tecnica`; `score_evaluador` se precarga con `score_ia`.
- Tarjeta HITL: afirmación, badge score/confianza, visor desplegable de la cita, selector editable y observación.

### Fase 7 — Dictamen ejecutivo (`services/verdict_ai.py`)
- Entrada: `ResultadoEvaluacion` de `core/` + evidencias validadas; salida `VerdictResponse`.
- Guardia: si el LLM contradice `dictamen_base`, se rechaza/sobrescribe. Persistir con `modelo_utilizado`.

### Fase 8 — Calibración bibliográfica (`services/literature_ai.py`)
- Clientes `httpx` async (OpenAlex, Crossref, Semantic Scholar), ventana 2020–2025, `cadena_busqueda` por factor, dedupe por DOI, reintentos y rate-limit.
- Pertinencia con `gemini-3.5-flash-lite` → `articulo_literatura` → `core.calibration` → `factor_calibracion` → `factor.is_vigente`.
- Una calibración vigente; cada evaluación queda ligada a su calibración (reproducibilidad).
- Panel admin: recalcular, tabla `c_i, n_i, r_i, IL, IE, IS`, modal de artículos por factor.

### Fase 9 — Catálogo y cierre
- CRUD de dimensiones, factores (`cadena_busqueda`) y subfactores (`subfactor_activo`), solo admin.
- Resiliencia transversal: cualquier excepción de IA → `modo = manual` con aviso, sin romper `rx.State`.
- Tests con mocks (Gemini, APIs académicas), integración contra `TEST_DATABASE_URL`, README actualizado.

## Orden

`0 → 1 → 2 → 3 → 4` (app manual completa) → `5 → 6 → 7` (IA) → `8 → 9`. La fase 8 puede hacerse en paralelo con 5–7.

## Desviaciones respecto a `skill.md`

- `evaluacion_subfactor.score_evaluador` es nulo hasta que se puntúa (permite medir el progreso).
- Se añadieron `evaluacion_subfactor.revision_prioritaria`, `documento_chunk.ubicacion` y
  `factor.orden`/`subfactor.orden` para la revisión prioritaria, las citas y el orden en la UI.
- Las enumeraciones se guardan como texto con `CHECK` (no tipos ENUM de PostgreSQL).
- El resultado del análisis estático se guarda como un fragmento `[análisis estático]` para que
  también sea evidencia recuperable por el RAG.
