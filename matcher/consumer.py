"""Phase 3 — alert matcher.

Consumes DealEvents (group ``matcher``), finds active watches that match each
deal, and for every new (user, deal, channel) writes a pending row to the
notifications ledger and publishes a NotificationMessage to
``stream:notifications`` for the notifier.

Idempotency: the notifications UNIQUE (user_id, deal_id, channel) constraint is
the dedup guarantee — we only publish when the ledger insert actually created a
row, so a redelivered deal-event never re-alerts. The read-loop/reaper/DLQ come
from shared.streams.run_consumer.

Run: python -m matcher.consumer
"""
from __future__ import annotations

import logging
import os
import signal

from matcher.matching import watch_matches
from shared import db, streams
from shared.config import settings
from shared.models import DealEvent, NotificationMessage

log = logging.getLogger(__name__)

CONSUMER_NAME = os.environ.get("CONSUMER_NAME") or f"matcher-{os.getpid()}"

# MVP channel. Per-watch channel preferences can be added later.
DEFAULT_CHANNEL = "email"

_running = True


def _stop(*_) -> None:
    global _running
    _running = False
    log.info("shutdown requested")


def process_deal(payload: dict) -> None:
    """Match one deal to watches and enqueue notifications. Raises on failure."""
    deal = DealEvent.model_validate(payload)
    if deal.deal_id is None:
        # No deal row id -> can't write the FK-bound ledger row. Skip (not a poison).
        log.warning("deal-event without deal_id, skipping: %s-%s", deal.route_origin, deal.route_destination)
        return

    matched = 0
    with db.get_conn() as conn:
        watches = db.find_active_watches_for_origin(conn, deal.route_origin)
        for w in watches:
            if not watch_matches(
                w,
                destination=deal.route_destination,
                price=deal.price,
                depart_date=deal.depart_date,
            ):
                continue

            notification_id = db.create_notification(
                conn, user_id=w["user_id"], deal_id=deal.deal_id, channel=DEFAULT_CHANNEL
            )
            conn.commit()
            if notification_id is None:
                continue  # already alerted this user for this deal/channel

            matched += 1
            msg = NotificationMessage(
                notification_id=notification_id,
                user_id=w["user_id"],
                email=w["email"],
                deal_id=deal.deal_id,
                channel=DEFAULT_CHANNEL,
                origin=deal.route_origin,
                destination=deal.route_destination,
                price=deal.price,
                depart_date=deal.depart_date,
                return_date=deal.return_date,
                deal_score=deal.deal_score,
                confidence=deal.confidence,
            )
            streams.publish(streams.NOTIFICATIONS, msg.model_dump())

    if matched:
        log.info("deal %s-%s matched %d watch(es)", deal.route_origin, deal.route_destination, matched)


def run() -> None:
    logging.basicConfig(level=settings.log_level)
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    streams.run_consumer(
        streams.DEAL_EVENTS,
        streams.GROUP_MATCHER,
        process_deal,
        consumer_name=CONSUMER_NAME,
        should_continue=lambda: _running,
    )


if __name__ == "__main__":
    run()
