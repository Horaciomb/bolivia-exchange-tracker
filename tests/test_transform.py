"""Tests de transform.py: brecha, validacion de reglas y manejo de timezone."""

from datetime import date

from src.etl import transform
from src.models.schemas import RawQuote

# Payloads base con el formato real confirmado de la API.
OFICIAL = {
    "moneda": "USD",
    "casa": "oficial",
    "nombre": "Oficial",
    "compra": 6.86,
    "venta": 6.96,
    "fechaActualizacion": "2026-06-25T21:01:05.619Z",
}
BINANCE = {
    "moneda": "USD",
    "casa": "binance",
    "nombre": "Binance",
    "compra": 9.84,
    "venta": 9.87,
    "fechaActualizacion": "2026-06-25T21:01:06.326Z",
}


def _raw(payload: dict) -> RawQuote:
    return transform.parse_raw(payload)


def test_calcular_brecha_valores_reales():
    brecha = transform.calcular_brecha(_raw(OFICIAL), _raw(BINANCE))
    # (9.87 - 6.96) / 6.96 * 100 = 41.8103... -> 41.81
    assert brecha == 41.81


def test_validar_rechaza_venta_menor_que_compra():
    mala = {**OFICIAL, "compra": 7.0, "venta": 6.5}
    assert transform.validar_reglas(_raw(mala)) is False


def test_validar_rechaza_venta_absurda():
    absurda = {**OFICIAL, "compra": 99.0, "venta": 150.0}
    assert transform.validar_reglas(_raw(absurda)) is False


def test_validar_rechaza_compra_no_positiva():
    cero = {**OFICIAL, "compra": 0.0, "venta": 6.96}
    assert transform.validar_reglas(_raw(cero)) is False


def test_validar_acepta_caso_normal():
    assert transform.validar_reglas(_raw(OFICIAL)) is True


def test_fecha_se_normaliza_a_hora_bolivia():
    # 02:30 UTC del 26-jun => en Bolivia (UTC-4) son las 22:30 del 25-jun.
    cerca_medianoche = {**OFICIAL, "fechaActualizacion": "2026-06-26T02:30:00.000Z"}
    clean = transform.to_clean(_raw(cerca_medianoche), brecha_pct=None)
    assert clean.fecha == date(2026, 6, 25)


def test_fecha_medianoche_utc_se_toma_literal():
    # La fuente codifica la fecha del oficial como medianoche UTC: NO se
    # convierte a UTC-4 (eso la retrocederia al 26-jul).
    solo_fecha = {**OFICIAL, "fechaActualizacion": "2026-07-27T00:00:00.000Z"}
    clean = transform.to_clean(_raw(solo_fecha), brecha_pct=None)
    assert clean.fecha == date(2026, 7, 27)


def test_fecha_un_segundo_despues_de_medianoche_si_se_convierte():
    # Frontera: con hora real (aunque sea 00:00:01) vuelve a aplicar UTC-4.
    casi_medianoche = {**OFICIAL, "fechaActualizacion": "2026-07-27T00:00:01.000Z"}
    clean = transform.to_clean(_raw(casi_medianoche), brecha_pct=None)
    assert clean.fecha == date(2026, 7, 26)


def test_transform_mixto_alinea_ambas_casas_en_la_misma_fecha():
    # Caso real de produccion: oficial con fecha-a-medianoche y binance con
    # timestamp intradia del mismo dia deben caer en la misma fecha.
    oficial = {**OFICIAL, "fechaActualizacion": "2026-07-27T00:00:00.000Z"}
    binance = {**BINANCE, "fechaActualizacion": "2026-07-27T21:01:09.629Z"}
    result = transform.transform({"oficial": oficial, "binance": binance})

    assert {q.fecha for q in result} == {date(2026, 7, 27)}


def test_transform_completo_emite_dos_filas_con_brecha():
    result = transform.transform({"oficial": OFICIAL, "binance": BINANCE})

    assert len(result) == 2
    por_casa = {q.casa: q for q in result}
    assert por_casa["oficial"].brecha_pct is None
    assert por_casa["binance"].brecha_pct == 41.81
    assert por_casa["oficial"].fecha == date(2026, 6, 25)


def test_transform_descarta_oficial_invalido_y_emite_binance_sin_brecha():
    oficial_malo = {**OFICIAL, "compra": 7.0, "venta": 6.5}  # venta < compra
    result = transform.transform({"oficial": oficial_malo, "binance": BINANCE})

    # Oficial descartado; binance se emite pero sin brecha (oficial invalido).
    assert len(result) == 1
    assert result[0].casa == "binance"
    assert result[0].brecha_pct is None


def test_transform_descarta_binance_invalido():
    binance_malo = {**BINANCE, "venta": 200.0}  # absurdo
    result = transform.transform({"oficial": OFICIAL, "binance": binance_malo})

    assert len(result) == 1
    assert result[0].casa == "oficial"
