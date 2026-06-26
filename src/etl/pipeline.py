"""Orquestador del pipeline ETL: extract -> transform -> load.

Entry point del proceso diario. Carga las variables de entorno desde .env (si
existe) para correr localmente, extrae las cotizaciones de DolarApi, las
transforma/valida y hace UPSERT idempotente en fx.exchange_rates.

Uso:
    python -m src.etl.pipeline
"""

import logging
import sys

from dotenv import load_dotenv

from src.etl.extract import extract_all
from src.etl.load import upsert_quotes
from src.etl.transform import transform

logger = logging.getLogger(__name__)


def run() -> int:
    """Corre el pipeline completo una vez.

    Returns:
        Numero de filas cargadas (0 a 2).
    """
    logger.info("Iniciando pipeline ETL Bolivia Exchange Tracker.")

    extracted = extract_all()
    logger.info("Extraccion OK: %s", list(extracted.keys()))

    quotes = transform(extracted)
    logger.info("Transformacion OK: %d cotizaciones validas.", len(quotes))

    if not quotes:
        logger.warning("No hay cotizaciones validas; no se carga nada.")
        return 0

    loaded = upsert_quotes(quotes)
    logger.info("Pipeline finalizado: %d filas cargadas.", loaded)
    return loaded


def main() -> None:
    """Configura logging, carga el .env y ejecuta el pipeline."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    # En local lee .env; en CI/prod las variables vienen del entorno (no-op).
    load_dotenv()

    try:
        run()
    except Exception:
        logger.exception("El pipeline fallo.")
        sys.exit(1)


if __name__ == "__main__":
    main()
