"""Carga idempotente de cotizaciones a PostgreSQL (esquema fx).

Usa conexion directa con psycopg2 (no supabase-py) y hace UPSERT sobre
``fx.exchange_rates`` con ``ON CONFLICT (fecha, casa)``, de modo que correr el
ETL varias veces el mismo dia actualiza la fila en vez de duplicarla.

Ademas expone ``fetch_huecos``, la consulta de continuidad que el pipeline usa
para verificar que la serie historica no tenga dias sin cotizacion.

La connection string se lee de ``DATABASE_URL`` (nunca hardcodeada).
"""

import logging
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import date

import psycopg2
from psycopg2.extensions import connection as PgConnection
from psycopg2.extras import execute_batch

from src.db import SEARCH_PATH_SQL, get_database_url
from src.models.schemas import CleanQuote

logger = logging.getLogger(__name__)

# UPSERT idempotente. La tabla se califica con el esquema fx explicitamente,
# ademas del search_path que se setea al abrir la conexion.
_UPSERT_SQL = """
    INSERT INTO fx.exchange_rates
        (fecha, casa, compra, venta, brecha_pct, fecha_actualizacion, imputado)
    VALUES
        (%(fecha)s, %(casa)s, %(compra)s, %(venta)s, %(brecha_pct)s,
         %(fecha_actualizacion)s, %(imputado)s)
    ON CONFLICT (fecha, casa) DO UPDATE SET
        compra              = EXCLUDED.compra,
        venta               = EXCLUDED.venta,
        brecha_pct          = EXCLUDED.brecha_pct,
        fecha_actualizacion = EXCLUDED.fecha_actualizacion,
        imputado            = EXCLUDED.imputado;
"""

# Dias sin cotizacion dentro de la ventana vigilada, por casa.
#
# El rango va desde `hoy - dias` (acotado por el primer dia con datos, para no
# reportar dias anteriores al inicio de la serie) hasta el ultimo dia cargado
# (no hasta hoy: el ETL corre a las 23:00 UTC y esta consulta se ejecuta justo
# despues del load, asi que el ultimo dia cargado ya es el dia en curso).
_HUECOS_SQL = """
    WITH rango AS (
        SELECT
            GREATEST(CURRENT_DATE - %(dias)s::int, MIN(fecha)) AS desde,
            MAX(fecha)                                         AS hasta
        FROM fx.exchange_rates
    ),
    esperado AS (
        SELECT dia::date AS fecha, casa
        FROM rango r
        CROSS JOIN LATERAL generate_series(r.desde, r.hasta, INTERVAL '1 day') AS dia
        CROSS JOIN unnest(%(casas)s::text[]) AS casa
    )
    SELECT e.fecha, e.casa
    FROM esperado e
    WHERE NOT EXISTS (
        SELECT 1
        FROM fx.exchange_rates r
        WHERE r.fecha = e.fecha
          AND r.casa = e.casa
    )
    ORDER BY e.fecha, e.casa;
"""


def get_connection() -> PgConnection:
    """Abre una conexion a PostgreSQL usando DATABASE_URL.

    Setea ``search_path`` a ``fx, public`` para que las queries no necesiten
    calificar el esquema, aunque el DML critico igual lo califica.

    Returns:
        Conexion psycopg2 abierta.

    Raises:
        KeyError: Si la variable de entorno DATABASE_URL no esta definida.
    """
    conn = psycopg2.connect(get_database_url())
    with conn.cursor() as cur:
        cur.execute(SEARCH_PATH_SQL)
    return conn


@contextmanager
def _managed_connection(conn: PgConnection | None) -> Iterator[PgConnection]:
    """Cede una conexion, cerrandola solo si la abrio esta funcion.

    Las funciones publicas del modulo aceptan una conexion opcional para poder
    encadenar operaciones en una misma transaccion (y para los tests). La regla
    es que quien abre, cierra: una conexion prestada se devuelve intacta.

    Args:
        conn: Conexion prestada, o None para abrir una propia.

    Yields:
        La conexion a usar.
    """
    if conn is not None:
        yield conn
        return

    propia = get_connection()
    try:
        yield propia
    finally:
        propia.close()


def upsert_quotes(quotes: list[CleanQuote], conn: PgConnection | None = None) -> int:
    """Hace UPSERT de una lista de cotizaciones limpias.

    Si no se pasa ``conn``, abre (y cierra) una propia. La operacion es
    transaccional: hace commit al final o rollback si algo falla.

    Args:
        quotes: Cotizaciones validadas a cargar.
        conn: Conexion existente reutilizable (opcional). Si es None, se crea
            una nueva y se cierra al terminar.

    Returns:
        Numero de filas procesadas (insertadas o actualizadas).
    """
    if not quotes:
        logger.info("No hay cotizaciones para cargar.")
        return 0

    rows = [q.model_dump() for q in quotes]
    with _managed_connection(conn) as cx:
        try:
            with cx.cursor() as cur:
                execute_batch(cur, _UPSERT_SQL, rows)
            cx.commit()
            logger.info("UPSERT de %d cotizaciones en fx.exchange_rates.", len(rows))
            return len(rows)
        except Exception:
            cx.rollback()
            logger.exception("Fallo el UPSERT; se hizo rollback.")
            raise


def fetch_huecos(
    dias: int,
    casas: Sequence[str],
    conn: PgConnection | None = None,
) -> list[tuple[date, str]]:
    """Busca dias sin cotizacion en los ultimos N dias de la serie.

    Complementa la verificacion de completitud de la corrida diaria: esa mira
    solo el pull de hoy, esta mira la serie ya persistida. Cubre el caso en que
    una corrida termina "exitosa" pero no deja fila nueva (p. ej. un UPSERT que
    pisa una fila existente porque la fuente repitio la fecha), que fue
    exactamente el mecanismo del hueco de julio 2026.

    Args:
        dias: Tamano de la ventana hacia atras desde hoy.
        casas: Casas que deben existir cada dia.
        conn: Conexion existente reutilizable (opcional). Si es None, se crea
            una nueva y se cierra al terminar.

    Returns:
        Lista de tuplas ``(fecha, casa)`` faltantes, ordenada por fecha. Vacia
        si la serie es continua.
    """
    with _managed_connection(conn) as cx, cx.cursor() as cur:
        cur.execute(_HUECOS_SQL, {"dias": dias, "casas": list(casas)})
        return cur.fetchall()
