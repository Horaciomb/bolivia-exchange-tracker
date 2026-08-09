"""Orquestador del pipeline ETL: extract -> transform -> load.

Entry point del proceso diario. Carga las variables de entorno desde .env (si
existe) para correr localmente, extrae las cotizaciones de DolarApi, las
transforma/valida y hace UPSERT idempotente en fx.exchange_rates.

Al terminar corre dos verificaciones de calidad de datos. Cualquiera de las dos
termina el proceso con exit code 1 (aunque la carga en si haya salido bien) para
que GitHub Actions marque la corrida en rojo y notifique:

1. **Completitud de la corrida**: que el pull de hoy haya traido todas las casas
   esperadas.
2. **Continuidad de la serie**: que no haya dias sin cotizacion en la ventana
   reciente ya persistida.

Las dos nacen del mismo incidente. En julio 2026 se perdieron 10 dias de la casa
`oficial` sin que nadie se enterara: el pipeline devolvia exito porque cargaba,
pero la fuente repetia la fecha y el UPSERT pisaba la fila existente en vez de
crear una nueva. La primera verificacion no habria detectado eso; la segunda si.

Uso:
    python -m src.etl.pipeline
"""

import logging
import sys
from datetime import date

from dotenv import load_dotenv

from src.etl.extract import extract_all
from src.etl.load import fetch_huecos, upsert_quotes
from src.etl.transform import transform
from src.models.schemas import CleanQuote

logger = logging.getLogger(__name__)

# Casas que toda corrida diaria debe cargar. Si falta alguna, la corrida falla.
CASAS_ESPERADAS = ("oficial", "binance")

# Ventana hacia atras en la que la serie debe ser continua, sin dias faltantes.
VENTANA_CONTINUIDAD_DIAS = 30


class AlertaDeDatosError(RuntimeError):
    """Base de las alertas de calidad de datos que hacen fallar la corrida.

    La carga puede haber funcionado; lo que falla es la verificacion posterior.
    Se distinguen de un error inesperado en que su mensaje ya es autoexplicativo
    y no necesitan traceback.
    """


class CotizacionesIncompletasError(AlertaDeDatosError):
    """Una o mas casas esperadas no llegaron a cargarse en la corrida."""

    def __init__(self, faltantes: list[str]) -> None:
        self.faltantes = faltantes
        super().__init__(
            f"Corrida incompleta: no se cargo {', '.join(faltantes)}. "
            f"Esperadas: {', '.join(CASAS_ESPERADAS)}."
        )


class SerieIncompletaError(AlertaDeDatosError):
    """La serie persistida tiene dias sin cotizacion en la ventana vigilada."""

    def __init__(self, huecos: list[tuple[date, str]]) -> None:
        self.huecos = huecos
        detalle = ", ".join(f"{fecha} ({casa})" for fecha, casa in huecos)
        super().__init__(
            f"Serie incompleta: {len(huecos)} dia/casa sin cotizacion en los "
            f"ultimos {VENTANA_CONTINUIDAD_DIAS} dias -> {detalle}. "
            "Reparar con un backfill marcado imputado = true "
            "(ver sql/migrations/)."
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
    otra) y recien despues verifica la calidad de los datos.

    Returns:
        Numero de filas cargadas (0 a 2).

    Raises:
        CotizacionesIncompletasError: Si falta alguna casa de
            ``CASAS_ESPERADAS``. Se lanza *despues* del load, de modo que las
            cotizaciones validas quedan persistidas igual.
        SerieIncompletaError: Si la serie tiene dias sin cotizacion en los
            ultimos ``VENTANA_CONTINUIDAD_DIAS`` dias.
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

    # La corrida trajo todo, pero eso no garantiza que haya quedado guardado en
    # un dia nuevo: se verifica contra lo que realmente hay en la tabla.
    huecos = fetch_huecos(VENTANA_CONTINUIDAD_DIAS, CASAS_ESPERADAS)
    if huecos:
        raise SerieIncompletaError(huecos)

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
    except AlertaDeDatosError as exc:
        # Alerta de calidad de datos: el mensaje ya es explicito, un traceback
        # solo agregaria ruido al log de la Action.
        logger.error("%s", exc)
        sys.exit(1)
    except Exception:
        logger.exception("El pipeline fallo.")
        sys.exit(1)


if __name__ == "__main__":
    main()
