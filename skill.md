## name: guiosad-architect-developer
description: Guía maestra de arquitectura, dominio matemático GUIOS, base de datos PostgreSQL + pgvector, integración Google AI (Gemini) y desarrollo full-stack en Reflex para el sistema GUIOSAD (Evaluación de Software Open Source Asistida por IA).

# GUIOSAD — Especificación Técnica y Reglas de Implementación para Agentes de Código

## 1. Propósito y Contexto del Sistema

**GUIOSAD** evoluciona la metodología doctoral **GUIOS / GUIOS PRO** (*Guía para la Selección de Software Open Source*) hacia una plataforma web híbrida (determinista + IA generativa/RAG) construida íntegramente en **Python con Reflex**.

El sistema resuelve simultáneamente:

1. **Calibración Bibliográfica Dinámica con IA (2020–2025):** Recolección, filtrado de pertinencia y conteo automatizado de producción científica por factor para calcular la *Importancia de la Literatura* ($IL$) y la *Importancia Sugerida* ($IS$) en vivo.

2. **Núcleo Matemático Determinista Inmutable:** Cálculo exacto de *Importancia Relativa* ($IR$), filtrado ($IR > 1$), *Ponderación Media* ($PM_i$), clasificación matricial **FODA** y dictamen base (**Tipo A, B o C**).

3. **Pre-evaluación Técnica Asistida (RAG + Gemini):** Ingesta de repositorios (GitHub/GitLab/ZIP) y documentación (PDF/MD/CSV) para prellenar subfactores con citas verificables de código/archivos y nivel de confianza.

4. **Control Híbrido (*Human-in-the-Loop*) y Trazabilidad Multiusuario:** Autenticación, gestión del catálogo GUIOS sin tocar código, auditoría de evaluaciones y conmutación automática a modo 100 % manual cuando no existan artefactos o falle la capa de IA.

## 2. Stack Tecnológico Obligatorio

* **Framework Web Full-Stack:** `reflex` (Estado reactivo en `rx.State`, componentes tipados, sin JS/HTML suelto).

* **Lenguaje:** Python `3.11+` con tipado estricto (`pydantic` v2, `typing`).

* **Base de Datos Relacional y Vectorial:** PostgreSQL `16+` con extensión `pgvector`, ORM `sqlmodel` / `sqlalchemy` y migraciones con `alembic`.

* **SDK de IA Generativa y Embeddings:** `google-genai` (usar `gemini-2.5-flash` para extracción/calibración masiva y `gemini-2.5-pro` o `gemini-2.5-flash` con `response_schema` Pydantic y `temperature=0.0` para pre-evaluación y dictamen; `text-embedding-004` para vectores de 768 dimensiones).

* **Ingesta y Parsing Técnico:** `pypdf` / `pymupdf`, `gitpython`, `ast` / `tree-sitter` (análisis estático de repositorios y detección de licencias FLOSS).

* **Búsqueda Científica (Calibración 2020–2025):** Clientes HTTP asíncronos (`httpx`) contra APIs académicas abiertas (OpenAlex, Crossref, Semantic Scholar) combinados con validación semántica mediante Google AI.

## 3. Principio Arquitectónico Fundamental: Desacoplamiento Estricto

El repositorio debe dividirse en **4 capas aisladas**. **Está estrictamente prohibido mezclar lógica matemática con UI o llamadas a LLM:**

