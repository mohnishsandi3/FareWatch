"""Pure watch-matching predicate (DB-free, unit-tested).

The matcher narrows candidate watches in SQL by origin, then applies this
predicate in Python so the matching rules have a single, testable home (no
duplicate logic drifting between SQL and code).
"""
from __future__ import annotations

from datetime import date


def watch_matches(
    watch: dict,
    *,
    destination: str,
    price: float,
    depart_date: date | None,
) -> bool:
    """Does this active, same-origin watch match the deal?

    - destination: a flexible watch (None) matches anywhere; otherwise exact.
    - max_price: None means no cap; otherwise the deal must be at or under it.
    - date window: if the deal has a depart_date it must fall within the watch's
      window; a deal with no depart_date can't be window-checked, so it matches.
    """
    wdest = watch.get("destination")
    if wdest is not None and wdest != destination:
        return False

    max_price = watch.get("max_price")
    if max_price is not None and price > float(max_price):
        return False

    if depart_date is not None:
        start = watch.get("date_window_start")
        end = watch.get("date_window_end")
        if start is not None and depart_date < start:
            return False
        if end is not None and depart_date > end:
            return False

    return True
