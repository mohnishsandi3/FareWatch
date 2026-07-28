"""Long-running scheduler for ingestion.

Runs the price poller on a fixed interval (POLL_INTERVAL_SECONDS). Kept
deliberately simple — APScheduler in-process is plenty for a curated hub set.
This is the container entrypoint for the ``ingestion`` service.
"""
from __future__ import annotations

import logging
import signal

from apscheduler.schedulers.blocking import BlockingScheduler

from ingestion.workers.price_poller import run_once
from shared.config import settings

log = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(level=settings.log_level)
    interval = settings.poll_interval_seconds

    scheduler = BlockingScheduler(timezone="UTC")
    # Run immediately on boot, then every interval.
    scheduler.add_job(run_once, "interval", seconds=interval, next_run_time=None, id="poll")
    scheduler.add_job(run_once, "date", id="poll-now")  # one immediate kick

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: scheduler.shutdown(wait=False))

    log.info("ingestion scheduler starting; polling every %ss for hubs %s", interval, settings.hubs)
    scheduler.start()


if __name__ == "__main__":
    main()