```
guiosad/
├── core/                   # DOMINIO PURO (Cero imports de reflex, google-genai, sqlmodel o httpx)
│   ├── constants.py        # Escalas, Matriz Cartesiana, catálogos base (3 dim, 18 fac, 61 sub)
│   ├── calibration.py      # Cálculo de ratios r_i = c_i/n_i, cuartiles IL y cruce IS
│   ├── evaluator.py        # Cálculo IR, filtro IR > 1, PM_i, FODA y dictamen base A/B/C
│   └── schemas.py          # Contratos Pydantic puros de entrada/salida del núcleo
├── models/                 # Persistencia PostgreSQL + SQLModel + pgvector
│   └── database.py
├── services/               # Capa de infraestructura e IA
│   ├── literature_ai.py    # Búsqueda 2020-2025, filtrado de pertinencia y persistencia IL/IS
│   ├── repo_ingestor.py    # Clonado/ZIP, análisis estático de licencias y chunking RAG
│   ├── subfactor_ai.py     # Prellenado estructurado (score_ia 1..4) con citas exactas
│   └── verdict_ai.py       # Redacción de dictamen ejecutivo y plan de mitigación FODA
├── state/                  # Estados reactivos de Reflex (rx.State)
│   ├── auth_state.py
│   ├── catalog_state.py
│   ├── calibration_state.py
│   └── evaluation_state.py
└── pages/                  # Vistas Reflex (Login, Dashboard, Calibración, Wizard 6 Pasos, Catálogo)

```

## 4. Especificación Matemática del Núcleo GUIOS (`core/`)

### 4.1. Escalas Oficiales

1. **Escala de Importancia (**$IE, IL, IS, ID, IR \in \{1, 2, 3, 4\}$**):**

   * `1`: Irrelevante

   * `2`: Opcional

   * `3`: Importante

   * `4`: Fundamental

2. **Escala de Cumplimiento de Subfactor (**$PS \in \{1, 2, 3, 4\}$**):**

   * `1`: No cumple el requisito

   * `2`: Desconozco si cumple el requisito *(Valor por defecto cuando la IA no halla evidencia suficiente)*

   * `3`: Cumple parcialmente el requisito

   * `4`: Cumple el requisito

### 4.2. Cálculo de Importancia de la Literatura ($IL$) e Importancia Sugerida ($IS$)

* **Importancia del Experto (**$IE$**):** Fija en **`3` (`Importante`)** para los 18 factores (consenso de 57 expertos de la tesis).

* **Conteo Bibliográfico (**$c_i$**):** Número de artículos pertinentes sobre adopción de software recuperados en el rango **`2020–2025`** para el factor $i$ usando su cadena booleana.

* **Normalización por Subfactores (**$r_i$**):**
  

  $$
  r_i = \frac{c_i}{n_i}
  $$

  
  donde $n_i$ es la cantidad de subfactores activos del factor $i$ (total 61 subfactores distribuidos en los 18 factores).

* **Asignación de Cuartiles (**$IL_i \in \{1, 2, 3, 4\}$**):**
  Ordenar el conjunto $\{r_1, r_2, \dots, r_{18}\}$ y dividir en 4 cuartiles ($Q_1, Q_2, Q_3, Q_4$):

  * $r_i \le Q_1 \implies IL_i = 1$

  * $Q_1 < r_i \le Q_2 \implies IL_i = 2$

  * $Q_2 < r_i \le Q_3 \implies IL_i = 3$

  * $r_i > Q_3 \implies IL_i = 4$

* **Importancia Sugerida (**$IS_i$**):** Se obtiene aplicando la Matriz Cartesiana $M(IE_i, IL_i)$.

### 4.3. Matriz Cartesiana de Doble Uso ($IS$ e $IR$)

Esta tabla determina tanto $IS = M(IE, IL)$ como $IR = M(ID, IS)$:

| Eje Y ($IE$ o $ID$) \\ Eje X ($IL$ o $IS$) | `1` (Irrelevante) | `2` (Opcional) | `3` (Importante) | `4` (Fundamental) | 
| ----- | ----- | ----- | ----- | ----- | 
| **`4` (Fundamental)** | `2` | `3` | `3` | **`4`** | 
| **`3` (Importante)** | `2` | `2` | **`3`** | **`3`** | 
| **`2` (Opcional)** | `1` | `2` | `2` | **`3`** | 
| **`1` (Irrelevante)** | `1` | `1` | `2` | `2` | 

```
CARTESIAN_MATRIX: dict[tuple[int, int], int] = {
    (4, 1): 2, (4, 2): 3, (4, 3): 3, (4, 4): 4,
    (3, 1): 2, (3, 2): 2, (3, 3): 3, (3, 4): 3,
    (2, 1): 1, (2, 2): 2, (2, 3): 2, (2, 4): 3,
    (1, 1): 1, (1, 2): 1, (1, 3): 2, (1, 4): 2,
}

```

