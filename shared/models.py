"""Shared domain models passed between pipeline stages.

These are plain pydantic models used as the payload shape on the Redis Streams,
independent of the DB rows. Keep them small and serializable.
"""
from __future__ import annotations

import hashlib
from datetime import date, datetime

from pydantic import BaseModel


class PriceObservation(BaseModel):
    """A single cheapest-price data point pulled from the Data API.

    Published to ``stream:observations`` by ingestion, consumed by the engine.
    """

    origin: str
    destination: str
    depart_date: date | None = None
    return_date: date | None = None
    price: float
    currency: str
    transfers: int = 0
    observed_at: datetime
    obs_bucket: datetime
    source_expires_at: datetime | None = None

    def dedup_key(self) -> str:
        """Deterministic key for stream-level idempotency.

        Mirrors the DB unique constraint (route + dates + transfers + window):
        reprocessing a redelivered message becomes a no-op.
        """
        raw = "|".join(
            [
                self.origin,
                self.destination,
                str(self.depart_date or ""),
                str(self.return_date or ""),
                str(self.transfers),
                self.obs_bucket.isoformat(),
            ]
        )
        return hashlib.sha256(raw.encode()).hexdigest()


class DealEvent(BaseModel):
    """An anomaly emitted by the detection engine onto ``stream:deal-events``."""

    route_origin: str
    route_destination: str
    price: float
    depart_date: date | None = None
    return_date: date | None = None
    baseline_median: float | None = None
    deal_score: float
    confidence: str  # high | medium | low
    detected_at: datetime
    expires_at: datetime | None = None
    deal_id: str | None = None  # set by the engine after the deal row is written


class NotificationMessage(BaseModel):
    """A matched deal-for-user, emitted by the matcher onto
    ``stream:notifications`` and consumed by the notifier. Carries the ledger row
    id plus the denormalized fields the notifier needs to render the alert."""

    notification_id: str
    user_id: str
    email: str
    deal_id: str
    channel: str
    origin: str
    destination: str
    price: float
    depart_date: date | None = None
    return_date: date | None = None
    deal_score: float
    confidence: str
