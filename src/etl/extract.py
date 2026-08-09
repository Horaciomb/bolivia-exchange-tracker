"""Extraccion de cotizaciones desde DolarApi Bolivia.

Expone funciones para obtener las cotizaciones crudas (oficial y binance) y el
estado de la fuente. La extraccion reintenta con backoff exponencial ante
errores de red o respuestas 5xx antes de propagar la excepcion.
"""

import logging
import os
import time

import requests

from src.models.schemas import CASAS

logger = logging.getLogger(__name__)

# Base URL configurable por entorno; default al endpoint de produccion.
BASE_URL = os.environ.get("DOLARAPI_BASE_URL", "https://bo.dolarapi.com")

# Politica de reintentos.
MAX_RETRIES = 3
BACKOFF_BASE_SECONDS = 1.0
REQUEST_TIMEOUT_SECONDS = 10


def _get_with_retries(url: str) -> dict:
    """Hace GET con reintentos y backoff exponencial.

    Se reintenta lo que puede recuperarse solo: errores de red y timeouts
    (``requests.RequestException``) y respuestas 5xx, que indican que la fuente
    esta caida. Un 4xx se propaga en el primer intento, porque significa que la
    peticion esta mal (URL o casa inexistente) y reintentarla solo gasta tiempo.

    Args:
        url: URL absoluta a consultar.

    Returns:
        El cuerpo JSON de la respuesta como dict.

    Raises:
        requests.HTTPError: Ante una respuesta 4xx (sin reintentar) o 5xx
            persistente.
        requests.RequestException: Si se agotan los reintentos por errores de
            red.
    """
    last_exc: requests.RequestException | None = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
        except requests.RequestException as exc:
            # Red caida o timeout: transitorio.
            last_exc = exc
        else:
            if response.status_code < 400:
                return response.json()

            error = requests.HTTPError(
                f"HTTP {response.status_code} en {url}", response=response
            )
            if response.status_code < 500:
                logger.error(
                    "Respuesta %d de %s: error del cliente, no se reintenta.",
                    response.status_code,
                    url,
                )
                raise error
            last_exc = error

        logger.warning(
            "Intento %d/%d fallo para %s: %s",
            attempt,
            MAX_RETRIES,
            url,
            last_exc,
        )
        if attempt < MAX_RETRIES:
            time.sleep(BACKOFF_BASE_SECONDS * (2 ** (attempt - 1)))

    logger.error("Agotados los %d reintentos para %s", MAX_RETRIES, url)
    # El bucle solo llega aqui despues de al menos un fallo, asi que last_exc
    # nunca es None.
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
    """Extrae la cotizacion de todas las casas que rastrea el sistema.

    Returns:
        Dict con una clave por casa de ``CASAS``, cada una con su dict crudo.
    """
    return {casa: fetch_quote(casa) for casa in CASAS}
