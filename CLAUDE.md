# CLAUDE.md — Bolivia Exchange Rate Tracker

## Propósito del proyecto

Pipeline ETL que extrae diariamente las cotizaciones del dólar en Bolivia
(oficial y paralelo/Binance), las almacena en PostgreSQL (Supabase), calcula
la brecha cambiaria, y expone los datos vía una API REST pública documentada.

Este es un proyecto de portafolio para demostrar competencias de Ingeniería de
Datos: extracción desde API, transformación con Python, carga incremental a
PostgreSQL, orquestación con GitHub Actions (cron) y publicación de un API con
FastAPI. El énfasis está en la **calidad del código, los tests y la documentación**,
no solo en que "funcione".

## Stack tecnológico (NO cambiar sin justificación)

- **Lenguaje:** Python 3.11+
- **ETL:** requests + pandas
- **Base de datos:** PostgreSQL en Supabase (cliente: supabase-py o psycopg2)
- **API:** FastAPI + uvicorn
- **Validación:** pydantic v2
- **Tests:** pytest
- **Orquestación:** GitHub Actions (cron diario)
- **Deploy API:** Render.com (free tier)
- **Gestión de entorno:** python-dotenv para local, variables de entorno en prod
- **Linting:** ruff

## Fuente de datos

API pública DolarApi Bolivia — gratuita, sin token, sin rate limit estricto:

- Base URL: `https://bo.dolarapi.com`
- `GET /v1/dolares/oficial` → cotización oficial (compra/venta)
- `GET /v1/dolares/binance` → cotización paralelo/Binance (compra/venta)
- `GET /v1/estado` → estado de la API (health check)

Formato de respuesta esperado (ejemplo oficial):
```json
{
  "moneda": "USD",
  "casa": "oficial",
  "nombre": "Oficial",
  "compra": 6.86,
  "venta": 6.96,
  "fechaActualizacion": "2026-06-25T14:00:00.000Z"
}
```

NOTA: confirmar los campos exactos haciendo un curl real a la API antes de
modelar el schema. No asumas el formato — valídalo.

## Arquitectura del repositorio

```
bolivia-exchange-tracker/
├── .github/workflows/
│   ├── etl-daily.yml        # cron diario que corre el ETL
│   └── ci.yml               # corre tests + ruff en cada push/PR
├── src/
│   ├── etl/
│   │   ├── __init__.py
│   │   ├── extract.py       # llama a DolarApi, retorna raw dict
│   │   ├── transform.py     # limpia, calcula brecha, valida con pydantic
│   │   ├── load.py          # upsert a Supabase (idempotente por fecha+casa)
│   │   └── pipeline.py      # orquesta extract→transform→load, entry point
│   ├── models/
│   │   └── schemas.py       # modelos pydantic (RawQuote, CleanQuote)
│   └── api/
│       ├── __init__.py
│       ├── main.py          # app FastAPI
│       ├── database.py      # conexión a Supabase/PG
│       └── routers/
│           └── rates.py     # endpoints /rates/*
├── tests/
│   ├── test_extract.py      # mock de la API
│   ├── test_transform.py    # casos de cálculo de brecha + validación
│   └── test_api.py          # TestClient de FastAPI
├── sql/
│   └── schema.sql           # DDL de la tabla exchange_rates
├── .env.example
├── requirements.txt
├── pyproject.toml           # config de ruff y pytest
├── README.md
└── CLAUDE.md
```

## Modelo de datos

Tabla `exchange_rates` en Supabase:

| Columna           | Tipo          | Notas                                   |
|-------------------|---------------|-----------------------------------------|
| id                | bigint        | PK, identity                            |
| fecha             | date          | fecha de la cotización                  |
| casa              | text          | 'oficial' o 'binance'                   |
| compra            | numeric(10,4) | precio compra                           |
| venta             | numeric(10,4) | precio venta                            |
| brecha_pct        | numeric(6,2)  | solo para binance: % sobre oficial      |
| fecha_actualizacion | timestamptz | timestamp original de la fuente         |
| created_at        | timestamptz   | default now()                           |

