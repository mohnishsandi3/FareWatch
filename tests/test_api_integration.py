"""Integration tests for the read API (FastAPI TestClient + live Postgres).

SKIPPED unless you opt in (needs Postgres with migrations 0001-0003 applied):

    # PowerShell
    $env:FAREWATCH_INTEGRATION = "1"; pytest -q tests/test_api_integration.py

Exercises the endpoint wiring + SQL the pure suite can't reach.
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
def client():
    try:
        from fastapi.testclient import TestClient

        from api.main import app
        from shared import db

        # Probe the DB so we skip cleanly (not error) when it's unreachable.
        with db.get_conn() as c:
            with c.cursor() as cur:
                cur.execute("SELECT 1")
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"API/Postgres not reachable: {exc}")
    return TestClient(app)


@pytest.fixture()
def chain():
    """Insert user + route + a fresh deal; clean up afterwards."""
    from shared import db

    created = {}
    with db.get_conn() as conn:
        email = f"apitest+{uuid.uuid4().hex[:8]}@example.com"
        price = 100.0 + random.randint(1, 100000) / 100.0
        user_id = db.create_user(conn, email)
        route_id = db.get_or_create_route(conn, "AAA", "BBB")
        deal_id = db.insert_deal(
            conn, route_id=route_id, price=price, depart_date=date(2026, 8, 1),
            return_date=None, baseline_median=400.0, deal_score=0.6,
            confidence="high", detected_at=datetime.now(timezone.utc), expires_at=None,
        )
        conn.commit()
        created.update(email=email, user_id=user_id, route_id=route_id, deal_id=deal_id, price=price)
    yield created
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM notifications WHERE user_id = %s", (created["user_id"],))
            cur.execute("DELETE FROM deals WHERE id = %s", (created["deal_id"],))
            cur.execute("DELETE FROM watches WHERE user_id = %s", (created["user_id"],))
            cur.execute("DELETE FROM users WHERE id = %s", (created["user_id"],))
        conn.commit()


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_feed_returns_the_deal(client, chain):
    r = client.get("/feed", params={"origin": "AAA", "recency_days": 1, "limit": 100})
    assert r.status_code == 200
    body = r.json()
    mine = [d for d in body["items"] if d["id"] == chain["deal_id"]]
    assert len(mine) == 1
    assert mine[0]["destination"] == "BBB"
    assert mine[0]["price"] == pytest.approx(chain["price"])


def test_feed_max_price_filters(client, chain):
    # max_price below our deal's price -> excluded.
    r = client.get("/feed", params={"origin": "AAA", "max_price": 1.0, "recency_days": 1})
    assert r.status_code == 200
    assert all(d["id"] != chain["deal_id"] for d in r.json()["items"])


def test_watch_create_list_delete_roundtrip(client, chain):
    # Create.
    r = client.post("/watches", json={
        "email": chain["email"], "origin": "AAA", "destination": None,
        "max_price": 500, "date_window_start": "2026-06-01",
        "date_window_end": "2026-09-01",
    })
    assert r.status_code == 201, r.text
    watch = r.json()
    assert watch["origin"] == "AAA" and watch["active"] is True

    # List shows it.
    r = client.get("/watches", params={"email": chain["email"]})
    assert r.status_code == 200
    assert any(w["id"] == watch["id"] for w in r.json())

    # Delete (deactivate).
    r = client.delete(f"/watches/{watch['id']}", params={"email": chain["email"]})
    assert r.status_code == 204

    # No longer in the active list.
    r = client.get("/watches", params={"email": chain["email"]})
    assert all(w["id"] != watch["id"] for w in r.json())


def test_route_history(client, chain):
    r = client.get(f"/routes/{chain['route_id']}/history", params={"days": 90})
    assert r.status_code == 200
    body = r.json()
    assert body["route"]["origin"] == "AAA"
    assert any(d["id"] == chain["deal_id"] for d in body["deals"])


def test_route_history_404_for_unknown_route(client):
    r = client.get(f"/routes/{uuid.uuid4()}/history")
    assert r.status_code == 404
