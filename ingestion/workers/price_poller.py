"""Phase 1 ingestion worker: poll cheapest directions per hub, write history.

For each curated origin hub we make ONE call to ``/v1/city-directions`` (many
destinations per call), then for each destination:
  1. resolve/create the route,
  2. insert the observation idempotently (per-window dedup at the DB),
  3. publish it to ``stream:observations`` for the detection engine.

No detection here — the goal is a clean, growing, deduplicated history.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone

from ingestion.hubs import active_hubs
from ingestion.travelpayouts_client import TravelpayoutsClient, TravelpayoutsError
from shared import db, streams
from shared.config import settings
from shared.models import PriceObservation

log = logging.getLogger(__name__)


def _bucket(now: datetime) -> datetime:
    """Floor ``now`` to the polling-window granularity for observation dedup."""
    secs = settings.obs_bucket_seconds
    epoch = int(now.timestamp())
    return datetime.fromtimestamp(epoch - (epoch % secs), tz=timezone.utc)


def _parse_date(value) -> date | None:
    if not value:
        return None
    try:
        # API returns ISO datetimes like "2026-07-14T10:20:00+03:00" or "2026-07".
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _parse_dt(value) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def poll_hub(client: TravelpayoutsClient, origin: str) -> dict[str, int]:
    """Poll one origin hub. Returns counts for logging/metrics."""
    now = datetime.now(timezone.utc)
    bucket = _bucket(now)
    stats = {"seen": 0, "written": 0, "duplicate": 0, "published": 0}

    try:
        resp = client.city_directions(origin)
    except TravelpayoutsError as exc:
        log.error("city_directions failed for %s: %s", origin, exc)
        return stats

    data = resp.get("data") or {}
    currency = resp.get("currency", settings.default_currency)

    with db.get_conn() as conn:
        for destination, item in data.items():
            stats["seen"] += 1
            price = item.get("price") or item.get("value")
            if price is None:
                continue

            depart = _parse_date(item.get("depart_date") or item.get("departure_at"))
            ret = _parse_date(item.get("return_date") or item.get("return_at"))
            transfers = int(item.get("transfers") or item.get("number_of_changes") or 0)
            expires = _parse_dt(item.get("expires_at"))

            route_id = db.get_or_create_route(conn, origin, destination)
            wrote = db.insert_observation(
                conn,
                route_id=route_id,
                depart_date=depart,
                return_date=ret,
                price=float(price),
                currency=currency,
                transfers=transfers,
                observed_at=now,
                obs_bucket=bucket,
                source_expires_at=expires,
            )
            conn.commit()

            if not wrote:
                stats["duplicate"] += 1
                continue
            stats["written"] += 1

            obs = PriceObservation(
                origin=origin,
                destination=destination,
                depart_date=depart,
                return_date=ret,
                price=float(price),
                currency=currency,
                transfers=transfers,
                observed_at=now,
                obs_bucket=bucket,
                source_expires_at=expires,
            )
            streams.publish(streams.OBSERVATIONS, obs.model_dump())
            stats["published"] += 1

    log.info("hub %s: %s", origin, stats)
    return stats


def run_once() -> None:
    """One full pass across all curated hubs."""
    with TravelpayoutsClient() as client:
        for origin in active_hubs():
            poll_hub(client, origin)


if __name__ == "__main__":
    logging.basicConfig(level=settings.log_level)
    run_once()
