"""Pure-logic tests for the matcher predicate (no DB/Redis)."""
from datetime import date

from matcher.matching import watch_matches


def _watch(**kw):
    base = dict(
        destination=None,
        max_price=None,
        date_window_start=date(2026, 6, 1),
        date_window_end=date(2026, 9, 1),
    )
    base.update(kw)
    return base


def test_flexible_destination_matches_anywhere():
    w = _watch(destination=None)
    assert watch_matches(w, destination="LON", price=300, depart_date=date(2026, 7, 1))
    assert watch_matches(w, destination="CDG", price=300, depart_date=date(2026, 7, 1))


def test_fixed_destination_must_match():
    w = _watch(destination="LON")
    assert watch_matches(w, destination="LON", price=300, depart_date=date(2026, 7, 1))
    assert not watch_matches(w, destination="CDG", price=300, depart_date=date(2026, 7, 1))


def test_max_price_cap():
    w = _watch(max_price=400)
    assert watch_matches(w, destination="LON", price=399, depart_date=date(2026, 7, 1))
    assert watch_matches(w, destination="LON", price=400, depart_date=date(2026, 7, 1))  # inclusive
    assert not watch_matches(w, destination="LON", price=401, depart_date=date(2026, 7, 1))


def test_no_max_price_means_no_cap():
    w = _watch(max_price=None)
    assert watch_matches(w, destination="LON", price=9999, depart_date=date(2026, 7, 1))


def test_date_window_bounds():
    w = _watch(date_window_start=date(2026, 6, 1), date_window_end=date(2026, 9, 1))
    assert watch_matches(w, destination="LON", price=300, depart_date=date(2026, 6, 1))   # start inclusive
    assert watch_matches(w, destination="LON", price=300, depart_date=date(2026, 9, 1))   # end inclusive
    assert not watch_matches(w, destination="LON", price=300, depart_date=date(2026, 5, 31))
    assert not watch_matches(w, destination="LON", price=300, depart_date=date(2026, 9, 2))


def test_deal_without_depart_date_skips_window_check():
    w = _watch()
    assert watch_matches(w, destination="LON", price=300, depart_date=None)
