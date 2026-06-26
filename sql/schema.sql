-- Schema y tabla del Bolivia Exchange Rate Tracker.
-- Compatible con PostgreSQL / Supabase.
--
-- El proyecto vive en un esquema dedicado `fx` dentro de una instancia
-- PostgreSQL compartida con otros proyectos (NO es un proyecto Supabase nuevo).
-- Esto lo aisla logicamente sin afectar a `public` ni a otros esquemas.
--
-- Idempotencia: UNIQUE (fecha, casa) permite que el ETL haga UPSERT
-- (ON CONFLICT) y correr el pipeline dos veces el mismo dia no duplique filas.

CREATE SCHEMA IF NOT EXISTS fx;

CREATE TABLE IF NOT EXISTS fx.exchange_rates (
    id                  bigint        GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    fecha               date          NOT NULL,
    casa                text          NOT NULL,
    compra              numeric(10, 4) NOT NULL,
    venta               numeric(10, 4) NOT NULL,
    brecha_pct          numeric(6, 2),                       -- solo binance: % sobre oficial
    fecha_actualizacion timestamptz   NOT NULL,              -- timestamp original de la fuente
    created_at          timestamptz   NOT NULL DEFAULT now(),

    CONSTRAINT exchange_rates_casa_chk CHECK (casa IN ('oficial', 'binance')),
    CONSTRAINT uq_fecha_casa UNIQUE (fecha, casa)
);

-- Optimizan las queries /rates/latest, /rates/history y /rates/brecha del API.
CREATE INDEX IF NOT EXISTS idx_fx_rates_fecha
    ON fx.exchange_rates (fecha DESC);
CREATE INDEX IF NOT EXISTS idx_fx_rates_casa_fecha
    ON fx.exchange_rates (casa, fecha DESC);