### 4.4. Flujo de 6 Pasos, Regla FODA y Dictamen Base (`A / B / C`)

1. **Paso 1 — Definición de** $ID$ **y Alcance:**

   * El decisor ingresa $ID_i \in \{1..4\}$ para los 18 factores.

   * El núcleo calcula $IR_i = M(ID_i, IS_i)$.

   * **Regla de Alcance:** 17 factores poseen alcance inmutable (6 `Interno` y 11 `Externo`). Únicamente el factor **Soporte** permite al decisor elegir dinámicamente entre `Interno` (equipo propio) o `Externo` (comunidad/proveedores).

2. **Paso 2 — Filtrado de Relevancia:**

   * Todo factor con $IR_i = 1$ **(`Irrelevante`) se excluye** automáticamente.

   * Solo pasan a evaluación los factores con $IR_i > 1$.

3. **Paso 3 — Ponderación de Subfactores (**$PS_{ij}$**):**

   * Cada subfactor $j$ de un factor relevante recibe una puntuación $PS_{ij} \in \{1, 2, 3, 4\}$ (propuesta por IA con cita verificable o ingresada manualmente).

4. **Paso 4 — Ponderación Media (**$PM_i$**):**
   

   $$
   PM_i = \frac{1}{m_i} \sum_{j=1}^{m_i} PS_{ij} \quad \in [1.0, 4.0]
   $$

5. **Paso 5 — Clasificación FODA (Umbral de corte** $= 3.0$**):**
   

   $$
   \text{FODA}(PM_i, \text{Alcance}_i) = \begin{cases} \textbf{Fortaleza} & \text{si } PM_i \ge 3.0 \land \text{Alcance}_i = \text{Interno} \\ \textbf{Oportunidad} & \text{si } PM_i \ge 3.0 \land \text{Alcance}_i = \text{Externo} \\ \textbf{Debilidad} & \text{si } PM_i < 3.0 \land \text{Alcance}_i = \text{Interno} \\ \textbf{Amenaza} & \text{si } PM_i < 3.0 \land \text{Alcance}_i = \text{Externo} \end{cases}
   $$

6. **Paso 6 — Regla Determinista de Dictamen Base (`Tipo A`, `Tipo B`, `Tipo C`):**

   * **Tipo A (`ADOPTAR_SIN_OBSERVACIONES`):** Todos los factores relevantes ($IR_i > 1$) obtuvieron $PM_i \ge 3.0$ (cero *Debilidades* y cero *Amenazas*).

   * **Tipo B (`ADOPTAR_CON_MATICES`):** Existen *Debilidades* o *Amenazas* ($PM_i < 3.0$), **pero todas** pertenecen exclusivamente a factores cuya importancia relativa es `Opcional` ($IR_i = 2$).

   * **Tipo C (`ANALIZAR_O_POSPONER`):** Existe al menos una *Debilidad* o *Amenaza* en un factor `Importante` o `Fundamental` ($IR_i \ge 3$), **o** el total de factores negativos (*Debilidades* + *Amenazas*) supera al total de factores positivos (*Fortalezas* + *Oportunidades*).

## 5. Modelo de Datos Relacional y Vectorial (`models/database.py`)

