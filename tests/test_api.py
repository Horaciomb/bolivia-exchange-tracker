"""Tests de la API con TestClient. La capa de servicios esta mockeada: no se
abre ninguna conexion real a PostgreSQL."""

from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient

from src.api import services
from src.api.main import app

client = TestClient(app)

OFICIAL_ROW = {
    "fecha": date(2026, 6, 25),
    "casa": "oficial",
    "compra": 6.86,
    "venta": 6.96,
    "brecha_pct": None,
    "fecha_actualizacion": datetime(2026, 6, 25, 21, 1, 5),
    "imputado": False,
}
BINANCE_ROW = {
    "fecha": date(2026, 6, 25),
    "casa": "binance",
    "compra": 9.84,
    "venta": 9.87,
    "brecha_pct": 41.81,
    "fecha_actualizacion": datetime(2026, 6, 25, 21, 1, 6),
    "imputado": False,
}


def test_root():
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"]
    assert body["docs"] == "/docs"


def test_health_db_up(monkeypatch):
    monkeypatch.setattr(services, "check_db", lambda: True)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "db": "up"}


def test_health_db_down(monkeypatch):
    monkeypatch.setattr(services, "check_db", lambda: False)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["db"] == "down"


def test_latest_all(monkeypatch):
    monkeypatch.setattr(services, "get_latest_all", lambda: [OFICIAL_ROW, BINANCE_ROW])
    resp = client.get("/rates/latest")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 2
    assert {r["casa"] for r in body} == {"oficial", "binance"}


def test_latest_by_casa_ok(monkeypatch):
    monkeypatch.setattr(services, "get_latest_by_casa", lambda casa: BINANCE_ROW)
    resp = client.get("/rates/latest/binance")
    assert resp.status_code == 200
    body = resp.json()
    assert body["casa"] == "binance"
    assert body["brecha_pct"] == 41.81
    assert body["imputado"] is False


def test_latest_by_casa_404(monkeypatch):
    monkeypatch.setattr(services, "get_latest_by_casa", lambda casa: None)
    resp = client.get("/rates/latest/oficial")
    assert resp.status_code == 404


def test_latest_by_casa_invalida():
    # 'euro' no es un valor valido del enum Casa -> 422.
    resp = client.get("/rates/latest/euro")
    assert resp.status_code == 422


def test_history_paginado(monkeypatch):
    captured = {}

    def fake_history(casa, desde, hasta, limit, offset):
        captured.update(
            casa=casa, desde=desde, hasta=hasta, limit=limit, offset=offset
        )
        return [BINANCE_ROW]

    monkeypatch.setattr(services, "get_history", fake_history)
    resp = client.get(
        "/rates/history",
        params={"casa": "binance", "desde": "2026-06-01", "limit": 10, "offset": 5},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["casa"] == "binance"
    assert body["limit"] == 10
    assert body["offset"] == 5
    assert body["count"] == 1
    assert len(body["items"]) == 1
    # Verifica que los parametros llegaron a la capa de servicio.
    assert captured["casa"] == "binance"
    assert captured["desde"] == date(2026, 6, 1)


def test_history_requiere_casa():
    resp = client.get("/rates/history")
    assert resp.status_code == 422


def test_brecha_series(monkeypatch):
    serie = [
        {"fecha": date(2026, 6, 24), "brecha_pct": 40.0},
        {"fecha": date(2026, 6, 25), "brecha_pct": 41.81},
    ]
    monkeypatch.setattr(services, "get_brecha_series", lambda dias: serie)
    resp = client.get("/rates/brecha", params={"dias": 7})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 2
    assert body[1]["brecha_pct"] == 41.81


def test_brecha_dias_invalido():
    resp = client.get("/rates/brecha", params={"dias": 0})
    assert resp.status_code == 422


def test_stats_summary(monkeypatch):
    summary = {
        "dias": 30,
        "min": 38.0,
        "max": 45.0,
        "promedio": 41.5,
        "muestras": 30,
    }
    monkeypatch.setattr(services, "get_stats_summary", lambda dias: summary)
    resp = client.get("/stats/summary")
    assert resp.status_code == 200
    body = resp.json()
    assert body["promedio"] == 41.5
    assert body["muestras"] == 30


def test_stats_summary_sin_datos(monkeypatch):
    # Ventana sin muestras: min/max/promedio None, muestras 0.
    summary = {"dias": 30, "min": None, "max": None, "promedio": None, "muestras": 0}
    monkeypatch.setattr(services, "get_stats_summary", lambda dias: summary)
    resp = client.get("/stats/summary")
    assert resp.status_code == 200
    body = resp.json()
    assert body["muestras"] == 0
    assert body["promedio"] is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
