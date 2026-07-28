"""Per-route price history — the "why is this a deal?" view.

Returns the route, its observation time-series, all baseline tiers, and recent
deal markers so the front end can chart the price against the learned baseline.
"""
from __future__ import annotations

import uuid

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query

from api.deps import get_conn
from api.schemas import (
    BaselineOut,
    DealOut,
    ObservationPoint,
    RouteHistoryResponse,
    RouteOut,
)
from shared import db

router = APIRouter(prefix="/routes", tags=["routes"])


@router.get("/{route_id}", response_model=RouteOut)
def get_route(route_id: uuid.UUID, conn: psycopg.Connection = Depends(get_conn)) -> RouteOut:
    route = db.fetch_route(conn, str(route_id))
    if route is None:
        raise HTTPException(status_code=404, detail="route not found")
    return RouteOut(**route)


@router.get("/{route_id}/history", response_model=RouteHistoryResponse)
def get_route_history(
    route_id: uuid.UUID,
    days: int = Query(default=90, ge=1, le=365),
    limit: int = Query(default=2000, ge=1, le=10000, description="max observation points"),
    conn: psycopg.Connection = Depends(get_conn),
) -> RouteHistoryResponse:
    route = db.fetch_route(conn, str(route_id))
    if route is None:
        raise HTTPException(status_code=404, detail="route not found")
    observations = db.fetch_route_observations(conn, str(route_id), days=days, limit=limit)
    baselines = db.fetch_route_baselines(conn, str(route_id))
    deals = db.fetch_route_deals(conn, str(route_id), days=days, limit=200)
    return RouteHistoryResponse(
        route=RouteOut(**route),
        observations=[ObservationPoint(**o) for o in observations],
        baselines=[BaselineOut(**b) for b in baselines],
        deals=[DealOut(**d) for d in deals],
    )
