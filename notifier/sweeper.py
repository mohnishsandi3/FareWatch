"""Phase 3 hardening — notification re-publish sweeper.

The matcher publishes a notification to the stream right after writing the ledger
row (fast path). If that publish is lost (matcher crashed between commit and
XADD) or a notifier crashes mid-delivery, the stream copy disappears but the
ledger row remains stuck. This sweeper is the safety net: on an interval it
re-publishes stale `pending` rows and reclaims `sending` rows stuck past the
lease, so every accepted match is eventually delivered.

Re-publishing is safe: the notifier's atomic lease-claim means duplicate stream
messages for the same notification can't double-send.

Run: python -m notifier.sweeper
"""
from __future__ import annotations

import logging
import signal

from apscheduler.schedulers.blocking import BlockingScheduler

from shared import db, streams
from shared.config import settings

log = logging.getLogger(__name__)


def sweep_once() -> int:
    """One sweep pass. Returns the number of notifications re-published."""
    with db.get_conn() as conn:
        msgs = db.sweep_republishable(
            conn,
            grace_seconds=settings.notification_grace_seconds,
            lease_seconds=settings.notification_lease_seconds,
            limit=settings.notification_sweep_batch,
        )
        for m in msgs:
            streams.publish(streams.NOTIFICATIONS, m)
        conn.commit()  # releases the FOR UPDATE locks after publishing
    if msgs:
        log.info("re-published %d straggler notification(s)", len(msgs))
    return len(msgs)


def run() -> None:
    logging.basicConfig(level=settings.log_level)
    interval = settings.notification_sweep_interval_seconds
    scheduler = BlockingScheduler(timezone="UTC")
    scheduler.add_job(sweep_once, "interval", seconds=interval, id="sweep")

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: scheduler.shutdown(wait=False))

    log.info("notification sweeper starting; interval=%ss grace=%ss lease=%ss",
             interval, settings.notification_grace_seconds, settings.notification_lease_seconds)
    scheduler.start()


if __name__ == "__main__":
    run()
