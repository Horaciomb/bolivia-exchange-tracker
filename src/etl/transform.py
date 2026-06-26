"""Transformacion y validacion de cotizaciones.

Convierte los dicts crudos de DolarApi en una lista de ``CleanQuote`` validadas
y normalizadas, calculando la brecha cambiaria para la cotizacion binance.

Reglas de negocio (sanity checks). Una fila que las incumpla se descarta con un
warning, sin romper el pipeline:

- ``compra > 0``
- ``venta >= compra``
- ``venta < MAX_VENTA`` (el dolar en Bolivia no llega a 100 Bs)
"""

import logging

from src.models.schemas import BOLIVIA_TZ, MAX_VENTA, CleanQuote, RawQuote

logger = logging.getLogger(__name__)


def parse_raw(raw: dict) -> RawQuote:
    """Valida un dict crudo contra el modelo RawQuote.

    Args:
        raw: Dict tal como lo devuelve la fuente.

    Returns:
        Instancia de RawQuote.

    Raises:
        pydantic.ValidationError: Si faltan campos o los tipos no encajan.
    """
    return RawQuote.model_validate(raw)


def validar_reglas(quote: RawQuote) -> bool:
    """Aplica los sanity checks de negocio a una cotizacion.

    Args:
        quote: Cotizacion cruda ya parseada.

    Returns:
        True si la cotizacion es valida; False (y loggea warning) si no.
    """
    if quote.compra <= 0:
        logger.warning("Descartada %s: compra <= 0 (%s)", quote.casa, quote.compra)
        return False
    if quote.venta < quote.compra:
        logger.warning(
            "Descartada %s: venta (%s) < compra (%s)",
            quote.casa,
            quote.venta,
            quote.compra,
        )
        return False
    if quote.venta >= MAX_VENTA:
        logger.warning(
            "Descartada %s: venta (%s) >= MAX_VENTA (%s)",
            quote.casa,
            quote.venta,
            MAX_VENTA,
        )
        return False
    return True


def calcular_brecha(oficial: RawQuote, binance: RawQuote) -> float:
    """Calcula la brecha cambiaria de binance sobre el oficial.

    Args:
        oficial: Cotizacion oficial.
        binance: Cotizacion binance/paralelo.

    Returns:
        Porcentaje de brecha redondeado a 2 decimales:
        ``((binance.venta - oficial.venta) / oficial.venta) * 100``.
    """
    brecha = ((binance.venta - oficial.venta) / oficial.venta) * 100
    return round(brecha, 2)


def to_clean(raw: RawQuote, brecha_pct: float | None) -> CleanQuote:
    """Normaliza una cotizacion cruda a CleanQuote.

    Deriva ``fecha`` convirtiendo el timestamp de la fuente (UTC) a hora Bolivia
    (UTC-4) antes de truncar a fecha, para que cerca de medianoche no quede
    corrida un dia.

    Args:
        raw: Cotizacion cruda valida.
        brecha_pct: Brecha calculada (solo binance) o None.

    Returns:
        Instancia de CleanQuote.
    """
    fecha_bolivia = raw.fecha_actualizacion.astimezone(BOLIVIA_TZ).date()
    return CleanQuote(
        fecha=fecha_bolivia,
        casa=raw.casa,
        compra=raw.compra,
        venta=raw.venta,
        brecha_pct=brecha_pct,
        fecha_actualizacion=raw.fecha_actualizacion,
    )


def transform(extracted: dict[str, dict]) -> list[CleanQuote]:
    """Orquesta el transform de ambas cotizaciones.

    Parsea y valida oficial y binance, calcula la brecha de binance (solo si el
    oficial es valido) y retorna las CleanQuote validas. Las filas que fallan la
    validacion se descartan sin romper el pipeline.

    Args:
        extracted: Dict con claves "oficial" y "binance" (dicts crudos).

    Returns:
        Lista de CleanQuote validas (0 a 2 elementos).
    """
    clean: list[CleanQuote] = []

    oficial_raw = parse_raw(extracted["oficial"])
    binance_raw = parse_raw(extracted["binance"])

    oficial_ok = validar_reglas(oficial_raw)
    binance_ok = validar_reglas(binance_raw)

    if oficial_ok:
        clean.append(to_clean(oficial_raw, brecha_pct=None))

    if binance_ok:
        # La brecha requiere el oficial valido; si no, se emite con None.
        brecha = calcular_brecha(oficial_raw, binance_raw) if oficial_ok else None
        if not oficial_ok:
            logger.warning(
                "Oficial invalido: se emite binance sin brecha_pct."
            )
        clean.append(to_clean(binance_raw, brecha_pct=brecha))

    return clean
