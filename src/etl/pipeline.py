"""Orquestador del pipeline ETL: extract -> transform -> load.

Entry point del proceso diario. Carga las variables de entorno desde .env (si
existe) para correr localmente, extrae las cotizaciones de DolarApi, las
transforma/valida y hace UPSERT idempotente en fx.exchange_rates.

Al terminar verifica la **completitud**: si alguna casa esperada no llego a
cargarse, el proceso termina con exit code 1 aunque el resto haya cargado bien,
para que GitHub Actions marque la corrida en rojo y notifique. Sin esto un fallo
parcial es silencioso: en julio 2026 se perdieron 10 dias de la casa `oficial`
sin que nadie se enterara, porque el transform descartaba la fila con un warning
y el pipeline seguia devolviendo exito.

Uso:
    python -m src.etl.pipeline
"""

import logging
import sys

from dotenv import load_dotenv

from src.etl.extract import extract_all
from src.etl.load import upsert_quotes
from src.etl.transform import transform
from src.models.schemas import CleanQuote

logger = logging.getLogger(__name__)

# Casas que toda corrida diaria debe cargar. Si falta alguna, la corrida falla.
CASAS_ESPERADAS = ("oficial", "binance")


class CotizacionesIncompletasError(RuntimeError):
    """Una o mas casas esperadas no llegaron a cargarse en la corrida."""

    def __init__(self, faltantes: list[str]) -> None:
        self.faltantes = faltantes
        super().__init__(
            f"Corrida incompleta: no se cargo {', '.join(faltantes)}. "
            f"Esperadas: {', '.join(CASAS_ESPERADAS)}."
        )


def casas_faltantes(quotes: list[CleanQuote]) -> list[str]:
    """Devuelve las casas esperadas que no estan presentes en las cotizaciones.

    Se evalua despues del transform, de modo que cubre tanto el caso de que la
    fuente no devolviera la casa como el de que los sanity checks la
    descartaran.

    Args:
        quotes: Cotizaciones validas emitidas por el transform.

    Returns:
        Lista de casas faltantes, en el orden de ``CASAS_ESPERADAS``. Vacia si
        la corrida esta completa.
    """
    presentes = {q.casa for q in quotes}
    return [casa for casa in CASAS_ESPERADAS if casa not in presentes]


def run() -> int:
    """Corre el pipeline completo una vez.

    Carga siempre lo que sea valido (una casa caida no debe hacer perder la
    otra) y recien despues verifica la completitud de la corrida.

    Returns:
        Numero de filas cargadas (0 a 2).

    Raises:
        CotizacionesIncompletasError: Si falta alguna casa de
            ``CASAS_ESPERADAS``. Se lanza *despues* del load, de modo que las
            cotizaciones validas quedan persistidas igual.
    """
    logger.info("Iniciando pipeline ETL Bolivia Exchange Tracker.")

    extracted = extract_all()
    logger.info("Extraccion OK: %s", list(extracted.keys()))

    quotes = transform(extracted)
    logger.info("Transformacion OK: %d cotizaciones validas.", len(quotes))

    loaded = upsert_quotes(quotes) if quotes else 0
    if not quotes:
        logger.warning("No hay cotizaciones validas; no se carga nada.")

    faltantes = casas_faltantes(quotes)
    if faltantes:
        # Se cargo lo que habia, pero la corrida no esta completa: hay que
        # fallar fuerte para que el hueco no pase inadvertido.
        raise CotizacionesIncompletasError(faltantes)

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
    except CotizacionesIncompletasError as exc:
        # Fallo de completitud: el mensaje ya es explicito, un traceback solo
        # agregaria ruido al log de la Action.
        logger.error("%s", exc)
        sys.exit(1)
    except Exception:
        logger.exception("El pipeline fallo.")
        sys.exit(1)


if __name__ == "__main__":
    main()