Implementar las siguientes entidades con `SQLModel`:

 1. **`usuario`**: `id`, `nombre_completo`, `email` (único), `password_hash`, `rol` (`admin | decisor | evaluador`), `organizacion`, `activo`, `creado_en`.

 2. **`calibracion_literatura`**: `id`, `anio_inicio` (default `2020`), `anio_fin` (default `2025`), `usuario_id` (FK), `es_vigente` (bool), `fecha_ejecucion`, `observaciones`.

 3. **`articulo_literatura`**: `id`, `calibracion_id` (FK), `factor_id` (FK), `titulo`, `autores`, `anio_publicacion`, `fuente_indexada`, `doi_o_url`, `abstract`, `es_pertinente` (bool), `razon_pertinencia_ia`.

 4. **`factor_calibracion`**: `id`, `calibracion_id` (FK), `factor_id` (FK), `citas_pertinentes` ($c_i$), `subfactores_activos` ($n_i$), `ratio_normalizado` ($r_i$), `il_calculado` (1..4), `ie_fijo` (3), `is_calculado` (1..4).

 5. **`dimension`**: `id`, `codigo`, `nombre` (`Tecnológica`, `Organizacional`, `Económica`), `descripcion`, `activa`.

 6. **`factor`**: `id`, `dimension_id` (FK), `codigo`, `nombre`, `tipo_alcance` (`Interno | Externo | Configurable`), `cadena_busqueda`, `ie_base` (3), `is_vigente` (1..4), `activo`.

 7. **`subfactor`**: `id`, `factor_id` (FK), `codigo`, `afirmacion`, `guia_verificacion`, `subfactor_activo` (bool).

 8. **`evaluacion`**: `id`, `usuario_propietario_id` (FK), `calibracion_id` (FK), `nombre_software`, `version`, `url_repositorio`, `organizacion`, `modo` (`hibrido_ia | manual`), `estado` (`paso_1 | paso_2 | paso_3 | revision | finalizada`), `dictamen_base` (`A | B | C | None`), `creado_en`, `actualizado_en`.

 9. **`evaluacion_participante`**: `id`, `evaluacion_id` (FK), `usuario_id` (FK), `rol_participacion` (soporte para evaluaciones colaborativas/multiusuario).

10. **`evaluacion_factor`**: `id`, `evaluacion_id` (FK), `factor_id` (FK), `id_decisor` (1..4), `is_aplicado` (1..4), `ir_calculado` (1..4), `alcance_aplicado` (`Interno | Externo`), `es_relevante` (bool), `pm_calculado` (float), `clasificacion_foda` (`Fortaleza | Oportunidad | Debilidad | Amenaza | Excluido`).

11. **`evaluacion_subfactor`**: `id`, `evaluacion_factor_id` (FK), `subfactor_id` (FK), `score_ia` (int 1..4 nullable), `nivel_confianza` (float 0.0..1.0 nullable), `justificacion_ia` (text nullable), `score_evaluador` (int 1..4), `observacion_evaluador` (text nullable), `validado_por_humano` (bool).

12. **`documento_chunk`**: `id`, `evaluacion_id` (FK), `ruta_archivo`, `categoria` (`codigo | licencia | documentacion | configuracion`), `contenido_texto`, `embedding` (`Vector(768)`).

13. **`evidencia_tecnica`**: `id`, `evaluacion_subfactor_id` (FK), `ruta_archivo`, `ubicacion_exacta`, `fragmento_evidencia`.

14. **`recomendacion_ejecutiva`**: `id`, `evaluacion_id` (FK), `dictamen_base` (`A | B | C`), `resumen_ejecutivo`, `plan_accion_foda_json` (lista estructurada de mitigaciones para *Debilidades* y *Amenazas*), `modelo_utilizado`, `creado_en`.

## 6. Contratos de Servicios de IA (`services/`)

### 6.1. Calibración Bibliográfica IA (`services/literature_ai.py`)

* **RF-BIB-01 / RF-BIB-02:** Para cada uno de los 18 factores, ejecuta la búsqueda académica filtrada estrictamente por ventana **`2020–2025`**.

* Utiliza Gemini (`temperature=0.0`, `response_schema`) para clasificar cada artículo recuperado (`es_pertinente: bool`) verificando que trate sobre evaluación/adopción de software OSS respecto al factor específico.

* Persiste los artículos en `articulo_literatura` (caché auditable y reproducible ante cambios editoriales) e invoca `core.calibration` para actualizar `il_calculado` e `is_calculado`.

### 6.2. Ingesta Técnica y RAG (`services/repo_ingestor.py`)

