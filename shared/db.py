"""Postgres access helpers (psycopg 3).

A tiny connection-pool wrapper plus the Phase 1 write path: resolve a route and
insert an observation idempotently. Detection-engine queries live in engine/.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from typing import Iterator

import psycopg
from psycopg_pool import ConnectionPool

from shared.config import settings

_pool: ConnectionPool | None = None


def get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(settings.database_url, min_size=1, max_size=5, open=True)
    return _pool


@contextmanager
def get_conn() -> Iterator[psycopg.Connection]:
    with get_pool().connection() as conn:
        yield conn


def get_or_create_route(conn: psycopg.Connection, origin: str, destination: str) -> str:
    """Return routes.id, inserting the pair if new. Idempotent via UNIQUE."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO routes (origin, destination)
            VALUES (%s, %s)
            ON CONFLICT (origin, destination) DO UPDATE SET origin = EXCLUDED.origin
            RETURNING id
            """,
            (origin.upper(), destination.upper()),
        )
        return cur.fetchone()[0]


def insert_observation(
    conn: psycopg.Connection,
    *,
    route_id: str,
    depart_date,
    return_date,
    price: float,
    currency: str,
    transfers: int,
    observed_at: datetime,
    obs_bucket: datetime,
    source_expires_at: datetime | None,
) -> bool:
    """Insert one observation. Returns True if a new row was written, False if
    it collided with the per-window unique constraint (already recorded)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO price_observations
                (route_id, depart_date, return_date, price, currency,
                 transfers, observed_at, obs_bucket, source_expires_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT ON CONSTRAINT uq_observation DO NOTHING
            RETURNING id
            """,
            (
                route_id,
                depart_date,
                return_date,
                price,
                currency,
                transfers,
                observed_at,
                obs_bucket,
                source_expires_at,
            ),
        )
        return cur.fetchone() is not None


# ---------------------------------------------------------------------------
# Engine (Phase 2) read/write helpers
# ---------------------------------------------------------------------------
GLOBAL_BUCKET = 0  # month_bucket value for the all-month fallback tier


def fetch_window_prices(
    conn: psycopg.Connection,
    route_id: str,
    *,
    window_days: int,
    month_bucket: int | None = None,
) -> list[float]:
    """Prices for a route over the rolling window.

    When ``month_bucket`` is given (1-12), restrict to observations whose
    ``depart_date`` falls in that calendar month (seasonality). When None,
    return everything in the window (the global fallback tier).
    """
    sql = [
        "SELECT price FROM price_observations",
        "WHERE route_id = %s",
        "AND observed_at >= now() - make_interval(days => %s)",
    ]
    params: list = [route_id, window_days]
    if month_bucket is not None:
        sql.append("AND depart_date IS NOT NULL AND EXTRACT(MONTH FROM depart_date) = %s")
        params.append(month_bucket)
    with conn.cursor() as cur:
        cur.execute(" ".join(sql), params)
        return [float(r[0]) for r in cur.fetchall()]


def upsert_baseline(
    conn: psycopg.Connection,
    *,
    route_id: str,
    month_bucket: int,
    median_price: float,
    p10_price: float,
    mad: float,
    sample_size: int,
    seeded: bool = False,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO route_baselines
                (route_id, month_bucket, median_price, p10_price, mad, sample_size, seeded, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, now())
            ON CONFLICT (route_id, month_bucket) DO UPDATE SET
                median_price = EXCLUDED.median_price,
                p10_price    = EXCLUDED.p10_price,
                mad          = EXCLUDED.mad,
                sample_size  = EXCLUDED.sample_size,
                seeded       = EXCLUDED.seeded,
                updated_at   = now()
            """,
            (route_id, month_bucket, median_price, p10_price, mad, sample_size, seeded),
        )


