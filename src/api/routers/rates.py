"""Endpoints de cotizaciones (/rates/*) y estadisticas (/stats/*).

Los handlers son delgados: validan/parametrizan la peticion y delegan toda la
logica a ``src.api.services``. Se importa el modulo completo (no las funciones
sueltas) para facilitar el mockeo en tests.
"""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from src.api import services
from src.api.schemas import BrechaPoint, Casa, HistoryPage, RateOut, StatsSummary

rates_router = APIRouter(prefix="/rates", tags=["rates"])
stats_router = APIRouter(prefix="/stats", tags=["stats"])


@rates_router.get("/latest", response_model=list[RateOut])
def latest_all() -> list[dict]:
    """Ultima cotizacion de cada casa (oficial y binance)."""
    return services.get_latest_all()


@rates_router.get("/latest/{casa}", response_model=RateOut)
def latest_by_casa(casa: Casa) -> dict:
    """Ultima cotizacion de una casa especifica."""
    row = services.get_latest_by_casa(casa.value)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Sin datos para casa '{casa.value}'.")
    return row


@rates_router.get("/history", response_model=HistoryPage)
def history(
    casa: Casa,
    desde: Annotated[date | None, Query(description="Fecha minima inclusive.")] = None,
    hasta: Annotated[date | None, Query(description="Fecha maxima inclusive.")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> HistoryPage:
    """Historico paginado de una casa, con filtros opcionales de fecha."""
    items = services.get_history(casa.value, desde, hasta, limit, offset)
    return HistoryPage(
        casa=casa.value,
        limit=limit,
        offset=offset,
        count=len(items),
        items=items,
    )


@rates_router.get("/brecha", response_model=list[BrechaPoint])
def brecha(dias: Annotated[int, Query(ge=1, le=365)] = 30) -> list[dict]:
    """Serie temporal de la brecha cambiaria de los ultimos N dias."""
    return services.get_brecha_series(dias)


@stats_router.get("/summary", response_model=StatsSummary)
def stats_summary(dias: Annotated[int, Query(ge=1, le=365)] = 30) -> dict:
    """Min, max y promedio de la brecha en los ultimos N dias."""
    return services.get_stats_summary(dias)
