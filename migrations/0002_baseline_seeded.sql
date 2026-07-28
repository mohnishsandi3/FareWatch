-- Add a seeded flag to route_baselines so the engine can keep cold-start
-- (seeded) baselines at low confidence until enough native observations accrue.
-- Idempotent. Apply manually after 0001 on an existing DB:
--   psql "$DATABASE_URL" -f migrations/0002_baseline_seeded.sql

BEGIN;

ALTER TABLE route_baselines
    ADD COLUMN IF NOT EXISTS seeded boolean NOT NULL DEFAULT false;

COMMENT ON COLUMN route_baselines.seeded IS
    'true = derived from Travelpayouts seed endpoints (cold-start), not native '
    'observations; forces low confidence until native data replaces it.';

COMMIT;
