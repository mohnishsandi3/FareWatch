"""Pure tests for the read layer (no DB/Redis/FastAPI app needed).

Covers the confidence-tier expansion and the WatchCreate request validation —
the bits of logic worth pinning down. Endpoint wiring is exercised by the
guarded integration tests in test_api_integration.py.
"""
from datetime import date

import pytest
from pydantic import ValidationError

from api.filtering import confidence_at_least
from api.schemas import DealOut, WatchCreate


def test_confidence_at_least_expands_tiers():
    assert confidence_at_least("high") == ["high"]
    assert confidence_at_least("medium") == ["high", "medium"]
    assert confidence_at_least("low") == ["high", "medium", "low"]


def test_confidence_at_least_is_case_insensitive():
    assert confidence_at_least("MEDIUM") == ["high", "medium"]


def test_confidence_at_least_none_or_unknown_means_no_filter():
    assert confidence_at_least(None) is None
    assert confidence_at_least("") is None
    assert confidence_at_least("bogus") is None


def test_dealout_pct_below_baseline():
    d = DealOut(
        id="1", route_id="r1", origin="BOS", destination="LON", price=300.0,
        baseline_median=400.0, deal_score=0.25, confidence="high",
        detected_at="2026-06-01T00:00:00Z",
    )
    assert d.pct_below_baseline == 25.0


def test_dealout_pct_below_baseline_handles_missing_baseline():
    d = DealOut(
        id="1", route_id="r1", origin="BOS", destination="LON", price=300.0,
        baseline_median=None, deal_score=0.25, confidence="high",
        detected_at="2026-06-01T00:00:00Z",
    )
    assert d.pct_below_baseline is None


def test_watchcreate_normalizes_iata():
    w = WatchCreate(
        email="a@b.com", origin="bos", destination="lon",
        date_window_start=date(2026, 6, 1), date_window_end=date(2026, 9, 1),
    )
    assert w.normalized_origin() == "BOS"
    assert w.normalized_destination() == "LON"


def test_watchcreate_flexible_destination_allowed():
    w = WatchCreate(
        email="a@b.com", origin="BOS", destination=None,
        date_window_start=date(2026, 6, 1), date_window_end=date(2026, 9, 1),
    )
    assert w.normalized_destination() is None


def test_watchcreate_rejects_inverted_window():
    with pytest.raises(ValidationError):
        WatchCreate(
            email="a@b.com", origin="BOS",
            date_window_start=date(2026, 9, 1), date_window_end=date(2026, 6, 1),
        )


def test_watchcreate_rejects_bad_email():
    with pytest.raises(ValidationError):
        WatchCreate(
            email="not-an-email", origin="BOS",
            date_window_start=date(2026, 6, 1), date_window_end=date(2026, 9, 1),
        )


def test_watchcreate_rejects_nonpositive_max_price():
    with pytest.raises(ValidationError):
        WatchCreate(
            email="a@b.com", origin="BOS", max_price=0,
            date_window_start=date(2026, 6, 1), date_window_end=date(2026, 9, 1),
        )