* **RF-AUTO-01 / 02 / 03:** Soporta clonado temporal de repositorios Git, extracción de archivos `.zip` y carga de documentación (`.pdf`, `.md`, `.csv`, `LICENSE`, `package.json`, `pyproject.toml`, `Dockerfile`, etc.).

* Realiza análisis estático determinista de licencias FLOSS (identificando permisivas como MIT/Apache-2.0 vs. copyleft como GPL/AGPL) y almacena chunks vectorizados en `documento_chunk` (`pgvector`).

### 6.3. Pre-evaluación de Subfactores (`services/subfactor_ai.py`)

* **RF-AUTO-04 / 05 / 06:** Ejecuta consultas RAG únicamente para los subfactores activos pertenecientes a factores relevantes ($IR > 1$).

* Exige respuesta estructurada Pydantic:

  ```
  class SubfactorAISuggestion(BaseModel):
      subfactor_id: int
      score_ia: Literal[1, 2, 3, 4]
      nivel_confianza: float = Field(ge=0.0, le=1.0)
      justificacion: str
      citas: list[CitationItem]  # archivo, linea/seccion, fragmento exacto
  
  ```

* **Regla de Fallback Obligatoria:** Si `citas` está vacía o `nivel_confianza < 0.45`, el servicio **debe** asignar `score_ia = 2` (*"Desconozco si cumple el requisito"*) y marcar el subfactor para revisión prioritaria.

### 6.4. Dictamen Ejecutivo y Plan FODA (`services/verdict_ai.py`)

* **RF-AUTO-07 / 08:** Recibe el objeto ya calculado por `core.evaluator` (`dictamen_base` $\in \{A, B, C\}$, valores exactos de $IR$, $PM_i$, matriz FODA y evidencias validadas por el humano).

* **Prohibición:** El LLM **nunca** puede contradecir el `dictamen_base` calculado por `core/`. Su función es redactar la justificación ejecutiva contextualizada a la organización y generar acciones técnicas/organizacionales concretas para mitigar cada `Debilidad` y `Amenaza`.

## 7. Directrices de UI/UX y Control Híbrido en Reflex (`pages/` y `state/`)

1. **Optimización de Pasos 3 y 4 (Lección del Piloto UNEMI):**

   * En la validación original de GUIOS PRO, evaluar subfactores obligando a seleccionar factor por factor y guardar manualmente generaba fatiga de clics.

   * En Reflex, renderizar los subfactores relevantes agrupados por Dimensión y Factor en una vista continua con **guardado reactivo automático (`on_change`)** en `rx.State`, barra de progreso en vivo y filtros rápidos (`Todos`, `Pendientes / Desconozco (2)`, `Baja Confianza IA`).

2. **Transparencia *Human-in-the-Loop* (`RF-AUTO-09`):**

   * Cada tarjeta de subfactor muestra lado a lado: la afirmación del subfactor, el badge de `score_ia` + `nivel_confianza`, un visor desplegable con el fragmento exacto del archivo/código citado, y el selector editable `score_evaluador` (1–4) con campo de observación.

3. **Conmutación Transparente a Modo Manual (`RF-AUTO-10`):**

   * Si el usuario crea una evaluación sin subir repositorio ni documentos, o si la API de Google AI no está disponible/falla, el flujo opera automáticamente en modo `manual` permitiendo completar los 6 pasos tradicionales de GUIOS sin bloqueos.

4. **Módulo de Administración y Calibración en Vivo (`RF-AUTH-01 / 02`):**

   * Vistas protegidas por sesión (`Login` / `Registro`):

     * **Panel de Calibración Bibliográfica (2020–2025):** Botón para ejecutar/recalcular $IL$ e $IS$ en vivo, tabla comparativa ($c_i$, $n_i$, $r_i$, cuartil $IL$, $IE=3$, $IS$) y modal de auditoría con los artículos científicos recuperados por factor.

     * **Gestor de Catálogo GUIOS:** CRUD completo para Dimensiones, Factores (incluyendo edición de `cadena_busqueda`) y Subfactores (`subfactor_activo`).