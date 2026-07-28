# FareWatch

A persistent travel-deal monitoring engine: continuously ingests flight price
data, learns each route's "normal" price, and flags genuine deals with a
confidence level. See [CLAUDE.md](./CLAUDE.md) for the full design and product
decisions.

## Status

- **Phase 1 — Ingestion + price history** built (poll → dedup-write → stream).
- **Phase 2 — Deal detection engine** built: robust baselines (median + MAD,
  seasonality), anomaly detection with deal_score + confidence, a real Redis
  Streams consumer (consumer group, ack, reaper, dead-letter), and a cold-start
  seeder (`engine/seeder.py`) that primes baselines from the month-matrix.
- **Phase 3 — Watches / matching / notifications** built + hardened: alert
  matcher (deal-events → active watches), notifier with pluggable channels, and
  the notifications dedup ledger. Adds a third stream (`stream:notifications`)
  and consumer group on the shared `run_consumer` machinery. Delivery is
  lease-claimed (idempotent) with an attempts cap, and a sweeper
  (`notifier/sweeper.py`) guarantees stranded notifications are eventually
  delivered.
- **Phase 4 — Discovery dashboard** built: a FastAPI read layer (`/feed`,
  `/watches`, `/routes/{id}/history`) over Postgres, and a Next.js 15 + Tailwind
  front end — discovery feed, watch management, and a per-route price-history
  chart (dependency-free SVG) that shows *why* a price is flagged.
- **Next iteration** designed, not yet built — see "Known Gaps & Next
  Iteration" in [CLAUDE.md](./CLAUDE.md): matcher field fixes
  (`flexible_dates`/`cabin`), re-alert cooldown, booking deep links, an engine
  evaluation loop, then production hardening (rate-limit observability,
  retention, real email, auth).

## Layout

```
ingestion/   Python pollers (Travelpayouts Data API -> price_observations + stream)
engine/      Python deal detection (Phase 2) + cold-start seeder
matcher/     deal-events -> watches (Phase 3)
notifier/    delivery + dedup + sweeper (Phase 3)
api/         FastAPI read layer (Phase 4): feed, watches, route history
web/         Next.js 15 + Tailwind front end (Phase 4)
shared/      config, db, redis streams, domain models
migrations/  SQL (0001-0003)
tests/       unit tests (+ guarded integration tests)
```

## Local development

Prereqs: Docker + Python 3.12.

```powershell
# 1. Config
Copy-Item .env.example .env
#    then edit .env and set TRAVELPAYOUTS_TOKEN

# 2. Infra (Postgres + Redis). Migrations auto-apply on a fresh pg volume.
docker compose up -d postgres redis

# 3. Python env
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 4. Run one ingestion pass (writes history, publishes to the stream)
python -m ingestion.workers.price_poller

# 5. Or run the scheduler (polls every POLL_INTERVAL_SECONDS)
python -m ingestion.scheduler

# 6. (Optional, recommended) Seed cold-start baselines so deals can fire day one
python -m engine.seeder

# 7. Run the detection engine (consumes observations, emits deals)
python -m engine.consumer

# 8. Phase 3 pipeline: create a watch, then run the matcher + notifier
python -m scripts.create_watch --email you@example.com --origin BOS `
    --max-price 400 --start 2026-06-01 --end 2026-09-01
python -m matcher.consumer        # deal-events -> notifications
python -m notifier.consumer       # notifications -> delivery (logs the "email")
python -m notifier.sweeper        # safety-net: re-publishes stranded notifications

# 9. Phase 4 read API (serves the web app)
uvicorn api.main:app --reload        # http://localhost:8000  (/docs for Swagger)

# 10. Phase 4 web app (Next.js) — in a separate shell, with the API running
cd web
npm install
Copy-Item .env.example .env.local    # NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
npm run dev                          # http://localhost:3000

# 11. Tests (no DB/Redis needed)
pytest -q

# 12. Integration tests (need Postgres with migrations applied)
$env:FAREWATCH_INTEGRATION = "1"; pytest -q tests/test_delivery_integration.py tests/test_api_integration.py
```

To run ingestion in a container instead of on the host:

```powershell
docker compose up ingestion
```

## Design guardrails (from CLAUDE.md)

- **Data is cached, ~48h fresh**, with per-ticket `expires_at`. Not live booking
  pricing — fine for trend-based deal detection.
- **Polling cost is the killer.** `/v1/city-directions` returns many
  destinations per call; curated hubs keep us under ~200 req/hour/IP.
- **Every deal carries confidence** driven by sample size + freshness + baseline
  tier — honestly surfaces uneven coverage.
- **The detection engine is the product** (Phase 2); keep everything else thin.
