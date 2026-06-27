"""Carga idempotente de cotizaciones a PostgreSQL (esquema fx).

Usa conexion directa con psycopg2 (no supabase-py) y hace UPSERT sobre
``fx.exchange_rates`` con ``ON CONFLICT (fecha, casa)``, de modo que correr el
ETL varias veces el mismo dia actualiza la fila en vez de duplicarla.

La connection string se lee de ``DATABASE_URL`` (nunca hardcodeada).
"""

import logging
import os

import psycopg2
from psycopg2.extensions import connection as PgConnection
from psycopg2.extras import execute_batch

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


def get_connection() -> PgConnection:
    """Abre una conexion a PostgreSQL usando DATABASE_URL.

    Setea ``search_path`` a ``fx, public`` para que las queries no necesiten
    calificar el esquema, aunque el DML critico igual lo califica.

    Returns:
        Conexion psycopg2 abierta.

    Raises:
        KeyError: Si la variable de entorno DATABASE_URL no esta definida.
    """
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise KeyError(
            "DATABASE_URL no esta definida. Copia .env.example a .env "
            "y rellena la connection string."
        )
    conn = psycopg2.connect(db_url)
    with conn.cursor() as cur:
        cur.execute("SET search_path TO fx, public;")
    return conn


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

    own_conn = conn is None
    conn = conn or get_connection()

    rows = [q.model_dump() for q in quotes]
    try:
        with conn.cursor() as cur:
            execute_batch(cur, _UPSERT_SQL, rows)
        conn.commit()
        logger.info("UPSERT de %d cotizaciones en fx.exchange_rates.", len(rows))
        return len(rows)
    except Exception:
        conn.rollback()
        logger.exception("Fallo el UPSERT; se hizo rollback.")
        raise
    finally:
        if own_conn:
            conn.close()
