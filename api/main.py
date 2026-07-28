"""Phase 4 — FastAPI read layer over Postgres for the web app.

A thin read surface (plus minimal watch management) the Next.js front end calls:
  - GET  /feed                     discovery feed, ranked by deal_score+confidence
  - GET  /watches?email=           list a user's watches
  - POST /watches                  create a watch (upserts the user by email)
  - DELETE /watches/{id}?email=    deactivate a watch
  - GET  /routes/{id}              route metadata
  - GET  /routes/{id}/history      price history + baselines + deal markers

Run: uvicorn api.main:app --reload
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import feed, route_detail, watches
from shared.config import settings

app = FastAPI(title="FareWatch API", version="0.4.0")

# Allow the Next.js dev server (and any configured prod origins) to call the API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(feed.router)
app.include_router(watches.router)
app.include_router(route_detail.router)


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok"}
