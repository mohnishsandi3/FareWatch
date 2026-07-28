"""Phase 2 — robust baselines (median + MAD) with seasonality.

Baselines describe what's "normal" for a route. We use **median and
median-absolute-deviation (MAD)**, not mean/stdev: fares are right-skewed and
full of outliers that wreck a mean (CLAUDE.md).

Seasonality: baselines are bucketed by calendar month of departure. The engine
maintains, per route:
  - one baseline per observed month_bucket (1-12), and
  - one global baseline (month_bucket = 0) as a fallback tier for thin months.

The pure stats functions below are DB-free and unit-tested; ``recompute_route``
is the I/O wrapper that reads the rolling window and writes route_baselines.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np

from shared import db

GLOBAL_BUCKET = db.GLOBAL_BUCKET  # 0
DEFAULT_WINDOW_DAYS = 90

# Minimum native samples for a tier to be trusted as a baseline. Also the gate
# for overwriting a seeded baseline: native data only replaces a seed once it is
# this dense (otherwise the cold-start seed is preserved). Single source of
# truth — the detector imports these.
MONTH_MIN_SAMPLES = 8
GLOBAL_MIN_SAMPLES = 5


@dataclass(frozen=True)
class BaselineStats:
    median_price: float
    p10_price: float
    mad: float
    sample_size: int


def compute_stats(prices: list[float]) -> BaselineStats | None:
    """Robust summary of a price sample. Returns None if empty."""
    if not prices:
        return None
    arr = np.asarray(prices, dtype=float)
    median = float(np.median(arr))
    p10 = float(np.percentile(arr, 10))
    mad = float(np.median(np.abs(arr - median)))
    return BaselineStats(median_price=median, p10_price=p10, mad=mad, sample_size=int(arr.size))


def month_bucket_of(d: date | None) -> int | None:
    """Calendar-month bucket (1-12) for a departure date, or None if unknown."""
    return d.month if d is not None else None


def recompute_route(conn, route_id: str, *, window_days: int = DEFAULT_WINDOW_DAYS) -> None:
    """Recompute and persist native baselines for one route.

    Refreshes the global tier plus every month bucket with enough native data in
    the window. A tier is only written (seeded=False) once native samples reach
    its minimum — below that we skip, preserving any cold-start seed. Cheap given
    the curated-hub data volume; called after processing an observation.
    """
    # Global tier (all months, includes null-depart rows).
    global_stats = compute_stats(db.fetch_window_prices(conn, route_id, window_days=window_days))
    if global_stats is not None and global_stats.sample_size >= GLOBAL_MIN_SAMPLES:
        db.upsert_baseline(
            conn,
            route_id=route_id,
            month_bucket=GLOBAL_BUCKET,
            median_price=global_stats.median_price,
            p10_price=global_stats.p10_price,
            mad=global_stats.mad,
            sample_size=global_stats.sample_size,
            seeded=False,
        )

    # Per-month tiers.
    for bucket in range(1, 13):
        prices = db.fetch_window_prices(conn, route_id, window_days=window_days, month_bucket=bucket)
        stats = compute_stats(prices)
        if stats is None or stats.sample_size < MONTH_MIN_SAMPLES:
            continue
        db.upsert_baseline(
            conn,
            route_id=route_id,
            month_bucket=bucket,
            median_price=stats.median_price,
            p10_price=stats.p10_price,
            mad=stats.mad,
            sample_size=stats.sample_size,
            seeded=False,
        )
    conn.commit()
