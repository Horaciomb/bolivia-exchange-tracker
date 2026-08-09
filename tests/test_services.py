"""Tests de la capa de servicios del API.

Los tests de test_api.py mockean estas funciones para probar los endpoints, asi
que el SQL que vive aqui no quedaba cubierto por nada. Estos tests mockean un
nivel mas abajo -- el cursor -- para verificar las queries y sus parametros sin
tocar PostgreSQL.
"""

from contextlib import contextmanager
from datetime import date
from unittest.mock import MagicMock

import pytest

from src.api import services

FILA = {
    "fecha": date(2026, 8, 9),
    "casa": "binance",
    "compra": 11.17,
    "venta": 11.22,
    "brecha_pct": -5.4,
    "fecha_actualizacion": None,
    "imputado": False,
}


@pytest.fixture
def cursor(monkeypatch):
    """Reemplaza get_cursor por uno que cede un cursor mock."""
    cur = MagicMock()

    @contextmanager
    def fake_get_cursor():
        yield cur

    monkeypatch.setattr(services, "get_cursor", fake_get_cursor)
    return cur


def _sql(cursor) -> str:
    """SQL de la ultima llamada, normalizado a una linea."""
    return " ".join(cursor.execute.call_args.args[0].split())


def _params(cursor):
    """Parametros enlazados de la ultima llamada."""
    args = cursor.execute.call_args.args
    return args[1] if len(args) > 1 else None


# --- check_db --------------------------------------------------------------


def test_check_db_ok(cursor):
    assert services.check_db() is True
    assert "SELECT 1" in _sql(cursor)


def test_check_db_devuelve_false_si_la_conexion_falla(monkeypatch):
    @contextmanager
    def cursor_roto():
        raise RuntimeError("db caida")
        yield  # pragma: no cover

    monkeypatch.setattr(services, "get_cursor", cursor_roto)

    # No propaga: /health debe poder reportar "down" en vez de dar 500.
    assert services.check_db() is False


# --- lecturas simples ------------------------------------------------------


def test_get_latest_all_una_fila_por_casa(cursor):
    cursor.fetchall.return_value = [FILA]

    assert services.get_latest_all() == [FILA]
    assert "DISTINCT ON (casa)" in _sql(cursor)


def test_get_latest_by_casa_filtra_por_casa(cursor):
    cursor.fetchone.return_value = FILA

    assert services.get_latest_by_casa("binance") == FILA
    assert _params(cursor) == ("binance",)
    assert "LIMIT 1" in _sql(cursor)


def test_get_latest_by_casa_sin_datos(cursor):
    cursor.fetchone.return_value = None
    assert services.get_latest_by_casa("oficial") is None


# --- historico: armado dinamico del WHERE ----------------------------------


def test_get_history_sin_filtros_de_fecha(cursor):
    cursor.fetchall.return_value = [FILA]

    services.get_history("binance", limit=10, offset=5)

    sql = _sql(cursor)
    assert "fecha >=" not in sql
    assert "fecha <=" not in sql
    # Orden de los parametros: casa, luego paginacion.
    assert _params(cursor) == ["binance", 10, 5]


def test_get_history_con_ambas_fechas(cursor):
    cursor.fetchall.return_value = []
    desde, hasta = date(2026, 7, 1), date(2026, 7, 31)

    services.get_history("oficial", desde=desde, hasta=hasta, limit=50, offset=0)

    sql = _sql(cursor)
    assert "fecha >= %s" in sql
    assert "fecha <= %s" in sql
    assert _params(cursor) == ["oficial", desde, hasta, 50, 0]


def test_get_history_solo_desde(cursor):
    cursor.fetchall.return_value = []
    desde = date(2026, 7, 1)

    services.get_history("binance", desde=desde)

    assert "fecha >= %s" in _sql(cursor)
    assert "fecha <= %s" not in _sql(cursor)
    assert _params(cursor) == ["binance", desde, 50, 0]


def test_get_history_nunca_interpola_la_casa_en_el_sql(cursor):
    """La casa va siempre como parametro enlazado, no dentro del string."""
    cursor.fetchall.return_value = []

    services.get_history("binance")

    assert "binance" not in _sql(cursor)
    assert "binance" in _params(cursor)


# --- brecha y estadisticas -------------------------------------------------


def test_get_brecha_series_pasa_la_ventana(cursor):
    cursor.fetchall.return_value = [{"fecha": date(2026, 8, 9), "brecha_pct": -5.4}]

    result = services.get_brecha_series(7)

    assert result[0]["brecha_pct"] == -5.4
    assert _params(cursor) == (7,)
    assert "ORDER BY fecha ASC" in _sql(cursor)


def test_get_stats_summary_agrega_los_dias_al_resultado(cursor):
    cursor.fetchone.return_value = {
        "min": -6.16,
        "max": 5.44,
        "promedio": -0.07,
        "muestras": 31,
    }

    result = services.get_stats_summary(30)

    assert result == {
        "dias": 30,
        "min": -6.16,
        "max": 5.44,
        "promedio": -0.07,
        "muestras": 31,
    }


def test_get_stats_summary_tolera_una_fila_vacia(cursor):
    cursor.fetchone.return_value = None
    assert services.get_stats_summary(30) == {"dias": 30}


def test_brecha_y_stats_miden_el_mismo_universo(cursor):
    """Ambos endpoints comparten el filtro; si divergen, describen series
    distintas."""
    cursor.fetchall.return_value = []
    services.get_brecha_series(30)
    sql_serie = _sql(cursor)

    cursor.fetchone.return_value = {}
    services.get_stats_summary(30)
    sql_stats = _sql(cursor)

    filtro = " ".join(services._BRECHA_EN_VENTANA.split())
    assert filtro in sql_serie
    assert filtro in sql_stats
