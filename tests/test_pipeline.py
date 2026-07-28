"""Tests de pipeline.py: alerta de completitud de la corrida diaria."""

from datetime import UTC, date, datetime

import pytest

from src.etl import pipeline
from src.models.schemas import CleanQuote

TS = datetime(2026, 7, 27, 21, 1, 9, tzinfo=UTC)


def _quote(casa: str) -> CleanQuote:
    return CleanQuote(
        fecha=date(2026, 7, 27),
        casa=casa,
        compra=11.59,
        venta=11.63,
        fecha_actualizacion=TS,
    )


# --- casas_faltantes: logica pura, sin I/O ---------------------------------


def test_casas_faltantes_vacio_si_corrida_completa():
    quotes = [_quote("oficial"), _quote("binance")]
    assert pipeline.casas_faltantes(quotes) == []


def test_casas_faltantes_detecta_oficial_ausente():
    assert pipeline.casas_faltantes([_quote("binance")]) == ["oficial"]


def test_casas_faltantes_detecta_binance_ausente():
    assert pipeline.casas_faltantes([_quote("oficial")]) == ["binance"]


def test_casas_faltantes_lista_todas_si_no_hay_nada():
    assert pipeline.casas_faltantes([]) == ["oficial", "binance"]


# --- run(): integracion con extract/transform/load mockeados ---------------


@pytest.fixture
def etl_mocks(mocker):
    """Mockea los tres pasos del ETL y devuelve el mock del load."""
    mocker.patch.object(pipeline, "extract_all", return_value={})
    load = mocker.patch.object(pipeline, "upsert_quotes", side_effect=len)
    return load


def test_run_ok_cuando_ambas_casas_cargan(mocker, etl_mocks):
    quotes = [_quote("oficial"), _quote("binance")]
    mocker.patch.object(pipeline, "transform", return_value=quotes)

    assert pipeline.run() == 2
    etl_mocks.assert_called_once_with(quotes)


def test_run_falla_si_falta_una_casa(mocker, etl_mocks):
    mocker.patch.object(pipeline, "transform", return_value=[_quote("binance")])

    with pytest.raises(pipeline.CotizacionesIncompletasError) as exc:
        pipeline.run()

    assert exc.value.faltantes == ["oficial"]


def test_run_persiste_lo_valido_antes_de_fallar(mocker, etl_mocks):
    """Una casa caida no debe hacer perder la otra: se carga y luego se falla."""
    solo_binance = [_quote("binance")]
    mocker.patch.object(pipeline, "transform", return_value=solo_binance)

    with pytest.raises(pipeline.CotizacionesIncompletasError):
        pipeline.run()

    etl_mocks.assert_called_once_with(solo_binance)


def test_run_falla_sin_intentar_cargar_si_no_hay_nada(mocker, etl_mocks):
    mocker.patch.object(pipeline, "transform", return_value=[])

    with pytest.raises(pipeline.CotizacionesIncompletasError):
        pipeline.run()

    etl_mocks.assert_not_called()


def test_mensaje_de_error_nombra_las_casas_faltantes():
    exc = pipeline.CotizacionesIncompletasError(["oficial"])
    assert "oficial" in str(exc)


# --- main(): exit code 1, que es lo que hace fallar la GitHub Action -------


def test_main_sale_con_codigo_1_si_la_corrida_es_incompleta(mocker):
    mocker.patch.object(pipeline, "load_dotenv")
    mocker.patch.object(
        pipeline, "run", side_effect=pipeline.CotizacionesIncompletasError(["oficial"])
    )

    with pytest.raises(SystemExit) as exc:
        pipeline.main()

    assert exc.value.code == 1


def test_main_sale_con_codigo_1_ante_error_inesperado(mocker):
    mocker.patch.object(pipeline, "load_dotenv")
    mocker.patch.object(pipeline, "run", side_effect=RuntimeError("boom"))

    with pytest.raises(SystemExit) as exc:
        pipeline.main()

    assert exc.value.code == 1


def test_main_no_sale_si_todo_ok(mocker):
    mocker.patch.object(pipeline, "load_dotenv")
    mocker.patch.object(pipeline, "run", return_value=2)

    pipeline.main()  # no debe lanzar SystemExit
