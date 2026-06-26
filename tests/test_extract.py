"""Tests de extract.py. No tocan la red real: requests.get esta mockeado."""

from unittest.mock import MagicMock

import pytest
import requests

from src.etl import extract

OFICIAL_PAYLOAD = {
    "moneda": "USD",
    "casa": "oficial",
    "nombre": "Oficial",
    "compra": 6.86,
    "venta": 6.96,
    "fechaActualizacion": "2026-06-25T21:01:05.619Z",
}


def _ok_response(payload: dict) -> MagicMock:
    """Construye una respuesta mock con status 200 y JSON dado."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = payload
    resp.raise_for_status.return_value = None
    return resp


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """Anula el backoff para que los tests sean instantaneos."""
    monkeypatch.setattr(extract.time, "sleep", lambda _s: None)


def test_fetch_quote_parsea_payload(monkeypatch):
    mock_get = MagicMock(return_value=_ok_response(OFICIAL_PAYLOAD))
    monkeypatch.setattr(extract.requests, "get", mock_get)

    result = extract.fetch_quote("oficial")

    assert result == OFICIAL_PAYLOAD
    assert mock_get.call_count == 1
    # Verifica que arma la URL correcta.
    called_url = mock_get.call_args.args[0]
    assert called_url.endswith("/v1/dolares/oficial")


def test_reintenta_dos_fallos_y_exito(monkeypatch):
    # 2 fallos de conexion + 1 exito => 3 llamadas en total.
    side_effects = [
        requests.ConnectionError("boom"),
        requests.ConnectionError("boom"),
        _ok_response(OFICIAL_PAYLOAD),
    ]
    mock_get = MagicMock(side_effect=side_effects)
    monkeypatch.setattr(extract.requests, "get", mock_get)

    result = extract.fetch_quote("oficial")

    assert result == OFICIAL_PAYLOAD
    assert mock_get.call_count == 3


def test_falla_tras_tres_reintentos(monkeypatch):
    mock_get = MagicMock(side_effect=requests.ConnectionError("boom"))
    monkeypatch.setattr(extract.requests, "get", mock_get)

    with pytest.raises(requests.RequestException):
        extract.fetch_quote("oficial")

    assert mock_get.call_count == extract.MAX_RETRIES


def test_error_5xx_se_reintenta(monkeypatch):
    # Una respuesta 500 dispara raise_for_status -> se reintenta.
    resp_500 = MagicMock()
    resp_500.status_code = 503
    resp_500.raise_for_status.side_effect = requests.HTTPError("503")

    mock_get = MagicMock(
        side_effect=[resp_500, resp_500, _ok_response(OFICIAL_PAYLOAD)]
    )
    monkeypatch.setattr(extract.requests, "get", mock_get)

    result = extract.fetch_quote("binance")

    assert result == OFICIAL_PAYLOAD
    assert mock_get.call_count == 3


def test_extract_all_devuelve_ambas_casas(monkeypatch):
    binance_payload = {**OFICIAL_PAYLOAD, "casa": "binance", "nombre": "Binance"}

    def fake_fetch(casa: str) -> dict:
        return OFICIAL_PAYLOAD if casa == "oficial" else binance_payload

    monkeypatch.setattr(extract, "fetch_quote", fake_fetch)

    result = extract.extract_all()

    assert set(result.keys()) == {"oficial", "binance"}
    assert result["binance"]["casa"] == "binance"
