"""Pydantic request/response models for the read layer.

These shape the JSON the Next.js front end consumes. Response models use
``from_attributes``-free construction (we build them from plain dicts returned by
shared.db), and field types stay close to the DB columns.
"""
from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field, computed_field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Deals / feed
# ---------------------------------------------------------------------------
class DealOut(BaseModel):
    id: str
    route_id: str
    origin: str
    destination: str
    price: float
    depart_date: date | None = None
    return_date: date | None = None
    baseline_median: float | None = None
    deal_score: float
    confidence: str
    detected_at: datetime
    expires_at: datetime | None = None

    @computed_field  # surfaced in the JSON so the UI shows "23% below normal"
    @property
    def pct_below_baseline(self) -> float | None:
        if not self.baseline_median:
            return None
        return round((self.baseline_median - self.price) / self.baseline_median * 100, 1)


class FeedResponse(BaseModel):
    count: int
    items: list[DealOut]


# ---------------------------------------------------------------------------
# Watches
# ---------------------------------------------------------------------------
class WatchOut(BaseModel):
    id: str
    user_id: str
    origin: str
    destination: str | None = None
    max_price: float | None = None
    date_window_start: date
    date_window_end: date
    flexible_dates: bool
    cabin: str
    active: bool
    created_at: datetime


class WatchCreate(BaseModel):
    # Plain str (not EmailStr) to avoid the email-validator dependency; the read
    # layer stays thin and a light `@` check is enough for MVP watch creation.
    email: str = Field(min_length=3, max_length=254)
    origin: str = Field(min_length=3, max_length=3)
    destination: str | None = Field(default=None, min_length=3, max_length=3)
    max_price: float | None = Field(default=None, gt=0)
    date_window_start: date
    date_window_end: date
    flexible_dates: bool = True
    cabin: str = "economy"

    @field_validator("email")
    @classmethod
    def _check_email(cls, v: str) -> str:
        v = v.strip()
        if "@" not in v or v.startswith("@") or v.endswith("@"):
            raise ValueError("invalid email")
        return v

    @model_validator(mode="after")
    def _check_window(self) -> "WatchCreate":
        if self.date_window_end < self.date_window_start:
            raise ValueError("date_window_end must be on or after date_window_start")
        return self

    def normalized_origin(self) -> str:
        return self.origin.upper()

    def normalized_destination(self) -> str | None:
        return self.destination.upper() if self.destination else None


# ---------------------------------------------------------------------------
# Route detail / history
# ---------------------------------------------------------------------------
class RouteOut(BaseModel):
    id: str
    origin: str
    destination: str
    created_at: datetime


class ObservationPoint(BaseModel):
    observed_at: datetime
    depart_date: date | None = None
    return_date: date | None = None
    price: float
    transfers: int


class BaselineOut(BaseModel):
    month_bucket: int
    median_price: float | None = None
    p10_price: float | None = None
    mad: float | None = None
    sample_size: int
    seeded: bool
    updated_at: datetime


class RouteHistoryResponse(BaseModel):
    route: RouteOut
    observations: list[ObservationPoint]
    baselines: list[BaselineOut]
    deals: list[DealOut]
