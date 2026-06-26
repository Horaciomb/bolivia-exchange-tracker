"""Modelos pydantic y constantes de negocio del pipeline.

Define los dos modelos centrales:

- ``RawQuote``: refleja la respuesta cruda de DolarApi (validacion de tipos).
- ``CleanQuote``: cotizacion ya normalizada, lista para cargar a PostgreSQL.

El formato real de la fuente fue confirmado con un curl en vivo, por ejemplo::

    {
      "moneda": "USD",
      "casa": "oficial",
      "nombre": "Oficial",
      "compra": 6.86,
      "venta": 6.96,
      "fechaActualizacion": "2026-06-25T21:01:05.619Z"
    }
"""

from datetime import date, datetime, timedelta, timezone

from pydantic import BaseModel, ConfigDict, Field

# Zona horaria de Bolivia (UTC-4, sin horario de verano).
BOLIVIA_TZ = timezone(timedelta(hours=-4))

# Sanity check: el dolar en Bolivia no llega a 100 Bs. Una venta >= 100
# indica un dato corrupto de la fuente y la fila se descarta.
MAX_VENTA = 100.0


class RawQuote(BaseModel):
    """Cotizacion cruda tal como la devuelve DolarApi.

    Acepta el payload original (con la clave ``fechaActualizacion`` en
    camelCase) gracias al alias y a ``populate_by_name``. pydantic parsea el
    string ISO-8601 con sufijo ``Z`` a un ``datetime`` aware en UTC.

    Attributes:
        moneda: Codigo de la moneda (siempre "USD"). No se persiste.
        casa: Identificador de la casa de cambio ("oficial" o "binance").
        nombre: Nombre legible de la casa. Redundante; no se persiste.
        compra: Precio de compra en Bs.
        venta: Precio de venta en Bs.
        fecha_actualizacion: Timestamp original de la fuente (UTC).
    """

    model_config = ConfigDict(populate_by_name=True)

    moneda: str
    casa: str
    nombre: str
    compra: float
    venta: float
    fecha_actualizacion: datetime = Field(alias="fechaActualizacion")


class CleanQuote(BaseModel):
    """Cotizacion normalizada, lista para cargar a la tabla exchange_rates.

    Attributes:
        fecha: Fecha de la cotizacion en hora Bolivia (UTC-4).
        casa: "oficial" o "binance".
        compra: Precio de compra en Bs.
        venta: Precio de venta en Bs.
        brecha_pct: Porcentaje de brecha sobre el oficial. Solo se calcula
            para binance; ``None`` para oficial o si no se pudo calcular.
        fecha_actualizacion: Timestamp original de la fuente (UTC).
    """

    fecha: date
    casa: str
    compra: float
    venta: float
    brecha_pct: float | None = None
    fecha_actualizacion: datetime
