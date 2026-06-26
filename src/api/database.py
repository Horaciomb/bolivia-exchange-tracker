"""Gestion de la conexion a PostgreSQL para el API.

Usa un pool de conexiones psycopg2 inicializado de forma perezosa (lazy): el
pool solo se crea la primera vez que se necesita una conexion real. Asi, los
tests que mockean la capa de servicios pueden instanciar la app con TestClient
sin requerir una base de datos.

La connection string se lee de ``DATABASE_URL`` (nunca hardcodeada). Cada cursor
fija ``search_path`` a ``fx, public`` para no calificar el esquema en cada query.
"""

import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager

from psycopg2.extras import RealDictCursor
from psycopg2.pool import SimpleConnectionPool

logger = logging.getLogger(__name__)

_pool: SimpleConnectionPool | None = None


def _get_pool() -> SimpleConnectionPool:
    """Retorna el pool, creandolo en el primer uso.

    Raises:
        KeyError: Si DATABASE_URL no esta definida.
    """
    global _pool
    if _pool is None:
        db_url = os.environ.get("DATABASE_URL")
        if not db_url:
            raise KeyError("DATABASE_URL no esta definida.")
        logger.info("Inicializando pool de conexiones PostgreSQL.")
        _pool = SimpleConnectionPool(minconn=1, maxconn=5, dsn=db_url)
    return _pool


@contextmanager
def get_cursor() -> Iterator[RealDictCursor]:
    """Cede un cursor (RealDictCursor) dentro de una transaccion.

    Toma una conexion del pool, fija el search_path, cede el cursor y hace
    commit al salir (o rollback ante excepcion). La conexion siempre se devuelve
    al pool.

    Yields:
        Cursor que retorna filas como dicts.
    """
    pool = _get_pool()
    conn = pool.getconn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SET search_path TO fx, public;")
            yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)


def close_pool() -> None:
    """Cierra todas las conexiones del pool (al apagar el API)."""
    global _pool
    if _pool is not None:
        logger.info("Cerrando pool de conexiones.")
        _pool.closeall()
        _pool = None
