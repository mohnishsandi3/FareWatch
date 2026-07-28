"""Discovery feed — the core of v1: "best deals anywhere from my city".

Ranks recent, non-expired deals by deal_score then confidence, one card per
route. All filters are optional so the same endpoint serves the global feed and
a city-scoped feed.
"""
from __future__ import annotations

import psycopg
from fastapi import APIRouter, Depends, Query

from api.deps import get_conn
from api.filtering import confidence_at_least
from api.schemas import DealOut, FeedResponse
from shared import db

router = APIRouter(prefix="/feed", tags=["feed"])


@router.get("", response_model=FeedResponse)
def get_feed(
    origin: str | None = Query(default=None, min_length=3, max_length=3, description="IATA origin, e.g. BOS"),
    destination: str | None = Query(default=None, min_length=3, max_length=3),
    max_price: float | None = Query(default=None, gt=0),
    min_confidence: str | None = Query(
        default=None, description="high | medium | low — minimum confidence to include"
    ),
    recency_days: int = Query(default=7, ge=1, le=90, description="only deals detected within N days"),
    limit: int = Query(default=50, ge=1, le=200),
    conn: psycopg.Connection = Depends(get_conn),
) -> FeedResponse:
    rows = db.fetch_feed(
        conn,
        origin=origin,
        destination=destination,
        max_price=max_price,
        confidence_levels=confidence_at_least(min_confidence),
        recency_days=recency_days,
        limit=limit,
    )
    items = [DealOut(**r) for r in rows]
    return FeedResponse(count=len(items), items=items)
