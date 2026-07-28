"""Unit tests for ingestion-side observation logic (no DB/Redis needed)."""
from datetime import date, datetime, timezone

from ingestion.workers.price_poller import _bucket, _parse_date, _parse_dt
from shared.models import PriceObservation


def test_bucket_floors_to_window():
    # 10800s = 3h windows. 01:30 UTC -> floors to 00:00 UTC.
    t = datetime(2026, 6, 1, 1, 30, tzinfo=timezone.utc)
    b = _bucket(t)
    assert b.hour % 3 == 0 and b.minute == 0 and b.second == 0
    assert b <= t


def test_parse_date_handles_iso_datetime_and_none():
    assert _parse_date("2026-07-14T10:20:00+03:00") == date(2026, 7, 14)
    assert _parse_date("2026-07") is None  # month-only is not a full date
    assert _parse_date(None) is None


def test_parse_dt_handles_z_suffix():
    assert _parse_dt("2026-07-14T10:20:00Z") == datetime(2026, 7, 14, 10, 20, tzinfo=timezone.utc)
    assert _parse_dt(None) is None


def test_dedup_key_stable_and_window_sensitive():
    base = dict(
        origin="BOS",
        destination="LON",
        depart_date=date(2026, 8, 1),
        return_date=None,
        price=412.0,
        currency="usd",
        transfers=1,
        observed_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
    )
    w1 = datetime(2026, 6, 1, 0, tzinfo=timezone.utc)
    w2 = datetime(2026, 6, 1, 3, tzinfo=timezone.utc)
    a = PriceObservation(obs_bucket=w1, **base)
    b = PriceObservation(obs_bucket=w1, **base)
    c = PriceObservation(obs_bucket=w2, **base)
    assert a.dedup_key() == b.dedup_key()      # same window -> same key (dedup)
    assert a.dedup_key() != c.dedup_key()      # later window -> new key (wanted)
