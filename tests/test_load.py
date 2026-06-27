"""Tests de load.py. No tocan PostgreSQL real: la conexion esta mockeada."""

from datetime import UTC, date, datetime
from unittest.mock import MagicMock

import pytest

from src.etl import load
from src.models.schemas import CleanQuote


def _quote(casa: str = "oficial", brecha=None, imputado: bool = False) -> CleanQuote:
    return CleanQuote(
        fecha=date(2026, 6, 25),
        casa=casa,
        compra=6.86,
        venta=6.96,
        brecha_pct=brecha,
        fecha_actualizacion=datetime(2026, 6, 25, 21, 1, tzinfo=UTC),
        imputado=imputado,
    )


def _mock_conn() -> MagicMock:
    """Conexion mock con cursor usable como context manager."""
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    return conn


def test_upsert_vacio_no_toca_db():
    conn = _mock_conn()
    result = load.upsert_quotes([], conn=conn)

    assert result == 0
    conn.cursor.assert_not_called()
    conn.commit.assert_not_called()


def test_upsert_hace_commit_y_devuelve_conteo(monkeypatch):
    mock_execute_batch = MagicMock()
    monkeypatch.setattr(load, "execute_batch", mock_execute_batch)
    conn = _mock_conn()

    quotes = [_quote("oficial"), _quote("binance", brecha=41.81)]
    result = load.upsert_quotes(quotes, conn=conn)

    assert result == 2
    conn.commit.assert_called_once()
    conn.rollback.assert_not_called()
    # No cierra una conexion que no creo el.
    conn.close.assert_not_called()

    # Verifica que el UPSERT recibio los dicts de las cotizaciones.
    args, _ = mock_execute_batch.call_args
    assert args[1] == load._UPSERT_SQL
    rows = args[2]
    assert {r["casa"] for r in rows} == {"oficial", "binance"}
    assert all("imputado" in r for r in rows)


def test_upsert_propaga_imputado(monkeypatch):
    mock_execute_batch = MagicMock()
    monkeypatch.setattr(load, "execute_batch", mock_execute_batch)
    conn = _mock_conn()

    load.upsert_quotes([_quote("binance", brecha=42.24, imputado=True)], conn=conn)

    rows = mock_execute_batch.call_args.args[2]
    assert rows[0]["imputado"] is True


def test_upsert_hace_rollback_y_propaga_en_error(monkeypatch):
    mock_execute_batch = MagicMock(side_effect=RuntimeError("db boom"))
    monkeypatch.setattr(load, "execute_batch", mock_execute_batch)
    conn = _mock_conn()

    with pytest.raises(RuntimeError):
        load.upsert_quotes([_quote()], conn=conn)

    conn.rollback.assert_called_once()
    conn.commit.assert_not_called()


def test_get_connection_sin_env_lanza(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(KeyError):
        load.get_connection()
