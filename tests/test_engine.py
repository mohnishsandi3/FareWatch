"""Pure-logic tests for the detection engine (no DB/Redis)."""
from datetime import date

import pytest

from engine import baselines, detector


# --- baselines.compute_stats ------------------------------------------------
def test_compute_stats_basic():
    s = baselines.compute_stats([100, 200, 300, 400, 500])
    assert s is not None
    assert s.median_price == 300
    assert s.sample_size == 5
    # MAD = median(|x - 300|) = median(200,100,0,100,200) = 100
    assert s.mad == 100


def test_compute_stats_robust_to_outlier():
    # One absurd fare must not drag the center the way a mean would.
    s = baselines.compute_stats([300, 310, 290, 305, 9999])
    assert 290 <= s.median_price <= 310


def test_compute_stats_empty_is_none():
    assert baselines.compute_stats([]) is None


def test_month_bucket_of():
    assert baselines.month_bucket_of(date(2026, 7, 14)) == 7
    assert baselines.month_bucket_of(None) is None


# --- detector.decide --------------------------------------------------------
def _baseline(sample_size=25, **kw):
    return dict(median=400.0, p10=300.0, mad=40.0, sample_size=sample_size, **kw)


def test_thin_baseline_returns_none():
    # Below the per-month minimum sample count -> can't judge.
    assert detector.decide(price=250, tier="per_month", sample_size=3,
                           median=400, p10=300, mad=40, is_stale=False) is None


def test_clear_deal_below_p10():
    d = detector.decide(price=250, tier="per_month", is_stale=False, **_baseline())
    assert d is not None and d.is_deal is True
    # Fractional discount vs median 400 -> (400-250)/400 = 0.375
    assert d.deal_score == pytest.approx(0.375)


def test_deal_via_mad_threshold():
    # Not below p10 (300) but >3 MAD under median: 400 - 3*40 = 280; price 270 qualifies.
    d = detector.decide(price=270, tier="per_month", is_stale=False, **_baseline())
    assert d.is_deal is True


def test_normal_price_is_not_a_deal():
    d = detector.decide(price=390, tier="per_month", is_stale=False, **_baseline())
    assert d is not None and d.is_deal is False
    assert d.deal_score == pytest.approx((400 - 390) / 400)


def test_confidence_high_for_dense_per_month():
    d = detector.decide(price=250, tier="per_month", is_stale=False, **_baseline(sample_size=25))
    assert d.confidence == "high"


def test_confidence_downgraded_when_stale():
    fresh = detector.decide(price=250, tier="per_month", is_stale=False, **_baseline(sample_size=25))
    stale = detector.decide(price=250, tier="per_month", is_stale=True, **_baseline(sample_size=25))
    assert fresh.confidence == "high" and stale.confidence == "medium"


def test_global_tier_is_lower_confidence():
    d = detector.decide(price=250, tier="global", is_stale=False,
                        median=400, p10=300, mad=40, sample_size=10)
    assert d.confidence == "low"  # global + <15 samples


def test_seeded_baseline_is_always_low_confidence():
    # Even a dense per-month seed (would be "high" if native) stays low.
    d = detector.decide(price=250, tier="per_month", is_stale=False, seeded=True,
                        **_baseline(sample_size=30))
    assert d is not None and d.is_deal is True
    assert d.confidence == "low"


def test_seeded_still_detects_the_deal():
    # Seeding affects confidence, not whether the price qualifies as a deal.
    d = detector.decide(price=390, tier="per_month", is_stale=False, seeded=True,
                        **_baseline(sample_size=30))
    assert d is not None and d.is_deal is False
