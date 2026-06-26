"""App FastAPI del Bolivia Exchange Rate Tracker.

Expone la informacion de cotizaciones cargada por el ETL. La documentacion
interactiva se genera automaticamente en /docs (Swagger) y /redoc.
"""

import logging
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI

from src.api import services
from src.api.database import close_pool
from src.api.routers import rates
from src.api.schemas import HealthOut, RootOut

logger = logging.getLogger(__name__)

# En local lee .env (subiendo desde src/api/); en prod las vars vienen del entorno.
load_dotenv()

API_VERSION = "0.1.0"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Ciclo de vida: cierra el pool de conexiones al apagar."""
    yield
    close_pool()


app = FastAPI(
    title="Bolivia Exchange Rate Tracker API",
    description=(
        "API REST publica con las cotizaciones del dolar en Bolivia "
        "(oficial y binance/paralelo) y la brecha cambiaria."
    ),
    version=API_VERSION,
    lifespan=lifespan,
)

app.include_router(rates.rates_router)
app.include_router(rates.stats_router)


@app.get("/", response_model=RootOut, tags=["meta"])
def root() -> RootOut:
    """Informacion basica del servicio y link a la documentacion."""
    return RootOut(
        name="Bolivia Exchange Rate Tracker API",
        version=API_VERSION,
        docs="/docs",
    )


@app.get("/health", response_model=HealthOut, tags=["meta"])
def health() -> HealthOut:
    """Estado del API y de la conexion a la base de datos."""
    db_ok = services.check_db()
    return HealthOut(status="ok", db="up" if db_ok else "down")
