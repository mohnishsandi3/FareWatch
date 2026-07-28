"""Phase 2 — detection-engine consumer.

Consumes observations as group ``engine``, updates the route's baselines, runs
the detector, and publishes any DealEvent to ``stream:deal-events``. The
read-loop, reaper, and dead-letter machinery live in shared.streams.run_consumer
(this is a learning vehicle — the streaming machinery is real, just factored so
every stage shares it). This module only provides the per-message handler.

Idempotency backstops: the Redis processed-key (fast path) plus the DB unique
constraints on deals/observations (final guarantee).

Run: python -m engine.consumer
"""
from __future__ import annotations

import logging
import os
import signal

from engine import baselines, detector
from shared import db, streams
from shared.config import settings
from shared.models import DealEvent, PriceObservation

log = logging.getLogger(__name__)

CONSUMER_NAME = os.environ.get("CONSUMER_NAME") or f"engine-{os.getpid()}"

_running = True


def _stop(*_) -> None:
    global _running
    _running = False
    log.info("shutdown requested")


def process_observation(payload: dict) -> None:
    """One observation -> baseline refresh + maybe a deal. Raises on failure so
    the entry stays unacked for the reaper."""
    obs = PriceObservation.model_validate(payload)

    # Fast-path dedup: a redelivered identical observation is a no-op.
    if not streams.mark_processed(obs.dedup_key()):
        log.debug("duplicate observation %s, skipping", obs.dedup_key()[:12])
        return

    with db.get_conn() as conn:
        route_id = db.get_or_create_route(conn, obs.origin, obs.destination)
        baselines.recompute_route(conn, route_id)

        event: DealEvent | None = detector.evaluate(conn, obs)
        if event is None:
            return

        deal_id = db.insert_deal(
            conn,
            route_id=route_id,
            price=event.price,
            depart_date=event.depart_date,
            return_date=event.return_date,
            baseline_median=event.baseline_median,
            deal_score=event.deal_score,
            confidence=event.confidence,
            detected_at=event.detected_at,
            expires_at=event.expires_at,
        )
        conn.commit()

    # Only publish for genuinely new deals (DB uq_deal is the dedup backstop).
    if deal_id is not None:
        event.deal_id = deal_id
        streams.publish(streams.DEAL_EVENTS, event.model_dump())
        log.info(
            "DEAL %s-%s $%.0f score=%.2f conf=%s",
            event.route_origin, event.route_destination, event.price,
            event.deal_score, event.confidence,
        )


def run() -> None:
    logging.basicConfig(level=settings.log_level)
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    streams.run_consumer(
        streams.OBSERVATIONS,
        streams.GROUP_ENGINE,
        process_observation,
        consumer_name=CONSUMER_NAME,
        should_continue=lambda: _running,
    )


if __name__ == "__main__":
    run()