**Constraint de idempotencia:** UNIQUE(fecha, casa). El load hace UPSERT
(ON CONFLICT) para que correr el ETL dos veces el mismo día no duplique filas.

## Lógica de transformación

1. Parsear cada respuesta a un modelo pydantic `RawQuote` (valida tipos).
2. Normalizar la fecha a `date` (zona horaria Bolivia, UTC-4).
3. Para la cotización binance, calcular `brecha_pct`:
   `((binance.venta - oficial.venta) / oficial.venta) * 100`
4. Validar reglas de negocio: compra > 0, venta >= compra, venta < 100
   (sanity check — el dólar en Bolivia no llega a 100 Bs). Si falla, loggear
   warning y descartar esa fila, no romper el pipeline.
5. Retornar lista de `CleanQuote` lista para cargar.

## Endpoints del API a construir

- `GET /` → info básica + link a /docs
- `GET /health` → status del API y conexión a DB
- `GET /rates/latest` → última cotización de cada casa
- `GET /rates/latest/{casa}` → última de una casa específica
- `GET /rates/history?casa=binance&desde=2026-01-01&hasta=2026-06-01` → histórico
- `GET /rates/brecha?dias=30` → serie de brecha cambiaria de los últimos N días
- `GET /stats/summary` → min, max, promedio de la brecha en los últimos 30 días

Todos retornan JSON. Incluir paginación simple en /history (limit/offset).
FastAPI genera /docs (Swagger) automáticamente — asegurar que los modelos
de respuesta estén bien tipados con pydantic para que la doc se vea profesional.

## Convenciones de código

- Type hints en todas las funciones públicas.
- Docstrings estilo Google en módulos y funciones principales.
- Sin lógica de negocio en los routers — delegar a funciones de servicio.
- Manejo de errores explícito: la extracción debe reintentar 3 veces con
  backoff antes de fallar. Loggear con el módulo logging, no prints.
- Variables sensibles SOLO desde entorno. Nunca hardcodear la connection string.
- Commits en español o inglés, formato conventional commits (feat:, fix:, etc.)

## Tests requeridos (mínimo)

- `test_transform.py`: cálculo correcto de brecha, rechazo de venta<compra,
  rechazo de valores absurdos, manejo de fecha con timezone.
- `test_extract.py`: mockear requests, verificar reintentos en fallo.
- `test_api.py`: cada endpoint retorna 200 y el shape esperado (usar TestClient
  con una DB de prueba o mocks).

El CI debe correr `ruff check` y `pytest` — ambos deben pasar.

## Lo que NO debe hacer Claude Code

- NO crear las credenciales de Supabase ni el proyecto en Render — eso lo hace
  el usuario manualmente (ver pasos externos).
- NO commitear el archivo .env (debe estar en .gitignore).
- NO inventar el formato de la API — hacer un curl real primero y ajustar.
- NO sobre-ingenierizar: nada de Airflow, Kafka, ni Docker en esta fase. El
  scheduler es GitHub Actions y punto.

## Orden de implementación sugerido

1. Setup: requirements.txt, pyproject.toml, .gitignore, .env.example, estructura.
2. Hacer curl real a la API y confirmar el formato de respuesta.
3. sql/schema.sql con la tabla.
4. models/schemas.py (pydantic).
5. etl/extract.py + test.
6. etl/transform.py + test (incluye la lógica de brecha).
7. etl/load.py (upsert idempotente).
8. etl/pipeline.py (orquestador).
9. Correr el pipeline localmente contra Supabase y verificar que carga datos.
10. api/ completo con todos los endpoints.
11. tests/test_api.py.
12. .github/workflows/ci.yml y etl-daily.yml.
13. README.md con badges, descripción, diagrama de arquitectura, instrucciones.
