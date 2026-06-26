"""Capa de servicios: acceso a datos y logica de negocio del API.

Los routers delegan aqui toda la logica; no contienen SQL ni reglas. Cada
funcion abre un cursor via ``get_cursor`` y retorna dicts (o listas de dicts)
listos para que FastAPI los valide contra los modelos de respuesta.

Todas las queries usan parametros enlazados (nunca interpolacion de strings) y
se restringen al esquema ``fx`` por el search_path del cursor.
"""

import logging
from datetime import date

from src.api.database import get_cursor

logger = logging.getLogger(__name__)

# Columnas expuestas en las respuestas de cotizacion.
_RATE_COLS = "fecha, casa, compra, venta, brecha_pct, fecha_actualizacion"


def check_db() -> bool:
    """Verifica la conectividad a la base de datos.

    Returns:
        True si un ``SELECT 1`` responde; False si la conexion falla.
    """
    try:
        with get_cursor() as cur:
            cur.execute("SELECT 1 AS ok;")
            cur.fetchone()
        return True
    except Exception:
        logger.exception("Health check de DB fallo.")
        return False


def get_latest_all() -> list[dict]:
    """Ultima cotizacion de cada casa.

    Returns:
        Lista con la fila mas reciente por casa.
    """
    with get_cursor() as cur:
        cur.execute(
            f"""
            SELECT DISTINCT ON (casa) {_RATE_COLS}
            FROM fx.exchange_rates
            ORDER BY casa, fecha DESC, fecha_actualizacion DESC;
            """
        )
        return cur.fetchall()


def get_latest_by_casa(casa: str) -> dict | None:
    """Ultima cotizacion de una casa especifica.

    Args:
        casa: "oficial" o "binance".

    Returns:
        La fila mas reciente, o None si no hay datos para esa casa.
    """
    with get_cursor() as cur:
        cur.execute(
            f"""
            SELECT {_RATE_COLS}
            FROM fx.exchange_rates
            WHERE casa = %s
            ORDER BY fecha DESC, fecha_actualizacion DESC
            LIMIT 1;
            """,
            (casa,),
        )
        return cur.fetchone()


def get_history(
    casa: str,
    desde: date | None = None,
    hasta: date | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """Historico de cotizaciones de una casa, con filtros y paginacion.

    Args:
        casa: "oficial" o "binance".
        desde: Fecha minima inclusive (opcional).
        hasta: Fecha maxima inclusive (opcional).
        limit: Numero maximo de filas a retornar.
        offset: Numero de filas a saltar (paginacion).

    Returns:
        Lista de cotizaciones ordenadas por fecha descendente.
    """
    clauses = ["casa = %s"]
    params: list = [casa]
    if desde is not None:
        clauses.append("fecha >= %s")
        params.append(desde)
    if hasta is not None:
        clauses.append("fecha <= %s")
        params.append(hasta)

    where = " AND ".join(clauses)
    params.extend([limit, offset])

    with get_cursor() as cur:
        cur.execute(
            f"""
            SELECT {_RATE_COLS}
            FROM fx.exchange_rates
            WHERE {where}
            ORDER BY fecha DESC, fecha_actualizacion DESC
            LIMIT %s OFFSET %s;
            """,
            params,
        )
        return cur.fetchall()


def get_brecha_series(dias: int = 30) -> list[dict]:
    """Serie temporal de la brecha cambiaria (casa binance).

    Args:
        dias: Ventana hacia atras desde hoy.

    Returns:
        Lista de puntos {fecha, brecha_pct} ordenados por fecha ascendente.
    """
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT fecha, brecha_pct
            FROM fx.exchange_rates
            WHERE casa = 'binance'
              AND brecha_pct IS NOT NULL
              AND fecha >= (CURRENT_DATE - %s::int)
            ORDER BY fecha ASC;
            """,
            (dias,),
        )
        return cur.fetchall()


def get_stats_summary(dias: int = 30) -> dict:
    """Min, max, promedio y numero de muestras de la brecha en N dias.

    Args:
        dias: Ventana hacia atras desde hoy.

    Returns:
        Dict con claves dias, min, max, promedio, muestras.
    """
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT
                MIN(brecha_pct)            AS min,
                MAX(brecha_pct)            AS max,
                ROUND(AVG(brecha_pct), 2)  AS promedio,
                COUNT(*)                   AS muestras
            FROM fx.exchange_rates
            WHERE casa = 'binance'
              AND brecha_pct IS NOT NULL
              AND fecha >= (CURRENT_DATE - %s::int);
            """,
            (dias,),
        )
        row = cur.fetchone() or {}
    return {"dias": dias, **row}
