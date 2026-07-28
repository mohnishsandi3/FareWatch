"""Watch management — list, create, deactivate.

Identity is by email for MVP (no auth yet): creating a watch upserts the user.
This is the only write surface in the read layer, kept deliberately small.
"""
from __future__ import annotations

import uuid

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query

from api.deps import get_conn
from api.schemas import WatchCreate, WatchOut
from shared import db

router = APIRouter(prefix="/watches", tags=["watches"])


@router.get("", response_model=list[WatchOut])
def list_watches(
    email: str = Query(description="owner's email"),
    include_inactive: bool = Query(default=False),
    conn: psycopg.Connection = Depends(get_conn),
) -> list[WatchOut]:
    user = db.get_user_by_email(conn, email)
    if user is None:
        return []
    rows = db.list_watches(conn, user_id=user["id"], include_inactive=include_inactive)
    return [WatchOut(**r) for r in rows]


@router.post("", response_model=WatchOut, status_code=201)
def create_watch(body: WatchCreate, conn: psycopg.Connection = Depends(get_conn)) -> WatchOut:
    user_id = db.create_user(conn, body.email)
    watch_id = db.create_watch(
        conn,
        user_id=user_id,
        origin=body.normalized_origin(),
        destination=body.normalized_destination(),
        max_price=body.max_price,
        date_window_start=body.date_window_start,
        date_window_end=body.date_window_end,
        flexible_dates=body.flexible_dates,
        cabin=body.cabin,
    )
    conn.commit()
    row = db.get_watch(conn, watch_id)
    if row is None:  # pragma: no cover — just committed it
        raise HTTPException(status_code=500, detail="watch not found after create")
    return WatchOut(**row)


@router.delete("/{watch_id}", status_code=204)
def deactivate_watch(
    watch_id: uuid.UUID,
    email: str = Query(description="owner's email (authorizes the delete)"),
    conn: psycopg.Connection = Depends(get_conn),
) -> None:
    user = db.get_user_by_email(conn, email)
    if user is None:
        raise HTTPException(status_code=404, detail="watch not found")
    ok = db.deactivate_watch(conn, watch_id=str(watch_id), user_id=user["id"])
    conn.commit()
    if not ok:
        raise HTTPException(status_code=404, detail="watch not found")
