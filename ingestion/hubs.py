"""Curated origin hubs to poll.

Start small and dense (CLAUDE.md): a handful of major US cities so the cached
data is rich and polling stays cheap. Expand only after measuring call volume.
The active list comes from the ORIGIN_HUBS env var (see shared.config).
"""
from __future__ import annotations

from shared.config import settings

# Human-readable reference for the default set; the source of truth is the env.
KNOWN_HUBS = {
    "BOS": "Boston",
    "JFK": "New York (JFK)",
    "LAX": "Los Angeles",
    "ORD": "Chicago (O'Hare)",
    "SFO": "San Francisco",
}


def active_hubs() -> list[str]:
    return settings.hubs
