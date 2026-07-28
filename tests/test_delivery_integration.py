"""Integration tests for notification-delivery hardening.

Requires a live Postgres (migrations 0001-0003 applied). SKIPPED unless you opt
in, so the default ``pytest -q`` stays pure:

    # PowerShell
    $env:FAREWATCH_INTEGRATION = "1"; pytest -q tests/test_delivery_integration.py

These exercise the orphan-recovery + idempotency paths that the pure suite can't
cover (they're DB-bound by design).
"""
from __future__ import annotations

import os
import random
import uuid
from datetime import date, datetime, timezone

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("FAREWATCH_INTEGRATION") != "1",
    reason="set FAREWATCH_INTEGRATION=1 (needs Postgres) to run",
)


@pytest.fixture()
def conn():
    from shared import db

    try:
        c = db.get_pool().getconn()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Postgres not reachable: {exc}")
    try:
        yield c
    finally:
        db.get_pool().putconn(c)


def _make_chain(conn) -> dict:
    """Create user + route + deal + pending notification. Returns ids/values."""
    from shared import db

    email = f"itest+{uuid.uuid4().hex[:8]}@example.com"
    price = 100.0 + random.randint(1, 100000) / 100.0  # unique-ish -> fresh deal
    user_id = db.create_user(conn, email)
    route_id = db.get_or_create_route(conn, "ITA", "ITB")
    deal_id = db.insert_deal(
        conn,
        route_id=route_id,
        price=price,
        depart_date=date(2026, 8, 1),
        return_date=None,
        baseline_median=400.0,
        deal_score=0.4,
        confidence="high",
        detected_at=datetime.now(timezone.utc),
        expires_at=None,
    )
    notif_id = db.create_notification(conn, user_id=user_id, deal_id=deal_id, channel="email")
    conn.commit()
    return {
        "email": email, "user_id": user_id, "route_id": route_id,
        "deal_id": deal_id, "notif_id": notif_id, "price": price,
    }


def _cleanup(conn, chain: dict) -> None:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM notifications WHERE id = %s", (chain["notif_id"],))
        cur.execute("DELETE FROM deals WHERE id = %s", (chain["deal_id"],))
        cur.execute("DELETE FROM users WHERE id = %s", (chain["user_id"],))
    conn.commit()


def test_sweeper_republishes_orphaned_pending(conn):
    from shared import db

    chain = _make_chain(conn)
    try:
        # Pending row exists but its stream message was "lost" (never published).
        msgs = db.sweep_republishable(conn, grace_seconds=0, lease_seconds=1, limit=50)
        conn.commit()
        mine = [m for m in msgs if m["notification_id"] == chain["notif_id"]]
        assert len(mine) == 1
        m = mine[0]
        assert m["email"] == chain["email"]
        assert m["origin"] == "ITA" and m["destination"] == "ITB"
        assert m["price"] == pytest.approx(chain["price"])
    finally:
        _cleanup(conn, chain)


def test_notifier_delivery_is_idempotent(conn):
    from shared import db
    from notifier.consumer import process_notification

    chain = _make_chain(conn)
    payload = {
        "notification_id": chain["notif_id"],
        "user_id": chain["user_id"],
        "email": chain["email"],
        "deal_id": chain["deal_id"],
        "channel": "email",
        "origin": "ITA",
        "destination": "ITB",
        "price": chain["price"],
        "depart_date": "2026-08-01",
        "return_date": None,
        "deal_score": 0.4,
        "confidence": "high",
    }
    try:
        # First delivery: claims, sends, marks sent.
        process_notification(payload)
        assert db.get_notification_status(conn, chain["notif_id"]) == "sent"
        with conn.cursor() as cur:
            cur.execute("SELECT attempts FROM notifications WHERE id = %s", (chain["notif_id"],))
            attempts_after_first = cur.fetchone()[0]
        assert attempts_after_first == 1

        # Duplicate delivery (e.g. sweeper re-published): must NOT re-send.
        process_notification(payload)
        assert db.get_notification_status(conn, chain["notif_id"]) == "sent"
        with conn.cursor() as cur:
            cur.execute("SELECT attempts FROM notifications WHERE id = %s", (chain["notif_id"],))
            assert cur.fetchone()[0] == 1  # unchanged -> no second claim/send
    finally:
        _cleanup(conn, chain)
