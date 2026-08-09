"""Tests del pool de conexiones del API. No abren PostgreSQL: el pool es mock.

Lo que se verifica aqui es el contrato del pool: que se cree una sola vez, que
cada cursor fije el search_path, y sobre todo que la conexion vuelva al pool
pase lo que pase -- una conexion que no se devuelve agota el pool y deja el API
colgado tras unas pocas peticiones fallidas.
"""

from unittest.mock import MagicMock

import pytest

from src.api import database


@pytest.fixture(autouse=True)
def _pool_limpio():
    """Resetea el singleton entre tests (es estado global del modulo)."""
    database._pool = None
    yield
    database._pool = None


@pytest.fixture
def pool_mock(monkeypatch):
    """Mockea SimpleConnectionPool y devuelve (pool, conn, cursor)."""
    cur = MagicMock()
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur

    pool = MagicMock()
    pool.getconn.return_value = conn

    fabrica = MagicMock(return_value=pool)
    monkeypatch.setattr(database, "SimpleConnectionPool", fabrica)
    monkeypatch.setenv("DATABASE_URL", "postgresql://test/db")
    return fabrica, pool, conn, cur


def test_pool_se_crea_una_sola_vez(pool_mock):
    fabrica, _, _, _ = pool_mock

    primero = database._get_pool()
    segundo = database._get_pool()

    assert primero is segundo
    fabrica.assert_called_once()


def test_pool_sin_database_url_lanza(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(KeyError):
        database._get_pool()


def test_cursor_fija_el_search_path(pool_mock):
    _, _, _, cur = pool_mock

    with database.get_cursor() as c:
        assert c is cur

    sql = cur.execute.call_args.args[0]
    assert "search_path" in sql
    assert "fx" in sql


def test_cursor_hace_commit_y_devuelve_la_conexion(pool_mock):
    _, pool, conn, _ = pool_mock

    with database.get_cursor():
        pass

    conn.commit.assert_called_once()
    conn.rollback.assert_not_called()
    pool.putconn.assert_called_once_with(conn)


def test_cursor_hace_rollback_y_propaga(pool_mock):
    _, pool, conn, _ = pool_mock

    with pytest.raises(RuntimeError):
        with database.get_cursor():
            raise RuntimeError("query rota")

    conn.rollback.assert_called_once()
    conn.commit.assert_not_called()
    # Aun fallando, la conexion vuelve al pool.
    pool.putconn.assert_called_once_with(conn)


def test_close_pool_cierra_y_resetea(pool_mock):
    _, pool, _, _ = pool_mock
    database._get_pool()

    database.close_pool()

    pool.closeall.assert_called_once()
    assert database._pool is None


def test_close_pool_sin_pool_es_inocuo():
    database.close_pool()  # no debe lanzar
    assert database._pool is None
