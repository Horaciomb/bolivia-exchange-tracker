"""Modelos de respuesta (pydantic) de la API.

Separados de ``src.models.schemas`` (que modela el ETL) para que el contrato
publico del API pueda evolucionar sin arrastrar el modelo de persistencia.
FastAPI los usa para generar la documentacion Swagger en /docs.

La excepcion es el enum ``Casa``: no es un detalle de presentacion sino
vocabulario del dominio, asi que vive en ``src.models.schemas`` y los routers lo
importan de ahi.
"""

from datetime import date, datetime

from pydantic import BaseModel, Field


class RateOut(BaseModel):
    """Una cotizacion tal como se expone en el API."""

    fecha: date
    casa: str
    compra: float
    venta: float
    brecha_pct: float | None = None
    fecha_actualizacion: datetime
    imputado: bool = False


class HistoryPage(BaseModel):
    """Pagina de resultados del histgrico (paginacion limit/offset)."""

    casa: str
    limit: int
    offset: int
    count: int = Field(description="Numero de items en esta pagina.")
    items: list[RateOut]


class BrechaPoint(BaseModel):
    """Un punto de la serie temporal de brecha cambiaria."""

    fecha: date
    brecha_pct: float


class StatsSummary(BaseModel):
    """Resumen estadistico de la brecha en una ventana de dias."""

    dias: int
    min: float | None = None
    max: float | None = None
    promedio: float | None = None
    muestras: int


class HealthOut(BaseModel):
    """Estado del API y de la conexion a la base de datos."""

    status: str
    db: str


class RootOut(BaseModel):
    """Informacion basica del servicio."""

    name: str
    version: str
    docs: str
