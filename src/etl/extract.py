"""Extraccion de cotizaciones desde DolarApi Bolivia.

Expone funciones para obtener las cotizaciones crudas (oficial y binance) y el
estado de la fuente. La extraccion reintenta con backoff exponencial ante
errores de red o respuestas 5xx antes de propagar la excepcion.
"""

import logging
import os
import time

import requests

logger = logging.getLogger(__name__)

# Base URL configurable por entorno; default al endpoint de produccion.
BASE_URL = os.environ.get("DOLARAPI_BASE_URL", "https://bo.dolarapi.com")

# Politica de reintentos.
MAX_RETRIES = 3
BACKOFF_BASE_SECONDS = 1.0
REQUEST_TIMEOUT_SECONDS = 10


def _get_with_retries(url: str) -> dict:
    """Hace GET con reintentos y backoff exponencial.

    Reintenta ante ``requests.RequestException`` (incluye timeouts y errores de
    conexion) y ante respuestas con status >= 500. Los errores 4xx no se
    reintentan porque indican un problema del cliente, no transitorio.

    Args:
        url: URL absoluta a consultar.

    Returns:
        El cuerpo JSON de la respuesta como dict.

    Raises:
        requests.RequestException: Si todos los intentos fallan.
    """
    last_exc: Exception | None = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
            if response.status_code >= 500:
                response.raise_for_status()
            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            last_exc = exc
            logger.warning(
                "Intento %d/%d fallo para %s: %s",
                attempt,
                MAX_RETRIES,
                url,
                exc,
            )
            if attempt < MAX_RETRIES:
                time.sleep(BACKOFF_BASE_SECONDS * (2 ** (attempt - 1)))

    logger.error("Agotados los %d reintentos para %s", MAX_RETRIES, url)
    assert last_exc is not None
    raise last_exc


def fetch_quote(casa: str) -> dict:
    """Obtiene la cotizacion cruda de una casa.

    Args:
        casa: "oficial" o "binance".

    Returns:
        Dict crudo con los campos de la fuente (moneda, casa, nombre, compra,
        venta, fechaActualizacion).
    """
    url = f"{BASE_URL}/v1/dolares/{casa}"
    logger.info("Extrayendo cotizacion '%s' desde %s", casa, url)
    return _get_with_retries(url)


def fetch_estado() -> dict:
    """Obtiene el estado de la fuente (health check de DolarApi).

    Returns:
        Dict con la clave ``estado`` (p. ej. "Disponible").
    """
    url = f"{BASE_URL}/v1/estado"
    return _get_with_retries(url)


def extract_all() -> dict[str, dict]:
    """Extrae las cotizaciones oficial y binance.

    Returns:
        Dict con las claves "oficial" y "binance", cada una con su dict crudo.
    """
    return {
        "oficial": fetch_quote("oficial"),
        "binance": fetch_quote("binance"),
    }
