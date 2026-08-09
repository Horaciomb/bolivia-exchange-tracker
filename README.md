# 🇧🇴 Bolivia Exchange Rate Tracker

[![CI](https://github.com/Horaciomb/bolivia-exchange-tracker/actions/workflows/ci.yml/badge.svg)](https://github.com/Horaciomb/bolivia-exchange-tracker/actions/workflows/ci.yml)
[![ETL diario](https://github.com/Horaciomb/bolivia-exchange-tracker/actions/workflows/etl-daily.yml/badge.svg)](https://github.com/Horaciomb/bolivia-exchange-tracker/actions/workflows/etl-daily.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![Ruff](https://img.shields.io/badge/lint-ruff-261230.svg)](https://github.com/astral-sh/ruff)
[![FastAPI](https://img.shields.io/badge/API-FastAPI-009688.svg)](https://fastapi.tiangolo.com/)
[![API en vivo](https://img.shields.io/badge/API-en%20vivo-brightgreen.svg)](https://bolivia-exchange-tracker-api.onrender.com/docs)
[![License: MIT](https://img.shields.io/badge/license-MIT-yellow.svg)](LICENSE)

Pipeline **ETL** que extrae diariamente las cotizaciones del dólar en Bolivia
(oficial y paralelo/Binance), las almacena en **PostgreSQL**, calcula la **brecha
cambiaria** y las expone mediante una **API REST** pública documentada con Swagger.

Proyecto de portafolio de **Ingeniería de Datos**: el énfasis está en la calidad
del código, los tests y la documentación — no solo en que "funcione".

## 🔗 Demo en vivo

- **API:** <https://bolivia-exchange-tracker-api.onrender.com>
- **Documentación (Swagger):** <https://bolivia-exchange-tracker-api.onrender.com/docs>
- Ejemplos: [`/rates/latest`](https://bolivia-exchange-tracker-api.onrender.com/rates/latest) ·
  [`/rates/brecha?dias=30`](https://bolivia-exchange-tracker-api.onrender.com/rates/brecha?dias=30) ·
  [`/stats/summary`](https://bolivia-exchange-tracker-api.onrender.com/stats/summary)

> Alojada en Render (plan free): el primer request tras inactividad puede tardar ~50s.

---

## 🏗️ Arquitectura

```mermaid
flowchart LR
    A[DolarApi Bolivia<br/>API publica] -->|extract| B[extract.py<br/>requests + reintentos]
    B --> C[transform.py<br/>brecha + validacion]
    C -->|UPSERT idempotente| D[(PostgreSQL<br/>esquema fx)]
    D --> E[FastAPI<br/>API REST]
    E --> F[Clientes / Swagger /docs]
    G[GitHub Actions<br/>cron diario 23:00 UTC] -. dispara .-> B
```

El flujo `extract → transform → load` está orquestado por
[`src/etl/pipeline.py`](src/etl/pipeline.py) y se ejecuta a diario vía GitHub
Actions. La API ([`src/api/`](src/api/)) lee de la misma base de datos.

---

## 🧰 Stack tecnológico

| Capa | Tecnología |
|------|-----------|
| Lenguaje | Python 3.11+ |
| ETL | `requests` + reintentos con backoff |
| Validación | `pydantic` v2 |
| Base de datos | PostgreSQL (Supabase), esquema dedicado `fx` |
| Acceso a DB | `psycopg2` (conexión directa, SQL explícito) |
| API | `FastAPI` + `uvicorn` |
| Tests | `pytest` (con mocks, sin DB/red) |
| Lint | `ruff` |
| Orquestación | GitHub Actions (cron) |
| Deploy API | Render.com (free tier) |

---

## 📊 Fuente de datos

API pública **[DolarApi Bolivia](https://bo.dolarapi.com)** — gratuita, sin token:

| Endpoint | Descripción |
|----------|-------------|
| `GET /v1/dolares/oficial` | Cotización oficial (compra/venta) |
| `GET /v1/dolares/binance` | Cotización paralelo/Binance (compra/venta) |
| `GET /v1/estado` | Estado de la fuente (health) |

---

## 🗄️ Modelo de datos

El proyecto vive en un esquema dedicado **`fx`** dentro de una instancia
PostgreSQL compartida (no requiere un proyecto Supabase nuevo). Tabla
`fx.exchange_rates`:

| Columna | Tipo | Notas |
|---------|------|-------|
| `id` | bigint | PK, `GENERATED ALWAYS AS IDENTITY` |
| `fecha` | date | Fecha de la cotización (hora Bolivia, UTC-4) |
| `casa` | text | `'oficial'` o `'binance'` |
| `compra` | numeric(10,4) | Precio de compra |
| `venta` | numeric(10,4) | Precio de venta |
| `brecha_pct` | numeric(6,2) | Solo binance: `%` sobre el oficial |
| `fecha_actualizacion` | timestamptz | Timestamp original de la fuente |
| `imputado` | boolean | `true` si la fila es estimada (backfill), no real |
| `created_at` | timestamptz | `default now()` |

**Idempotencia:** `UNIQUE (fecha, casa)` + UPSERT (`ON CONFLICT`), de modo que
correr el ETL varias veces el mismo día actualiza la fila en lugar de duplicarla.

**Integridad de datos (`imputado`):** DolarApi solo expone la cotización actual
(sin histórico), así que un día perdido no se puede volver a pedir. Toda fila que
no provenga de una extracción directa se marca `imputado = true` para distinguirla
del dato observado. El pipeline diario siempre carga `imputado = false`, y el API
expone el flag en cada cotización. Ver [Calidad de datos](#-calidad-de-datos).

La **brecha cambiaria** se calcula como:

```
brecha_pct = ((binance.venta - oficial.venta) / oficial.venta) * 100
```

---

## 🔍 Calidad de datos

Un pipeline que corre solo sirve de poco si nadie se entera cuando falla a medias.
Esta sección documenta un incidente real del proyecto, cómo se corrigió y qué
controles quedaron para que no se repita en silencio.

### El incidente (julio 2026)

Tras el cambio de régimen cambiario del 29-jun, la fuente **cambió el formato del
payload** de la casa `oficial`: dejó de mandar un timestamp real y pasó a codificar
solo la fecha, como medianoche UTC.

```jsonc
// binance: timestamp intradía real
"fechaActualizacion": "2026-07-27T21:01:09.629Z"
// oficial: la fecha, codificada como medianoche UTC
"fechaActualizacion": "2026-07-27T00:00:00.000Z"
```

El `transform` normalizaba ese valor a hora Bolivia (UTC-4) — correcto para un
timestamp intradía, destructivo sobre una medianoche UTC: le restaba 4 horas y lo
retrocedía al día anterior. Esto produjo dos daños distintos:

| Efecto | Alcance | Causa |
|--------|---------|-------|
| Fechas corridas un día | 18 filas `oficial` | La conversión de TZ sobre una fecha sin hora |
| Días sin cotización | 10 días `oficial` | El UPSERT pisaba la fila existente en vez de crear una nueva |

Nada de esto rompió el pipeline: las Actions siguieron en verde todo el tiempo.

### Diagnóstico y corrección

El desfase se detectó porque `brecha_pct` — calculada correctamente en el momento
del pull — **no se reproducía** con un `JOIN` por fecha, pero sí contra el oficial
del día anterior. El fix vive en
[`transform.py::derivar_fecha`](src/etl/transform.py), que distingue los dos
formatos, y la reparación de los datos ya cargados en
[`sql/migrations/`](sql/migrations/).

Los 10 días perdidos **no requirieron una fuente externa ni interpolación**: la
serie `binance` estaba completa y conservaba su brecha, y la fórmula es invertible.

```
brecha_pct = ((binance.venta - oficial.venta) / oficial.venta) * 100
     =>  oficial.venta = binance.venta / (1 + brecha_pct / 100)
```

El valor oficial nunca se perdió: estaba codificado dentro de la brecha. Validado
contra los 35 días que sí tenían ambas casas, la inversión reproduce
`oficial.venta` con un **error máximo de 0.0006 Bs** (redondeo de `brecha_pct` a
2 decimales). Como `compra` no participa en la fórmula y se derivó del spread del
último día conocido, las filas quedan marcadas `imputado = true`.

### Controles automáticos

El pipeline corre dos verificaciones después de cargar. Cualquiera de las dos
termina con **exit code 1** y pone la Action en rojo, aunque la carga haya
funcionado:

| Control | Qué verifica | Qué atrapa |
|---------|--------------|------------|
| **Completitud de la corrida** | Que el pull de hoy traiga todas las casas esperadas | La fuente caída o una fila descartada por los sanity checks |
| **Continuidad de la serie** | Que no falte ningún día en los últimos 30, consultando la tabla | Una corrida "exitosa" que no dejó fila nueva — el mecanismo exacto del incidente |

El segundo control es el que faltaba: la completitud mira el pull, no el resultado
persistido. Ambos se cargan siempre *después* del `load`, de modo que una casa
caída nunca hace perder la otra.

> Las filas imputadas se cuentan como presentes: reparar un hueco con un backfill
> documentado (`imputado = true`) es lo que devuelve la Action a verde.

---

## 🌐 Endpoints de la API

| Método | Ruta | Descripción |
|--------|------|-------------|
| `GET` | `/` | Info del servicio + link a `/docs` |
| `GET` | `/health` | Estado del API y conexión a la DB |
| `GET` | `/rates/latest` | Última cotización de cada casa |
| `GET` | `/rates/latest/{casa}` | Última de una casa (`oficial`/`binance`) |
| `GET` | `/rates/history?casa=&desde=&hasta=&limit=&offset=` | Histórico paginado |
| `GET` | `/rates/brecha?dias=30` | Serie temporal de la brecha |
| `GET` | `/stats/summary?dias=30` | Min, max y promedio de la brecha |

La documentación interactiva (Swagger) se genera automáticamente en **`/docs`**
y ReDoc en **`/redoc`**.

---

## 📁 Estructura del repositorio

```
bolivia-exchange-tracker/
├── .github/workflows/
│   ├── ci.yml               # ruff + pytest en cada push/PR
│   └── etl-daily.yml        # cron diario del ETL
├── src/
│   ├── etl/
│   │   ├── extract.py       # llama a DolarApi (reintentos + backoff)
│   │   ├── transform.py     # valida, calcula brecha, normaliza fecha
│   │   ├── load.py          # UPSERT idempotente + chequeo de continuidad
│   │   └── pipeline.py      # orquestador extract→transform→load + alertas
│   ├── models/
│   │   └── schemas.py       # modelos pydantic del ETL (RawQuote, CleanQuote)
│   └── api/
│       ├── main.py          # app FastAPI (/, /health)
│       ├── database.py      # pool psycopg2 + search_path fx
│       ├── services.py      # capa de servicios (queries + lógica)
│       ├── schemas.py       # modelos de respuesta + enum Casa
│       └── routers/
│           └── rates.py     # endpoints /rates/* y /stats/*
├── tests/                   # pytest (extract, transform, load, api) — con mocks
├── sql/
│   ├── schema.sql           # DDL del esquema fx y la tabla
│   └── migrations/          # correcciones de datos, con contexto y verificación
├── .env.example
├── requirements.txt
├── pyproject.toml           # config de ruff y pytest
└── README.md
```

---

## 🚀 Puesta en marcha

### 1. Clonar e instalar

```bash
git clone https://github.com/Horaciomb/bolivia-exchange-tracker.git
cd bolivia-exchange-tracker

python -m venv venv
# Windows
venv\Scripts\activate
# Linux/Mac
source venv/bin/activate

pip install -r requirements.txt
```

### 2. Configurar variables de entorno

```bash
cp .env.example .env
```

Edita `.env` y completa tu connection string directa de PostgreSQL:

```
DATABASE_URL=postgresql://USER:PASSWORD@HOST:PORT/DBNAME
DOLARAPI_BASE_URL=https://bo.dolarapi.com
```

> ⚠️ `.env` está en `.gitignore` — nunca se commitea.

### 3. Crear el esquema y la tabla

Ejecuta el DDL una sola vez contra tu base de datos:

```bash
psql "$DATABASE_URL" -f sql/schema.sql
```

Esto crea el esquema `fx` y la tabla `fx.exchange_rates` (idempotente:
`CREATE ... IF NOT EXISTS`).

---

## ▶️ Uso

### Correr el pipeline ETL (una vez)

```bash
python -m src.etl.pipeline
```

Extrae las cotizaciones, calcula la brecha y hace UPSERT en `fx.exchange_rates`.

### Levantar la API

```bash
uvicorn src.api.main:app --reload
```

- API: <http://127.0.0.1:8000>
- Swagger: <http://127.0.0.1:8000/docs>

---

## ✅ Tests y linting

```bash
ruff check .           # lint
pytest -q              # tests (usan mocks; no requieren DB ni red)
pytest -q --cov=src    # tests + cobertura (umbral 90%, actual 99%)
```

La suite cubre el cálculo de brecha, la validación de reglas de negocio, el
manejo de timezone (incluidos los dos formatos de fecha de la fuente), la
política de reintentos del extract, el UPSERT y el chequeo de continuidad del
load, las dos alertas de calidad de datos, el SQL de la capa de servicios y cada
endpoint de la API.

---

## 🔄 CI/CD (GitHub Actions)

| Workflow | Disparador | Qué hace |
|----------|-----------|----------|
| **CI** | push a `main`/`dev`, PR a `main` | `ruff check` + `pytest` con umbral de cobertura |
| **ETL diario** | cron `0 23 * * *` (UTC) + manual | corre el pipeline y falla si la carga quedó incompleta |

El ETL requiere el secret **`DATABASE_URL`** configurado en
*Settings → Secrets and variables → Actions*.

> ⚠️ **IPv4 / pooler:** la conexión **directa** de Supabase
> (`db.<ref>.supabase.co:5432`) resuelve solo a **IPv6**, y los runners de GitHub
> Actions **no tienen salida IPv6** (fallan con `Network is unreachable`). En el
> secret usa el string del **pooler (Supavisor, IPv4)**: *Dashboard → Project
> Settings → Database → Connection string → "Session pooler"*
> (`postgres.<ref>@aws-0-<region>.pooler.supabase.com:5432`).

---

## 📦 Deploy de la API (Render)

El repo incluye un **Blueprint** ([`render.yaml`](render.yaml)) que define el
servicio como código (build, start, health check, Python 3.11).

1. En [Render](https://render.com): **New + → Blueprint** y conectar este repo.
   Render lee `render.yaml` y crea el *Web Service* (plan free).
2. Configurar la única variable secreta `DATABASE_URL` con el string del
   **pooler IPv4** de Supabase (igual que en CI: Render tampoco hace IPv6).
3. Deploy. La API queda en `https://<servicio>.onrender.com` y la doc en `/docs`.

> Build: `pip install -r requirements.txt` · Start:
> `uvicorn src.api.main:app --host 0.0.0.0 --port $PORT` · Health check: `/health`.
> Nota: en el plan free el servicio se duerme tras inactividad (primer request lento).

---

## 📄 Licencia

Distribuido bajo licencia **MIT**. Ver [LICENSE](LICENSE) para el texto completo.
