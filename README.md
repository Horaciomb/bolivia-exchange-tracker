# 🇧🇴 Bolivia Exchange Rate Tracker

[![CI](https://github.com/Horaciomb/bolivia-exchange-tracker/actions/workflows/ci.yml/badge.svg)](https://github.com/Horaciomb/bolivia-exchange-tracker/actions/workflows/ci.yml)
[![ETL diario](https://github.com/Horaciomb/bolivia-exchange-tracker/actions/workflows/etl-daily.yml/badge.svg)](https://github.com/Horaciomb/bolivia-exchange-tracker/actions/workflows/etl-daily.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![Ruff](https://img.shields.io/badge/lint-ruff-261230.svg)](https://github.com/astral-sh/ruff)
[![FastAPI](https://img.shields.io/badge/API-FastAPI-009688.svg)](https://fastapi.tiangolo.com/)

Pipeline **ETL** que extrae diariamente las cotizaciones del dólar en Bolivia
(oficial y paralelo/Binance), las almacena en **PostgreSQL**, calcula la **brecha
cambiaria** y las expone mediante una **API REST** pública documentada con Swagger.

Proyecto de portafolio de **Ingeniería de Datos**: el énfasis está en la calidad
del código, los tests y la documentación — no solo en que "funcione".

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
(sin histórico), así que un día perdido no se puede recuperar de la fuente. Si se
hace *backfill* de un hueco, la fila se inserta con `imputado = true` (estimada por
interpolación o carry-forward) para distinguirla de los datos reales. El pipeline
diario siempre carga `imputado = false`. El API expone este flag en cada cotización.

La **brecha cambiaria** se calcula como:

```
brecha_pct = ((binance.venta - oficial.venta) / oficial.venta) * 100
```

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
│   │   ├── load.py          # UPSERT idempotente a fx.exchange_rates
│   │   └── pipeline.py      # orquestador extract→transform→load
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
│   └── schema.sql           # DDL del esquema fx y la tabla
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
ruff check .     # lint
pytest -q        # tests (usan mocks; no requieren DB ni red)
```

La suite cubre el cálculo de brecha, la validación de reglas de negocio, el
manejo de timezone, los reintentos del extract, el UPSERT del load y cada
endpoint de la API.

---

## 🔄 CI/CD (GitHub Actions)

| Workflow | Disparador | Qué hace |
|----------|-----------|----------|
| **CI** | push a `main`/`dev`, PR a `main` | `ruff check` + `pytest` |
| **ETL diario** | cron `0 23 * * *` (UTC) + manual | corre el pipeline contra la DB |

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

1. Crear un *Web Service* en [Render](https://render.com) apuntando al repo.
2. **Build:** `pip install -r requirements.txt`
3. **Start:** `uvicorn src.api.main:app --host 0.0.0.0 --port $PORT`
4. Configurar `DATABASE_URL` con el string del **pooler IPv4** de Supabase
   (igual que en CI: Render tampoco hace IPv6 por defecto).

---

## 📄 Licencia

Distribuido bajo licencia MIT.
