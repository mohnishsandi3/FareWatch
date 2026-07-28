"""Redis Streams helpers — the message-bus primitives.

Wraps XADD / XGROUP / XREADGROUP / XACK / XAUTOCLAIM with the project's
conventions: bounded streams (MAXLEN ~), per-stage consumer groups, and a
dead-letter path. Phase 1 only produces to ``stream:observations``; the consumer
helpers are here so the engine (Phase 2) and matcher (Phase 3) reuse them.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Callable

import redis

from shared.config import settings

log = logging.getLogger(__name__)

# Stream names
OBSERVATIONS = "stream:observations"
DEAL_EVENTS = "stream:deal-events"
NOTIFICATIONS = "stream:notifications"
DEAD_LETTER = "stream:dead-letter"

# Consumer groups (one per consuming stage)
GROUP_ENGINE = "engine"
GROUP_MATCHER = "matcher"
GROUP_NOTIFIER = "notifier"

# Backpressure / retry knobs
DEFAULT_MAXLEN = 100_000        # approximate cap per stream (XADD MAXLEN ~)
DEFAULT_BATCH = 64              # XREADGROUP COUNT per pull
MAX_DELIVERIES = 5              # attempts before dead-lettering
IDLE_RECLAIM_MS = 60_000        # reclaim PEL entries idle longer than this
PROCESSED_TTL_SECONDS = 7 * 24 * 3600  # dedup-key retention

_client: redis.Redis | None = None


def get_redis() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
    return _client


def publish(stream: str, payload: dict[str, Any], *, maxlen: int = DEFAULT_MAXLEN) -> str:
    """XADD a JSON payload to a bounded stream. Returns the entry id."""
    r = get_redis()
    return r.xadd(stream, {"data": json.dumps(payload, default=str)}, maxlen=maxlen, approximate=True)


def ensure_group(stream: str, group: str) -> None:
    """Create the consumer group if it doesn't exist (idempotent)."""
    r = get_redis()
    try:
        r.xgroup_create(stream, group, id="0", mkstream=True)
    except redis.ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise


def read_group(
    stream: str, group: str, consumer: str, *, count: int = DEFAULT_BATCH, block_ms: int = 5000
):
    """XREADGROUP one batch of new entries for this consumer."""
    r = get_redis()
    resp = r.xreadgroup(group, consumer, {stream: ">"}, count=count, block=block_ms)
    if not resp:
        return []
    # resp = [(stream, [(id, {field: val}), ...])]
    return [(entry_id, json.loads(fields["data"])) for entry_id, fields in resp[0][1]]


def ack(stream: str, group: str, entry_id: str) -> None:
    get_redis().xack(stream, group, entry_id)


def dead_letter(stream: str, group: str, entry_id: str, payload: dict, error: str) -> None:
    """Move a poison message to the dead-letter stream, then ack the original."""
    publish(DEAD_LETTER, {"source_stream": stream, "entry_id": entry_id, "error": error, "payload": payload})
    ack(stream, group, entry_id)


def mark_processed(dedup_key: str, *, ttl: int = PROCESSED_TTL_SECONDS) -> bool:
    """Record a dedup key. Returns True if newly seen (process it), False if it
    was already processed (skip + ack). Uses SET NX EX for atomicity."""
    return bool(get_redis().set(f"processed:{dedup_key}", "1", nx=True, ex=ttl))


def pending_stale(stream: str, group: str, *, idle_ms: int = IDLE_RECLAIM_MS, count: int = 64) -> list[dict]:
    """List PEL entries idle beyond ``idle_ms`` (candidates for reclaim/DLQ).

    Each dict has message_id, consumer, time_since_delivered, times_delivered.
    """
    return get_redis().xpending_range(stream, group, min="-", max="+", count=count, idle=idle_ms)


def claim(stream: str, group: str, consumer: str, ids: list[str], *, idle_ms: int = IDLE_RECLAIM_MS):
    """XCLAIM the given ids to this consumer. Returns [(id, payload), ...]."""
    claimed = get_redis().xclaim(stream, group, consumer, min_idle_time=idle_ms, message_ids=ids)
    return [(eid, json.loads(fields["data"])) for eid, fields in claimed]


# ---------------------------------------------------------------------------
# Generic consumer runner — the shared XREADGROUP loop + reaper + DLQ.
# Every stage (engine, matcher, notifier) runs the same machinery; only the
# per-message ``handler`` differs. A handler MUST raise on failure so the entry
# is left unacked for the reaper to retry / dead-letter.
# ---------------------------------------------------------------------------
Handler = Callable[[dict], None]


def _process(stream: str, group: str, entry_id: str, payload: dict, handler: Handler) -> None:
    handler(payload)
    ack(stream, group, entry_id)


def _reap(stream: str, group: str, consumer: str, handler: Handler) -> None:
    """Reclaim stale PEL entries; retry them, or dead-letter past MAX_DELIVERIES."""
    for item in pending_stale(stream, group):
        entry_id = item["message_id"]
        if item["times_delivered"] >= MAX_DELIVERIES:
            msgs = get_redis().xrange(stream, min=entry_id, max=entry_id)
            payload = json.loads(msgs[0][1]["data"]) if msgs else {}
            dead_letter(stream, group, entry_id, payload, error=f"exceeded {MAX_DELIVERIES} deliveries")
            log.warning("dead-lettered %s on %s after %s tries", entry_id, stream, item["times_delivered"])
            continue
        for eid, payload in claim(stream, group, consumer, [entry_id]):
            try:
                _process(stream, group, eid, payload, handler)
            except Exception:  # noqa: BLE001 — leave unacked; next reap escalates
                log.exception("retry failed for %s on %s", eid, stream)


def run_consumer(
    stream: str,
    group: str,
    handler: Handler,
    *,
    consumer_name: str,
    should_continue: Callable[[], bool] = lambda: True,
    block_ms: int = 5000,
) -> None:
    """Run the standard consume loop until ``should_continue()`` is False."""
    ensure_group(stream, group)
    log.info("consumer %s started on %s/%s", consumer_name, stream, group)
    while should_continue():
        for entry_id, payload in read_group(stream, group, consumer_name, block_ms=block_ms):
            try:
                _process(stream, group, entry_id, payload, handler)
            except Exception:  # noqa: BLE001 — logged; reaper will retry
                log.exception("processing failed for %s on %s", entry_id, stream)
        _reap(stream, group, consumer_name, handler)
