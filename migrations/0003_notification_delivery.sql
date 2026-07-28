-- Hardening for at-least-once notification delivery: a delivery attempt counter
-- and an updated_at timestamp that drives the sweeper (orphan recovery) and the
-- delivery state machine (pending -> sending -> sent | failed).
-- Idempotent. Apply after 0002:
--   psql "$DATABASE_URL" -f migrations/0003_notification_delivery.sql

BEGIN;

ALTER TABLE notifications
    ADD COLUMN IF NOT EXISTS attempts   int NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT now();

-- The sweeper scans by (status, updated_at); index it.
CREATE INDEX IF NOT EXISTS ix_notifications_status_updated
    ON notifications (status, updated_at);

COMMENT ON COLUMN notifications.attempts IS 'delivery attempts; capped before -> failed';
COMMENT ON COLUMN notifications.updated_at IS
    'last state change; sweeper re-publishes stale pending and reclaims stuck sending';

COMMIT;
