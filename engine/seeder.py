"""Phase 2 — cold-start baseline seeder.

Seeds route_baselines from the Travelpayouts month-matrix endpoint so the engine
can flag deals on day one instead of waiting weeks for native history to
accumulate (CLAUDE.md "Cold-start handling").

For each curated hub we discover popular destinations (city-directions), then for
each route pull the month-matrix (≈a month of daily prices), compute robust
stats (median/p10/MAD) per calendar-month bucket plus a global tier, and write
them with ``seeded=True``. Seeded baselines are capped at LOW confidence and are
overwritten by native data once it's dense enough (see engine.baselines).

Safe to re-run: a bucket that already has a native (seeded=False) baseline is
left untouched.

Run:  python -m engine.seeder
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date

from engine import baselines
from ingestion.hubs import active_hubs
from ingestion.travelpayouts_client import TravelpayoutsClient, TravelpayoutsError
from shared import db
from shared.config import settings

log = logging.getLogger(__name__)

# Need at least this many daily prices to seed a bucket's median/MAD meaningfully.
MIN_SEED_POINTS = 5


def _parse_date(value) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _seed_bucket(conn, route_id: str, month_bucket: int, prices: list[float]) -> bool:
    """Write a seeded baseline for one bucket unless a native one already exists."""
    existing = db.get_baseline(conn, route_id, month_bucket)
    if existing is not None and not existing["seeded"]:
        return False  # native data wins — never clobber it with a seed
    stats = baselines.compute_stats(prices)
    if stats is None:
        return False
    db.upsert_baseline(
        conn,
        route_id=route_id,
        month_bucket=month_bucket,
        median_price=stats.median_price,
        p10_price=stats.p10_price,
        mad=stats.mad,
        sample_size=stats.sample_size,
        seeded=True,
    )
    return True


def seed_route(client: TravelpayoutsClient, conn, origin: str, destination: str) -> dict:
    """Seed baselines for one route from its month-matrix. Returns stats."""
    result = {"buckets": 0, "points": 0}
    try:
        resp = client.month_matrix(origin, destination)
    except TravelpayoutsError as exc:
        log.warning("month_matrix %s-%s failed: %s", origin, destination, exc)
        return result

    by_bucket: dict[int, list[float]] = defaultdict(list)
    all_prices: list[float] = []
    for item in resp.get("data") or []:
        price = item.get("value") or item.get("price")
        d = _parse_date(item.get("depart_date"))
        if price is None or d is None:
            continue
        by_bucket[d.month].append(float(price))
        all_prices.append(float(price))

    if not all_prices:
        return result

    route_id = db.get_or_create_route(conn, origin, destination)
    for bucket, prices in by_bucket.items():
        if len(prices) < MIN_SEED_POINTS:
            continue
        if _seed_bucket(conn, route_id, bucket, prices):
            result["buckets"] += 1
    # Global tier across all sampled days.
    _seed_bucket(conn, route_id, baselines.GLOBAL_BUCKET, all_prices)
    conn.commit()

    result["points"] = len(all_prices)
    return result


def seed_all(limit_per_hub: int | None = None) -> None:
    """Seed baselines for popular destinations from every curated hub."""
    limit = settings.seed_limit_per_hub if limit_per_hub is None else limit_per_hub
    total = {"routes": 0, "buckets": 0}
    with TravelpayoutsClient() as client, db.get_conn() as conn:
        for origin in active_hubs():
            try:
                resp = client.city_directions(origin)
            except TravelpayoutsError as exc:
                log.error("city_directions %s failed: %s", origin, exc)
                continue
            dests = list((resp.get("data") or {}).keys())
            if limit:
                dests = dests[:limit]
            log.info("seeding %d routes from %s", len(dests), origin)
            for dest in dests:
                r = seed_route(client, conn, origin, dest)
                total["routes"] += 1
                total["buckets"] += r["buckets"]
    log.info("seed complete: %s", total)


if __name__ == "__main__":
    logging.basicConfig(level=settings.log_level)
    seed_all()