def get_baseline(conn: psycopg.Connection, route_id: str, month_bucket: int) -> dict | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT median_price, p10_price, mad, sample_size, seeded
            FROM route_baselines
            WHERE route_id = %s AND month_bucket = %s
            """,
            (route_id, month_bucket),
        )
        row = cur.fetchone()
    if row is None:
        return None
    return {
        "median_price": float(row[0]) if row[0] is not None else None,
        "p10_price": float(row[1]) if row[1] is not None else None,
        "mad": float(row[2]) if row[2] is not None else None,
        "sample_size": int(row[3]),
        "seeded": bool(row[4]),
    }


def insert_deal(
    conn: psycopg.Connection,
    *,
    route_id: str,
    price: float,
    depart_date,
    return_date,
    baseline_median: float | None,
    deal_score: float,
    confidence: str,
    detected_at,
    expires_at,
) -> str | None:
    """Insert a deal. Returns the new deal id, or None if it collided with
    uq_deal (already recorded) — the DB unique constraint is the dedup backstop."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO deals
                (route_id, price, depart_date, return_date, baseline_median,
                 deal_score, confidence, detected_at, expires_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT ON CONSTRAINT uq_deal DO NOTHING
            RETURNING id
            """,
            (
                route_id,
                price,
                depart_date,
                return_date,
                baseline_median,
                deal_score,
                confidence,
                detected_at,
                expires_at,
            ),
        )
        row = cur.fetchone()
        return str(row[0]) if row is not None else None


# ---------------------------------------------------------------------------
# Phase 3 — users, watches, notifications
# ---------------------------------------------------------------------------
def create_user(conn: psycopg.Connection, email: str, home_origin: str | None = None) -> str:
    """Idempotent on email. Returns the user id."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO users (email, home_origin)
            VALUES (%s, %s)
            ON CONFLICT (email) DO UPDATE SET home_origin = COALESCE(EXCLUDED.home_origin, users.home_origin)
            RETURNING id
            """,
            (email.lower(), home_origin),
        )
        return str(cur.fetchone()[0])


def create_watch(
    conn: psycopg.Connection,
    *,
    user_id: str,
    origin: str,
    destination: str | None,
    max_price: float | None,
    date_window_start,
    date_window_end,
    flexible_dates: bool = True,
    cabin: str = "economy",
) -> str:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO watches
                (user_id, origin, destination, max_price, date_window_start,
                 date_window_end, flexible_dates, cabin)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                user_id,
                origin.upper(),
                destination.upper() if destination else None,
                max_price,
                date_window_start,
                date_window_end,
                flexible_dates,
                cabin,
            ),
        )
        return str(cur.fetchone()[0])


def find_active_watches_for_origin(conn: psycopg.Connection, origin: str) -> list[dict]:
    """Active watches for an origin (coarse filter; precise matching is applied
    in Python so the predicate has a single, testable home). Joins the user's
    email so the notifier needs no extra lookup."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT w.id, w.user_id, u.email, w.destination, w.max_price,
                   w.date_window_start, w.date_window_end, w.flexible_dates, w.cabin
            FROM watches w
            JOIN users u ON u.id = w.user_id
            WHERE w.active AND w.origin = %s
            """,
            (origin.upper(),),
        )
        cols = [c.name for c in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def create_notification(
    conn: psycopg.Connection, *, user_id: str, deal_id: str, channel: str
) -> str | None:
    """Insert a pending ledger row. Returns the id if newly created, or None if
    (user, deal, channel) already exists — the UNIQUE constraint IS the dedup
    guarantee, so None means 'already alerted, do not resend'."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO notifications (user_id, deal_id, channel, status)
            VALUES (%s, %s, %s, 'pending')
            ON CONFLICT (user_id, deal_id, channel) DO NOTHING
            RETURNING id
            """,
            (user_id, deal_id, channel),
        )
        row = cur.fetchone()
        return str(row[0]) if row is not None else None


def get_notification_status(conn: psycopg.Connection, notification_id: str) -> str | None:
    with conn.cursor() as cur:
        cur.execute("SELECT status FROM notifications WHERE id = %s", (notification_id,))
        row = cur.fetchone()
        return row[0] if row else None


def claim_notification(
    conn: psycopg.Connection, notification_id: str, *, max_attempts: int
) -> str:
    """Atomically lease a notification for delivery.

    Transitions pending -> sending and increments attempts, all in one
    row-locked UPDATE so concurrent/duplicate stream messages can't both deliver.
    Returns:
      - "claimed": this worker owns delivery, go send;
      - "skip":    not pending (already sent, or in flight elsewhere, or absent);
      - "failed":  attempts exceeded max_attempts — marked failed, do not send.
    Caller must commit.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE notifications
            SET status = 'sending', attempts = attempts + 1, updated_at = now()
            WHERE id = %s AND status = 'pending'
            RETURNING attempts
            """,
            (notification_id,),
        )
        row = cur.fetchone()
    if row is None:
        return "skip"
    if row[0] > max_attempts:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE notifications SET status = 'failed', updated_at = now() WHERE id = %s",
                (notification_id,),
            )
        return "failed"
    return "claimed"


def reset_notification_pending(conn: psycopg.Connection, notification_id: str) -> None:
    """Return a leased notification to pending after a delivery failure so it is
    retried promptly (by the stream redelivery or the sweeper)."""
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE notifications SET status = 'pending', updated_at = now() "
            "WHERE id = %s AND status = 'sending'",
            (notification_id,),
        )


def mark_notification_sent(conn: psycopg.Connection, notification_id: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE notifications SET status = 'sent', sent_at = now(), updated_at = now() WHERE id = %s",
            (notification_id,),
        )


# ---------------------------------------------------------------------------
# Phase 4 — read layer for the API / web app
#
# These are query-only helpers consumed by the FastAPI read layer. They return
# plain dicts (JSON-friendly) and never mutate detection state.
# ---------------------------------------------------------------------------
def get_user_by_email(conn: psycopg.Connection, email: str) -> dict | None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, email, home_origin, created_at FROM users WHERE email = %s",
            (email.lower(),),
        )
        row = cur.fetchone()
    if row is None:
        return None
    return {
        "id": str(row[0]),
        "email": row[1],
        "home_origin": row[2],
        "created_at": row[3],
    }


def fetch_feed(
    conn: psycopg.Connection,
    *,
    origin: str | None,
    destination: str | None,
    max_price: float | None,
    confidence_levels: list[str] | None,
    recency_days: int,
    limit: int,
) -> list[dict]:
    """Discovery feed: the best current deal per route, ranked.

    One card per destination — ``DISTINCT ON (route_id)`` keeps the strongest
    (highest deal_score) non-expired deal per route, then the outer query ranks
    the whole feed by score then confidence. Expired deals (past their source
    ``expires_at``) and anything older than ``recency_days`` are dropped.
    """
    inner = [
        "SELECT DISTINCT ON (d.route_id)",
        "  d.id, r.id AS route_id, r.origin, r.destination, d.price,",
        "  d.depart_date, d.return_date, d.baseline_median, d.deal_score,",
        "  d.confidence, d.detected_at, d.expires_at",
        "FROM deals d JOIN routes r ON r.id = d.route_id",
        "WHERE (d.expires_at IS NULL OR d.expires_at > now())",
        "  AND d.detected_at >= now() - make_interval(days => %(recency_days)s)",
    ]
    params: dict = {"recency_days": recency_days, "limit": limit}
    if origin:
        inner.append("  AND r.origin = %(origin)s")
        params["origin"] = origin.upper()
    if destination:
        inner.append("  AND r.destination = %(destination)s")
        params["destination"] = destination.upper()
    if max_price is not None:
        inner.append("  AND d.price <= %(max_price)s")
        params["max_price"] = max_price
    if confidence_levels:
        inner.append("  AND d.confidence = ANY(%(confidence_levels)s::confidence_level[])")
        params["confidence_levels"] = confidence_levels
    # DISTINCT ON requires the leading ORDER BY key to match the distinct column.
    inner.append("ORDER BY d.route_id, d.deal_score DESC, d.detected_at DESC")

    sql = (
        "SELECT * FROM (\n" + "\n".join(inner) + "\n) t\n"
        # confidence enum is defined high<medium<low, so ASC = best first.
        "ORDER BY t.deal_score DESC, t.confidence ASC, t.detected_at DESC\n"
        "LIMIT %(limit)s"
    )
    with conn.cursor() as cur:
        cur.execute(sql, params)
        cols = [c.name for c in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    return [_deal_row(r) for r in rows]


def _deal_row(r: dict) -> dict:
    """Normalize a deal/route join row into JSON-friendly types."""
    return {
        "id": str(r["id"]),
        "route_id": str(r["route_id"]),
        "origin": r["origin"],
        "destination": r["destination"],
        "price": float(r["price"]),
        "depart_date": r["depart_date"],
        "return_date": r["return_date"],
        "baseline_median": float(r["baseline_median"]) if r["baseline_median"] is not None else None,
        "deal_score": float(r["deal_score"]),
        "confidence": r["confidence"],
        "detected_at": r["detected_at"],
        "expires_at": r["expires_at"],
    }


def list_watches(conn: psycopg.Connection, *, user_id: str, include_inactive: bool = False) -> list[dict]:
    sql = [
        "SELECT id, user_id, origin, destination, max_price, date_window_start,",
        "       date_window_end, flexible_dates, cabin, active, created_at",
        "FROM watches WHERE user_id = %s",
    ]
    params: list = [user_id]
    if not include_inactive:
        sql.append("AND active")
    sql.append("ORDER BY created_at DESC")
    with conn.cursor() as cur:
        cur.execute(" ".join(sql), params)
        cols = [c.name for c in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    return [_watch_row(r) for r in rows]


def _watch_row(r: dict) -> dict:
    return {
        "id": str(r["id"]),
        "user_id": str(r["user_id"]),
        "origin": r["origin"],
        "destination": r["destination"],
        "max_price": float(r["max_price"]) if r["max_price"] is not None else None,
        "date_window_start": r["date_window_start"],
        "date_window_end": r["date_window_end"],
        "flexible_dates": r["flexible_dates"],
        "cabin": r["cabin"],
        "active": r["active"],
        "created_at": r["created_at"],
    }


def get_watch(conn: psycopg.Connection, watch_id: str) -> dict | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, user_id, origin, destination, max_price, date_window_start,
                   date_window_end, flexible_dates, cabin, active, created_at
            FROM watches WHERE id = %s
            """,
            (watch_id,),
        )
        cols = [c.name for c in cur.description]
        row = cur.fetchone()
    return _watch_row(dict(zip(cols, row))) if row else None


