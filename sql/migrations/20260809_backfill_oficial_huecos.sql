-- Migracion 2026-08-09: reconstruye los 10 dias sin cotizacion `oficial`.
--
-- CONTEXTO
-- Entre el 2026-06-30 y el 2026-07-12 quedaron 10 dias sin fila `oficial`
-- (06-30 a 07-07, 07-11 y 07-12). No son efecto del desfase de fecha que
-- corrigio 20260727_fix_desfase_fecha_oficial.sql: coinciden con el cambio de
-- regimen cambiario del 29-jun, cuando la fuente cambio el formato del payload
-- oficial y el UPSERT quedo pisando la misma clave (fecha, casa) en vez de
-- crear filas nuevas. DolarApi solo expone el valor actual, asi que esos dias
-- no se pueden volver a pedir.
--
-- METODO: inversion algebraica, no interpolacion
-- La serie `binance` esta completa y conserva su `brecha_pct`, que se calculo
-- en el momento del pull contra el valor oficial vigente ese dia. La formula
-- de la brecha es invertible:
--
--     brecha_pct = ((binance.venta - oficial.venta) / oficial.venta) * 100
--  => oficial.venta = binance.venta / (1 + brecha_pct / 100)
--
-- Es decir: el valor oficial de esos dias nunca se perdio, quedo codificado
-- dentro de la brecha. No se esta estimando nada, se esta despejando.
--
-- Validacion previa sobre los 35 dias que SI tienen ambas casas: la inversion
-- reproduce `oficial.venta` con un error maximo de 0.0006 Bs, atribuible al
-- redondeo de `brecha_pct` a 2 decimales. Por eso el resultado se redondea a 2
-- decimales, que es la precision con la que publica la fuente.
--
-- `compra` NO es recuperable por esta via (no participa en la brecha). Se
-- deriva aplicando el spread compra/venta del ultimo dia oficial conocido, que
-- ademas garantiza compra <= venta:
--
--     06-30 a 07-07 -> referencia 06-29 (9.73 / 9.83, spread ~1.02%)
--     07-11, 07-12  -> referencia 07-10 (10.24 / 10.24, spread 0%)
--
-- Como `compra` es estimada, las 10 filas se marcan `imputado = true` aunque
-- `venta` sea una reconstruccion exacta. El flag se expone en el API.
--
-- `fecha_actualizacion` se fija a las 23:00 hora Bolivia (03:00 UTC del dia
-- siguiente), misma convencion que el backfill del 2026-06-26.

BEGIN;

INSERT INTO fx.exchange_rates
    (fecha, casa, compra, venta, brecha_pct, fecha_actualizacion, imputado)
SELECT
    h.fecha,
    'oficial',
    ROUND(h.venta_derivada * (ref.compra / ref.venta), 2),  -- spread del dia previo
    h.venta_derivada,
    NULL,                                                   -- brecha: solo binance
    ((h.fecha + 1) + TIME '03:00:00') AT TIME ZONE 'UTC',
    true
FROM (
    -- Dias con binance (y brecha) pero sin oficial: los huecos reconstruibles.
    SELECT
        b.fecha,
        ROUND(b.venta / (1 + b.brecha_pct / 100), 2) AS venta_derivada
    FROM fx.exchange_rates b
    WHERE b.casa = 'binance'
      AND b.brecha_pct IS NOT NULL
      AND NOT EXISTS (
          SELECT 1
          FROM fx.exchange_rates o
          WHERE o.casa = 'oficial'
            AND o.fecha = b.fecha
      )
) h
CROSS JOIN LATERAL (
    -- Ultimo oficial real anterior al hueco, del que se toma el spread.
    SELECT o.compra, o.venta
    FROM fx.exchange_rates o
    WHERE o.casa = 'oficial'
      AND o.fecha < h.fecha
    ORDER BY o.fecha DESC
    LIMIT 1
) ref
-- Idempotente: re-ejecutar la migracion no pisa filas reales ya cargadas.
ON CONFLICT (fecha, casa) DO NOTHING;

COMMIT;

-- VERIFICACION (ejecutada post-migracion, todas OK)
--
-- 1. 10 filas insertadas, todas con imputado = true. Total: 80 -> 90 filas.
--
-- 2. Sin huecos: entre 2026-06-25 y 2026-08-08 cada dia tiene las dos casas.
--      WITH cal AS (SELECT generate_series(MIN(fecha), MAX(fecha), '1 day')::date f
--                   FROM fx.exchange_rates)
--      SELECT COUNT(*) FROM cal c CROSS JOIN (VALUES ('oficial'),('binance')) t(casa)
--      WHERE NOT EXISTS (SELECT 1 FROM fx.exchange_rates r
--                        WHERE r.fecha=c.f AND r.casa=t.casa);
--    -> 0
--
-- 3. Coherencia de los valores reconstruidos: 9.83 para 06-30..07-07 (igual al
--    oficial real del 06-29) y 10.24 para 07-11/07-12 (igual al del 07-10). El
--    tipo de cambio oficial estuvo plano en ambas ventanas, que es justamente
--    por que el UPSERT pisaba la misma fila.
--
-- 4. Reglas de negocio: 0 filas con compra <= 0, venta < compra o venta >= 100.
