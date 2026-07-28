"""Thin client for the Travelpayouts Aviasales Data API.

Endpoints verified against the live docs (June 2026). We deliberately lean on
the multi-destination endpoints so one HTTP call fans out to many routes,
keeping us well under the ~200 req/hour/IP ceiling.

Auth: token in the ``X-Access-Token`` header.
Caching: data reflects the recent ~48h of searches; each ticket carries its own
``expires_at``. Respect ``X-RateLimit`` response headers.
"""
from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from shared.config import settings

log = logging.getLogger(__name__)


class TravelpayoutsError(RuntimeError):
    pass


class TravelpayoutsClient:
    def __init__(self, token: str | None = None, base_url: str | None = None) -> None:
        self._token = token or settings.travelpayouts_token
        self._base = (base_url or settings.travelpayouts_base_url).rstrip("/")
        self._http = httpx.Client(
            base_url=self._base,
            headers={"X-Access-Token": self._token, "Accept-Encoding": "gzip, deflate"},
            timeout=20.0,
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "TravelpayoutsClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- low-level ---------------------------------------------------------
    def _get(self, path: str, params: dict[str, Any]) -> dict:
        params = {k: v for k, v in params.items() if v is not None}
        for attempt in range(3):
            resp = self._http.get(path, params=params)
            if resp.status_code == 429:
                # Rate limited: honor Retry-After if present, else back off.
                wait = float(resp.headers.get("Retry-After", 2 ** attempt))
                log.warning("rate limited on %s, sleeping %.1fs", path, wait)
                time.sleep(wait)
                continue
            if resp.status_code >= 400:
                raise TravelpayoutsError(f"{resp.status_code} {path}: {resp.text[:200]}")
            return resp.json()
        raise TravelpayoutsError(f"giving up after retries: {path}")

    # -- endpoints we use --------------------------------------------------
    def city_directions(self, origin: str, currency: str | None = None) -> dict:
        """Cheapest popular destinations FROM one origin in a single call.

        Backbone of the flexible-discovery feed. Returns a dict keyed by
        destination IATA -> price/date payload.
        """
        return self._get(
            "/v1/city-directions",
            {"origin": origin, "currency": currency or settings.default_currency},
        )

    def prices_cheap(
        self,
        origin: str,
        destination: str,
        depart_date: str | None = None,
        return_date: str | None = None,
        currency: str | None = None,
    ) -> dict:
        """Cheapest 0/1/2-stop tickets for a specific route (route detail)."""
        return self._get(
            "/v1/prices/cheap",
            {
                "origin": origin,
                "destination": destination,
                "depart_date": depart_date,
                "return_date": return_date,
                "currency": currency or settings.default_currency,
            },
        )

    def month_matrix(
        self, origin: str, destination: str, currency: str | None = None
    ) -> dict:
        """Prices per calendar day grouped by transfers — seeds seasonal baselines."""
        return self._get(
            "/v2/prices/month-matrix",
            {
                "origin": origin,
                "destination": destination,
                "currency": currency or settings.default_currency,
                "show_to_affiliates": "true",
            },
        )

    def prices_monthly(
        self, origin: str, destination: str, currency: str | None = None
    ) -> dict:
        """Cheapest tickets grouped by month — also used for seasonal seeding."""
        return self._get(
            "/v1/prices/monthly",
            {
                "origin": origin,
                "destination": destination,
                "currency": currency or settings.default_currency,
            },
        )
