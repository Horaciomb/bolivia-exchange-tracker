-- Schema de la tabla exchange_rates (Bolivia Exchange Rate Tracker).
-- Compatible con PostgreSQL / Supabase.
--
-- Idempotencia: UNIQUE (fecha, casa) permite que el ETL haga UPSERT
-- (ON CONFLICT) y correr el pipeline dos veces el mismo dia no duplique filas.

CREATE TABLE IF NOT EXISTS exchange_rates (
    id                  bigint        GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    fecha               date          NOT NULL,
    casa                text          NOT NULL,
    compra              numeric(10, 4) NOT NULL,
    venta               numeric(10, 4) NOT NULL,
    brecha_pct          numeric(6, 2),                       -- solo binance: % sobre oficial
    fecha_actualizacion timestamptz   NOT NULL,              -- timestamp original de la fuente
    created_at          timestamptz   NOT NULL DEFAULT now(),

    CONSTRAINT exchange_rates_casa_chk CHECK (casa IN ('oficial', 'binance')),
    CONSTRAINT exchange_rates_fecha_casa_uq UNIQUE (fecha, casa)
);

-- Optimiza las queries /rates/latest e /rates/history del API.
CREATE INDEX IF NOT EXISTS exchange_rates_casa_fecha_idx
    ON exchange_rates (casa, fecha DESC);
