"""Phase 3 — notification delivery + dedup.

Consumes NotificationMessages (group ``notifier``), delivers via the message's
channel, and marks the ledger row sent. Delivery is idempotent: if the ledger
row is already ``sent`` (e.g. the worker crashed after sending but before ack,
then the entry was redelivered), we skip resending. The matcher already enforced
per-(user, deal, channel) dedup via the UNIQUE constraint.

Run: python -m notifier.consumer
"""
from __future__ import annotations

import logging
import os
import signal

from notifier.channels import get_channel
from shared import db, streams
from shared.config import settings
from shared.models import NotificationMessage

log = logging.getLogger(__name__)

CONSUMER_NAME = os.environ.get("CONSUMER_NAME") or f"notifier-{os.getpid()}"

_running = True


def _stop(*_) -> None:
    global _running
    _running = False
    log.info("shutdown requested")


def process_notification(payload: dict) -> None:
    """Deliver one notification, idempotently. Raises on delivery failure so the
    entry stays unacked for the reaper.

    Flow: atomically lease the ledger row (pending -> sending). If we don't win
    the lease (already sent, in flight, or absent) we skip and let the stream
    entry ack. Delivery happens outside any transaction; on failure we reset the
    row to pending and re-raise so it's retried (by stream redelivery or the
    sweeper). Duplicate stream messages can't double-send because only one claim
    wins the pending -> sending transition.
    """
    msg = NotificationMessage.model_validate(payload)

    with db.get_conn() as conn:
        action = db.claim_notification(
            conn, msg.notification_id, max_attempts=settings.notification_max_attempts
        )
        conn.commit()

    if action == "skip":
        log.debug("notification %s not claimable (sent/in-flight/absent), skipping", msg.notification_id)
        return
    if action == "failed":
        log.warning(
            "notification %s exceeded %d attempts -> failed (surfaced for inspection)",
            msg.notification_id, settings.notification_max_attempts,
        )
        return

    try:
        get_channel(msg.channel).send(msg)
    except Exception:
        with db.get_conn() as conn:
            db.reset_notification_pending(conn, msg.notification_id)
            conn.commit()
        raise

    with db.get_conn() as conn:
        db.mark_notification_sent(conn, msg.notification_id)
        conn.commit()


def run() -> None:
    logging.basicConfig(level=settings.log_level)
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    streams.run_consumer(
        streams.NOTIFICATIONS,
        streams.GROUP_NOTIFIER,
        process_notification,
        consumer_name=CONSUMER_NAME,
        should_continue=lambda: _running,
    )


if __name__ == "__main__":
    run()