def deactivate_watch(conn: psycopg.Connection, *, watch_id: str, user_id: str) -> bool:
    """Soft-delete a watch (set active=false). Scoped to user_id so one user
    can't deactivate another's watch. Returns True if a row was affected."""
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE watches SET active = false WHERE id = %s AND user_id = %s AND active",
            (watch_id, user_id),
        )
        return cur.rowcount > 0


def fetch_route(conn: psycopg.Connection, route_id: str) -> dict | None:
    with conn.cursor() as cur:
        cur.execute("SELECT id, origin, destination, created_at FROM routes WHERE id = %s", (route_id,))
        row = cur.fetchone()
    if row is None:
        return None
    return {"id": str(row[0]), "origin": row[1], "destination": row[2], "created_at": row[3]}


def fetch_route_observations(
    conn: psycopg.Connection, route_id: str, *, days: int, limit: int
) -> list[dict]:
    """Time-series points for a route's price-history chart, oldest first."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT observed_at, depart_date, return_date, price, transfers
            FROM price_observations
            WHERE route_id = %s AND observed_at >= now() - make_interval(days => %s)
            ORDER BY observed_at
            LIMIT %s
            """,
            (route_id, days, limit),
        )
        cols = [c.name for c in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    return [
        {
            "observed_at": r["observed_at"],
            "depart_date": r["depart_date"],
            "return_date": r["return_date"],
            "price": float(r["price"]),
            "transfers": int(r["transfers"]),
        }
        for r in rows
    ]


def fetch_route_baselines(conn: psycopg.Connection, route_id: str) -> list[dict]:
    """All baseline tiers for a route (month_bucket 0 = global, 1-12 = seasonal)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT month_bucket, median_price, p10_price, mad, sample_size, seeded, updated_at
            FROM route_baselines WHERE route_id = %s ORDER BY month_bucket
            """,
            (route_id,),
        )
        cols = [c.name for c in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    return [
        {
            "month_bucket": int(r["month_bucket"]),
            "median_price": float(r["median_price"]) if r["median_price"] is not None else None,
            "p10_price": float(r["p10_price"]) if r["p10_price"] is not None else None,
            "mad": float(r["mad"]) if r["mad"] is not None else None,
            "sample_size": int(r["sample_size"]),
            "seeded": bool(r["seeded"]),
            "updated_at": r["updated_at"],
        }
        for r in rows
    ]


def fetch_route_deals(conn: psycopg.Connection, route_id: str, *, days: int, limit: int) -> list[dict]:
    """Recent deals for a route, to overlay markers on the history chart."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT d.id, r.id AS route_id, r.origin, r.destination, d.price,
                   d.depart_date, d.return_date, d.baseline_median, d.deal_score,
                   d.confidence, d.detected_at, d.expires_at
            FROM deals d JOIN routes r ON r.id = d.route_id
            WHERE d.route_id = %s AND d.detected_at >= now() - make_interval(days => %s)
            ORDER BY d.detected_at DESC
            LIMIT %s
            """,
            (route_id, days, limit),
        )
        cols = [c.name for c in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    return [_deal_row(r) for r in rows]


def sweep_republishable(
    conn: psycopg.Connection, *, grace_seconds: int, lease_seconds: int, limit: int
) -> list[dict]:
    """Find notifications that need (re)publishing and return ready-to-send
    NotificationMessage dicts. Two recovery cases:

      1. 'sending' rows stuck past the lease (a notifier crashed mid-send) are
         reset to 'pending' (keeping their stale updated_at so step 2 picks them).
      2. 'pending' rows older than the grace period (publish was lost, or never
         happened) are locked (FOR UPDATE SKIP LOCKED so parallel sweepers don't
         double-grab), their updated_at bumped to throttle re-sweep, and returned.

    Caller publishes the returned messages, then commits (locks held until then).
    """
    with conn.cursor() as cur:
        # 1. Reclaim crashed in-flight deliveries.
        cur.execute(
            """
            UPDATE notifications SET status = 'pending'
            WHERE status = 'sending' AND updated_at < now() - make_interval(secs => %s)
            """,
            (lease_seconds,),
        )
        # 2. Lock & fetch stale pending rows with everything the notifier needs.
        cur.execute(
            """
            SELECT n.id, n.user_id, u.email, n.deal_id, n.channel,
                   r.origin, r.destination, d.price, d.depart_date, d.return_date,
                   d.deal_score, d.confidence
            FROM notifications n
            JOIN users u  ON u.id = n.user_id
            JOIN deals d  ON d.id = n.deal_id
            JOIN routes r ON r.id = d.route_id
            WHERE n.status = 'pending' AND n.updated_at < now() - make_interval(secs => %s)
            ORDER BY n.updated_at
            FOR UPDATE OF n SKIP LOCKED
            LIMIT %s
            """,
            (grace_seconds, limit),
        )
        cols = [c.name for c in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        if rows:
            ids = [r["id"] for r in rows]
            cur.execute("UPDATE notifications SET updated_at = now() WHERE id = ANY(%s)", (ids,))

    return [
        {
            "notification_id": str(r["id"]),
            "user_id": str(r["user_id"]),
            "email": r["email"],
            "deal_id": str(r["deal_id"]),
            "channel": r["channel"],
            "origin": r["origin"],
            "destination": r["destination"],
            "price": float(r["price"]),
            "depart_date": r["depart_date"],
            "return_date": r["return_date"],
            "deal_score": float(r["deal_score"]),
            "confidence": r["confidence"],
        }
        for r in rows
    ]
