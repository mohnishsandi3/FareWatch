-- FareWatch initial schema (Phase 1+).
-- Idempotent: safe to re-run. Applied automatically by postgres on a fresh
-- volume via docker-entrypoint-initdb.d, or manually:
--   psql "$DATABASE_URL" -f migrations/0001_init.sql

BEGIN;

CREATE EXTENSION IF NOT EXISTS "pgcrypto";  -- gen_random_uuid()

-- ---------------------------------------------------------------------------
-- users
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email       text NOT NULL UNIQUE,
    home_origin text,                       -- IATA city code, nullable
    created_at  timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- routes — canonical origin/destination pairs
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS routes (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    origin      text NOT NULL,              -- IATA
    destination text NOT NULL,              -- IATA
    created_at  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (origin, destination)
);

-- ---------------------------------------------------------------------------
-- price_observations — append-only time-series
--
-- Dedup-vs-time-series rule (see CLAUDE.md): one row per
-- (route, depart, return, transfers, obs_bucket). Within a polling window we
-- keep at most one row; the same price seen in a LATER window is a new, wanted
-- row (evidence of stability). NULLs in depart/return participate in the unique
-- constraint via NULLS NOT DISTINCT (Postgres 15+).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS price_observations (
    id                bigserial PRIMARY KEY,
    route_id          uuid NOT NULL REFERENCES routes(id),
    depart_date       date,
    return_date       date,
    price             numeric NOT NULL,
    currency          text NOT NULL,
    transfers         smallint NOT NULL DEFAULT 0,
    observed_at       timestamptz NOT NULL DEFAULT now(),
    obs_bucket        timestamptz NOT NULL,           -- polling window this row belongs to
    source_expires_at timestamptz,                    -- API's per-ticket expires_at
    CONSTRAINT uq_observation
        UNIQUE NULLS NOT DISTINCT
        (route_id, depart_date, return_date, transfers, obs_bucket)
);

CREATE INDEX IF NOT EXISTS ix_obs_route_time
    ON price_observations (route_id, observed_at);

-- ---------------------------------------------------------------------------
-- route_baselines — derived cache, recomputed on a rolling window
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS route_baselines (
    route_id     uuid NOT NULL REFERENCES routes(id),
    month_bucket smallint NOT NULL,         -- 1-12 seasonality; 0 = global fallback tier
    median_price numeric,
    p10_price    numeric,
    mad          numeric,                    -- median absolute deviation
    sample_size  int NOT NULL DEFAULT 0,
    updated_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (route_id, month_bucket)
);

-- ---------------------------------------------------------------------------
-- watches — user criteria
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS watches (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id           uuid NOT NULL REFERENCES users(id),
    origin            text NOT NULL,                 -- IATA
    destination       text,                          -- NULL = flexible/anywhere
    max_price         numeric,
    date_window_start date NOT NULL,
    date_window_end   date NOT NULL,
    flexible_dates    boolean NOT NULL DEFAULT true,
    cabin             text NOT NULL DEFAULT 'economy',
    active            boolean NOT NULL DEFAULT true,
    created_at        timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_watches_active_origin
    ON watches (origin) WHERE active;

-- ---------------------------------------------------------------------------
-- deals — a detected anomaly
-- ---------------------------------------------------------------------------
DO $$ BEGIN
    CREATE TYPE confidence_level AS ENUM ('high', 'medium', 'low');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

CREATE TABLE IF NOT EXISTS deals (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    route_id        uuid NOT NULL REFERENCES routes(id),
    price           numeric NOT NULL,
    depart_date     date,
    return_date     date,
    baseline_median numeric,                 -- snapshot at detection
    deal_score      numeric NOT NULL,        -- for ranking the feed
    confidence      confidence_level NOT NULL,
    detected_at     timestamptz NOT NULL DEFAULT now(),
    expires_at      timestamptz,             -- from source_expires_at
    -- One deal per route/dates/price instance; backstops stream-level dedup.
    CONSTRAINT uq_deal
        UNIQUE NULLS NOT DISTINCT (route_id, depart_date, return_date, price)
);

CREATE INDEX IF NOT EXISTS ix_deals_score
    ON deals (deal_score DESC, detected_at DESC);

-- ---------------------------------------------------------------------------
-- notifications — dedup ledger (the unique constraint IS the dedup guarantee)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS notifications (
    id       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id  uuid NOT NULL REFERENCES users(id),
    deal_id  uuid NOT NULL REFERENCES deals(id),
    channel  text NOT NULL,
    status   text NOT NULL DEFAULT 'pending',
    sent_at  timestamptz,
    UNIQUE (user_id, deal_id, channel)
);

COMMIT;
