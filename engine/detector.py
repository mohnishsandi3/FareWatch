"""Phase 2 — anomaly flagging + scoring.

A price is a deal only relative to what's normal for that route at that time. We
flag when an observed price falls below the route's p10 or several MADs under the
median, then attach:
  - ``deal_score`` — normalized "how good", for ranking the discovery feed.
  - ``confidence`` — high/medium/low from baseline tier + sample size + data
    freshness, honestly surfacing uneven, time-decaying coverage (CLAUDE.md).

The baseline hierarchy (per-month → global → none) is resolved in ``evaluate``;
the scoring decision in ``decide`` is pure and unit-tested.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from engine import baselines
from shared import db
from shared.models import DealEvent, PriceObservation

# Anomaly thresholds
MAD_MULTIPLIER = 3.0          # "several MADs under the median"

# Minimum samples to trust a tier as a baseline at all (single source of truth
# in baselines, reused here so detection and the recompute gate stay in sync).
MONTH_MIN_SAMPLES = baselines.MONTH_MIN_SAMPLES
GLOBAL_MIN_SAMPLES = baselines.GLOBAL_MIN_SAMPLES

# Confidence tiers, weakest → strongest
_LEVELS = ["low", "medium", "high"]


def _downgrade(level: str) -> str:
    i = _LEVELS.index(level)
    return _LEVELS[max(0, i - 1)]


@dataclass(frozen=True)
class Decision:
    is_deal: bool
    deal_score: float
    confidence: str
    baseline_median: float


def decide(
    *,
    price: float,
    tier: str,                 # "per_month" | "global"
    median: float,
    p10: float,
    mad: float,
    sample_size: int,
    is_stale: bool,
    seeded: bool = False,
) -> Decision | None:
    """Pure scoring. Returns a Decision (is_deal may be False) or None if the
    baseline is too thin in this tier to judge anything."""
    min_samples = MONTH_MIN_SAMPLES if tier == "per_month" else GLOBAL_MIN_SAMPLES
    if sample_size < min_samples or median <= 0:
        return None

    below_p10 = price <= p10
    below_mad = mad > 0 and price <= median - MAD_MULTIPLIER * mad
    is_deal = bool(below_p10 or below_mad)

    # Fractional discount vs the median, clamped to [0, 1].
    deal_score = max(0.0, min(1.0, (median - price) / median))

    confidence = _confidence(tier=tier, sample_size=sample_size, is_stale=is_stale, seeded=seeded)
    return Decision(is_deal=is_deal, deal_score=deal_score, confidence=confidence, baseline_median=median)


def _confidence(*, tier: str, sample_size: int, is_stale: bool, seeded: bool = False) -> str:
    # Cold-start seeds are cached aggregates, not native observations: cap at low
    # regardless of how many seed points they carry (CLAUDE.md).
    if seeded:
        return "low"
    if tier == "per_month":
        level = "high" if sample_size >= 20 else "medium"
    else:  # global fallback is inherently less specific
        level = "medium" if sample_size >= 15 else "low"
    if is_stale:
        level = _downgrade(level)
    return level


def evaluate(conn, obs: PriceObservation, *, now: datetime | None = None) -> DealEvent | None:
    """Resolve the baseline hierarchy for this observation and emit a DealEvent
    if it qualifies. Returns None when not a deal or no usable baseline exists."""
    now = now or datetime.now(timezone.utc)
    route_id = db.get_or_create_route(conn, obs.origin, obs.destination)

    bucket = baselines.month_bucket_of(obs.depart_date)
    is_stale = obs.source_expires_at is not None and obs.source_expires_at < now

    # Tier 1: per-month baseline (if departure month known and dense enough).
    decision: Decision | None = None
    if bucket is not None:
        b = db.get_baseline(conn, route_id, bucket)
        if b and b["median_price"] is not None:
            decision = decide(
                price=obs.price,
                tier="per_month",
                median=b["median_price"],
                p10=b["p10_price"],
                mad=b["mad"] or 0.0,
                sample_size=b["sample_size"],
                is_stale=is_stale,
                seeded=b.get("seeded", False),
            )

    # Tier 2: global fallback.
    if decision is None:
        g = db.get_baseline(conn, route_id, baselines.GLOBAL_BUCKET)
        if g and g["median_price"] is not None:
            decision = decide(
                price=obs.price,
                tier="global",
                median=g["median_price"],
                p10=g["p10_price"],
                mad=g["mad"] or 0.0,
                sample_size=g["sample_size"],
                is_stale=is_stale,
                seeded=g.get("seeded", False),
            )

    if decision is None or not decision.is_deal:
        return None

    return DealEvent(
        route_origin=obs.origin,
        route_destination=obs.destination,
        price=obs.price,
        depart_date=obs.depart_date,
        return_date=obs.return_date,
        baseline_median=decision.baseline_median,
        deal_score=decision.deal_score,
        confidence=decision.confidence,
        detected_at=now,
        expires_at=obs.source_expires_at,
    )
