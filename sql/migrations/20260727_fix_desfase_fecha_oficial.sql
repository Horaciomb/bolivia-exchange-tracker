-- Migracion 2026-07-27: corrige el desfase de un dia en la serie `oficial`.
--
-- CONTEXTO
-- Desde el 2026-07-07 la fuente (DolarApi) dejo de mandar un timestamp real
-- para la casa `oficial` y pasó a codificar solo la fecha, como medianoche UTC:
--
--     oficial:  "fechaActualizacion": "2026-07-27T00:00:00.000Z"   <- fecha
--     binance:  "fechaActualizacion": "2026-07-27T21:01:09.629Z"   <- timestamp
--
-- El transform normalizaba ese valor a hora Bolivia (UTC-4), correcto para el
-- timestamp intradia de binance pero destructivo sobre una medianoche UTC:
-- restaba 4 horas y retrocedia el dia (27-jul 00:00 UTC -> 26-jul 20:00 BOL).
-- Resultado: 18 filas `oficial` (2026-07-07 a 2026-07-26) quedaron guardadas
-- con la fecha del dia anterior al que realmente corresponden.
--
-- Efecto colateral: `brecha_pct` (calculada correctamente en el momento del
-- pull) no se podia reproducir con un JOIN por fecha, porque el oficial del
-- mismo pull vivia en fecha-1.
--
-- El fix del pipeline esta en src/etl/transform.py::derivar_fecha, que detecta
-- la medianoche UTC exacta y toma la fecha literal en vez de convertir la TZ.
-- Esta migracion repara los datos ya cargados.
--
-- Backup previo: fx.exchange_rates_bkp_20260727 (56 filas).

BEGIN;

-- El shift se hace en dos pasos porque `fecha + 1 dia` directo colisiona fila a
-- fila contra uq_fecha_casa (Postgres valida el indice unico por fila, no al
-- final del statement): el nuevo valor de una fila choca con el viejo de la
-- siguiente. Se mueven primero a un rango temporal libre y luego de vuelta.

-- Paso 1: rango temporal (+1000 dias).
UPDATE fx.exchange_rates
SET fecha = fecha + INTERVAL '1000 days'
WHERE casa = 'oficial'
  AND fecha_actualizacion AT TIME ZONE 'UTC'
      = date_trunc('day', fecha_actualizacion AT TIME ZONE 'UTC');

-- Paso 2: vuelta a la fecha correcta (neto +1 dia), la que la fuente codifico.
UPDATE fx.exchange_rates
SET fecha = fecha - INTERVAL '999 days'
WHERE casa = 'oficial'
  AND fecha >= '2029-01-01';

COMMIT;

-- VERIFICACION (ejecutada post-migracion, todas OK)
--
-- 1. Ninguna fila oficial queda desfasada respecto a su fecha de origen:
--      SELECT COUNT(*) FROM fx.exchange_rates
--      WHERE casa='oficial'
--        AND fecha_actualizacion AT TIME ZONE 'UTC'
--            = date_trunc('day', fecha_actualizacion AT TIME ZONE 'UTC')
--        AND fecha <> (fecha_actualizacion AT TIME ZONE 'UTC')::date;
--    -> 0
--
-- 2. Las 23 brechas guardadas se reproducen con JOIN por misma fecha
--    (23 comparables, 23 coinciden, 0 discrepan) sin haber tocado brecha_pct.
--
-- 3. Integridad: 56 filas antes y despues, 0 residuo en el rango temporal.
--
-- NOTA: quedan 10 dias sin cotizacion oficial (2026-06-30 a 2026-07-07,
-- 2026-07-11 y 2026-07-12). NO son efecto de este bug sino extracciones que
-- nunca ocurrieron: coinciden con el cambio de regimen cambiario del 29-jun,
-- cuando la fuente cambio el formato del payload oficial y el transform
-- descarto las filas por los sanity checks. Se dejan como huecos reales en
-- vez de imputarlos.
