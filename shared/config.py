"""Centralized settings, loaded from environment / .env."""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Travelpayouts Data API
    travelpayouts_token: str = "replace-me"
    travelpayouts_base_url: str = "https://api.travelpayouts.com"
    travelpayouts_marker: str = ""
    default_currency: str = "usd"
    default_market: str = "us"

    # Stores
    database_url: str = "postgresql://farewatch:farewatch@localhost:5432/farewatch"
    redis_url: str = "redis://localhost:6379/0"

    # Ingestion
    origin_hubs: str = "BOS,JFK,LAX,ORD,SFO"
    poll_interval_seconds: int = 10800
    obs_bucket_seconds: int = 10800

    # Cold-start seeding: cap destinations seeded per hub to bound API calls
    # (each is one month-matrix call). 0 = no cap (mind the ~200 req/hr ceiling).
    seed_limit_per_hub: int = 25

    # Notification delivery reliability
    notification_max_attempts: int = 5            # tries before status -> failed
    notification_grace_seconds: int = 60          # re-publish pending older than this
    notification_lease_seconds: int = 120         # reclaim 'sending' stuck longer than this
    notification_sweep_interval_seconds: int = 60
    notification_sweep_batch: int = 100

    # API read layer (Phase 4)
    api_cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    log_level: str = "INFO"

    @property
    def hubs(self) -> list[str]:
        return [h.strip().upper() for h in self.origin_hubs.split(",") if h.strip()]

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.api_cors_origins.split(",") if o.strip()]


settings = Settings()
