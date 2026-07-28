"""Pure filter helpers for the read layer (no FastAPI/DB imports).

Kept separate so the confidence-tier logic is unit-testable without a running
app or database.
"""
from __future__ import annotations

# Best-first order; mirrors the Postgres `confidence_level` enum definition.
CONFIDENCE_ORDER: list[str] = ["high", "medium", "low"]


def confidence_at_least(min_level: str | None) -> list[str] | None:
    """Expand a minimum confidence into the set of acceptable levels.

    ``"medium"`` -> ``["high", "medium"]``; ``None`` (or unknown) -> ``None``
    meaning "no filter". Used by the feed endpoint to translate a single query
    param into a SQL ``= ANY(...)`` list.
    """
    if not min_level:
        return None
    level = min_level.lower()
    if level not in CONFIDENCE_ORDER:
        return None
    return CONFIDENCE_ORDER[: CONFIDENCE_ORDER.index(level) + 1]
