# FareWatch

*(working name)*

A persistent travel-deal monitoring engine. It continuously ingests flight price data, learns what a "normal" price is for each route, and alerts users when a genuinely good deal appears. The core product is **deal detection** — distinguishing a real anomaly from noise — not itinerary generation or booking.

## Why this exists (the problem)

Retail travelers miss good fares because they can't watch prices continuously, and they can't tell whether a given price is actually good without knowing the route's history. Existing tools either do simple fixed-route price alerts (a commodity) or generate itineraries (something an LLM already does well). This project deliberately targets the gap: **persistent monitoring + anomaly detection over live price data**, which an LLM structurally cannot do (no live data, no persistent state, non-deterministic). The defensible value is in the always-on watchdog and the "is this actually a good deal?" judgment.

### Product decisions (deliberate, do not drift from these)

1. **Flexible-destination discovery is the core of v1, not fixed-route watching.** The primary experience is "show me the best deals anywhere from my city under $X in the next N months." This plays to the data source's strengths and is more differentiated than a single-route watcher. Fixed-route watching is a secondary feature.
2. **Every deal carries a confidence level.** Because the price data is cached and built from real user search history, coverage is uneven — popular routes are dense, obscure ones are thin. Rather than pretend the data is uniform, attach a confidence score (driven by sample size) to every deal. High-confidence deals on dense routes are trustworthy; low-confidence ones are flagged as such.
3. **The deal-detection engine is the product.** Invest engineering effort there and keep everything around it thin. It is the part that is neither an LLM nor a Google Flights clone.

## Tech Stack

- **Ingestion workers + detection engine**: Python (strong for the statistical work). Workers are plain processes, not a web framework.
- **Message bus**: Redis Streams (consumer groups, acks, dead-letter patterns — Kafka is the documented scale-up path, not needed for MVP).
- **Persistent store**: Postgres (time-series price history + all application state).
- **Cache + dedup + stream transport**: Redis.
- **API**: FastAPI (Python) — thin layer over Postgres for the front end.
- **Front end**: Next.js 15 + App Router + Tailwind CSS (reuses patterns from prior project).
- **Notifications**: transactional email provider + optional web push.
- **Deploy**: Azure (Container Apps for workers/engine; the API and web app can sit alongside). Dockerized throughout.

*Note: if deepening .NET is preferred over Python, the workers and engine port over cleanly — the architecture is identical. Python is the default recommendation for the stats-heavy detection engine.*

## Data Source

### Primary: Travelpayouts Aviasales Data API (flights)

This is the MVP data source. It is a travel-insights API returning flight price trends, cheap prices, and a month-matrix (prices per day of month grouped by transfers). Access is via an affiliate token (free to register; monetization is affiliate-commission based, not pay-per-call), which makes it effectively free for this project. Auth: pass the token in the `X-Access-Token` header (or `token` query param).

**Endpoints we use (verified against live docs, June 2026):**
- `GET /v1/city-directions?origin=BOS&currency=usd` — cheapest popular destinations *from one origin in a single call*. **This is the backbone of the flexible-discovery feed** and keeps polling cheap (one call fans out to many routes).
- `GET /v1/prices/cheap?origin=BOS&destination=...` — cheapest 0/1/2-stop tickets for a route (up to 100 results/page); used for route detail.
- `GET /v2/prices/month-matrix?origin=BOS&destination=...` — prices per calendar day grouped by transfers; **seeds seasonal baselines (cold-start)**.
- `GET /v1/prices/monthly?origin=BOS&destination=...` — cheapest tickets grouped by month; also for seasonal seeding.
- Supporting: `/v1/prices/calendar`, `/v2/prices/latest`, `/v1/prices/direct`.

**Critical constraints to design around:**
- **Data is cached**, based on real Aviasales user search history. Two different windows: query results are *retained* ~7 days, but the **price data itself reflects only the recent ~48 hours** of user searches, and **each ticket carries its own `expires_at`**. Practical freshness ≈ 48h. It is *not* live booking-grade pricing. For a deal monitor tracking trends, this is acceptable and actually helps avoid the polling-cost trap. Use the API's per-ticket `expires_at` directly to populate `deals.expires_at`, and feed ticket age into the confidence score (fresher data → higher confidence).
- **Polling cost is the hidden killer.** APIs without webhook/alert endpoints force repeated polling; naive high-frequency polling across many routes gets expensive and rate-limited fast. Poll on sensible intervals, cache aggressively, and lean on cached trend data rather than hammering a search endpoint. Travelpayouts explicitly recommends caching. Published rate limit is conservative (~200 queries/hour per IP); monitor the `X-RateLimit` response headers. Using `/v1/city-directions` (many destinations per call) keeps a curated-hub set well under this ceiling.
- **Coverage is uneven** (search-history-driven) — hence the confidence-level requirement above.
- The full real-time **flight search** API is gated (application process + a large monthly-active-user requirement, with an older version being sunset). The **Data API** (trends, cheap prices) is the accessible part and is what this project uses. Do not build on the gated search API for MVP.

### Avoid
- **Amadeus Self-Service** — deprecating (shutdown mid-2026). Do not start here.
- **Flight status APIs** (AeroDataBox, Aviationstack) — these are schedule/delay data, NOT pricing. Not relevant.

### Alternatives (future / if needed)
- **Duffel** — modern, transparent pricing, no accreditation; the right choice *only if* real booking flows are added later.
- **Scraping** (ScrapingBee, Apify) — fragile and adversarial; last-resort fallback for coverage APIs can't provide.

### Hotels (explicitly out of scope for v1)
- If extended later: **Xotelo** (free, includes a cheap/average/high price-day heatmap) or **Makcorps** (compares 200+ OTAs, small free tier). Keep hotels out of v1 — flights alone make a complete, demoable product.

## Architecture

A decoupled data pipeline. The two-stage message bus is deliberate: ingestion and detection and alerting each scale, retry, and fail independently.

```
Travelpayouts Data API (external source)
        |
        v
Ingestion workers ......... scheduled, rate-aware polling; idempotent writes
        |  publishes raw price observations
        v
Redis Streams: observations  (message bus, stage 1)
        |
        v
Deal detection engine ..... maintains baselines, detects anomalies   <-->  Postgres
        |  publishes deal events                                            (history,
        v                                                                    baselines,
Redis Streams: deal-events   (message bus, stage 2)                          deals, state)
        |                                                                       ^
        v                                                                       |
Alert matcher ............. matches deal events to active user watches ---------+
        |  publishes a notification per matched user/deal
        v
Redis Streams: notifications (message bus, stage 3)
        |
        v
Notification service ...... email / push, deduplicated via notifications ledger

Web app + API (Next.js + FastAPI) reads from Postgres for the discovery feed,
watch management, and per-route price-history charts.
```

## MVP Phases

### Phase 1 — Ingestion + price history (weeks 1-2)
- Scheduled ingestion workers pulling the Travelpayouts Data API for a *curated set of origin hubs* (start with a few major US cities incl. Boston — not "every airport," to keep data dense and polling cheap).
- Append every observation to `price_observations` (time-series).
- Idempotent writes (dedup identical observations), rate-limit-aware scheduling.
- No detection yet — goal is a clean, growing, deduplicated history.
- *Teaches: scheduling, rate-aware polling, idempotency.*

### Phase 2 — Deal detection engine (weeks 3-4)
- Consume observations from the stream; maintain per-route baselines; emit deal events.
- This is the centerpiece — over-invest here. (See "Deal Detection Engine" below.)

### Phase 3 — Watches, matching, notifications (weeks 5-6)
- User auth + watch creation ("anywhere from Boston under $400, flexible dates, next 3 months").
- Alert matcher pairs deal events against active watches.
- Notification delivery with deduplication (no double-alerting the same deal).
- *Teaches: consumer groups, idempotency, dead-letter queues.*

### Phase 4 — Discovery dashboard (weeks 7-8)
- Next.js front end: "deals from your city right now" feed, ranked by deal score and confidence.
- Watch management UI.
- Per-route price-history chart showing *why* a price is flagged as a deal.

## Data Model (Postgres)

### `users`
- `id` (uuid, PK), `email` (unique), `home_origin` (iata code, nullable), `created_at`

### `routes` — canonical origin/destination pairs
- `id` (uuid, PK), `origin` (iata), `destination` (iata), `created_at`
- unique on `(origin, destination)`

### `price_observations` — append-only time-series
- `id` (bigserial, PK), `route_id` (FK -> routes), `depart_date` (date), `return_date` (date, nullable), `price` (numeric), `currency` (text), `transfers` (smallint), `observed_at` (timestamptz), `obs_bucket` (timestamptz, the polling window this row belongs to), `source_expires_at` (timestamptz, nullable — the API's per-ticket `expires_at`)
- index on `(route_id, observed_at)` for fast baseline queries
- **dedup-vs-time-series rule:** unique on `(route_id, depart_date, return_date, transfers, obs_bucket)`. Within one polling window we keep at most one row per route/date/transfers (dedup); the *same* price re-seen in a *later* window is a new, wanted row (it's evidence the price is stable). This resolves the "dedup identical observations" vs "append-only time-series" tension — we dedup per window, not globally.
- treat as immutable; never update rows

### `route_baselines` — derived cache, recomputed on a rolling window
- `route_id` (FK -> routes), `month_bucket` (smallint, 0-12; 1-12 = seasonality, **0 = global all-month fallback tier**), `median_price` (numeric), `p10_price` (numeric), `mad` (numeric, median absolute deviation), `sample_size` (int), `seeded` (bool — true = cold-start seed from Travelpayouts endpoints, capped at low confidence until native data replaces it), `updated_at` (timestamptz)
- PK: `(route_id, month_bucket)`

### `watches` — user criteria
- `id` (uuid, PK), `user_id` (FK -> users), `origin` (iata), `destination` (iata, nullable — null = flexible/anywhere), `max_price` (numeric, nullable), `date_window_start` (date), `date_window_end` (date), `flexible_dates` (bool), `cabin` (text), `active` (bool), `created_at`
- **`flexible_dates` semantics (decided 2026-06, not yet enforced by the matcher):** `true` = a deal matches if its `depart_date` falls inside the window (lenient); `false` = the *whole trip* must fit — `depart_date` AND `return_date` (when present) both inside the window (strict). Implementing this in `matcher/matching.py` is a known gap (see "Known Gaps & Next Iteration").
- **`cabin` is deprecated — drop in the next migration.** The Data API carries no cabin information, so this field can never be matched honestly; today it is stored but silently ignored, which is worse than not having it. Remove from schema, API, and UI rather than fake it.

### `deals` — a detected anomaly
- `id` (uuid, PK), `route_id` (FK -> routes), `price` (numeric), `depart_date` (date), `return_date` (date, nullable), `baseline_median` (numeric, snapshot at detection), `deal_score` (numeric, for ranking), `confidence` (enum: high/medium/low, driven by sample_size), `detected_at` (timestamptz), `expires_at` (timestamptz, nullable)
- **Planned (next iteration):** `confirmations` (int, default 0) and `last_confirmed_at` (timestamptz, nullable) — the engine's self-evaluation signal (see "Engine evaluation loop" under Known Gaps).

### `notifications` — dedup ledger + delivery state machine
- `id` (uuid, PK), `user_id` (FK -> users), `deal_id` (FK -> deals), `channel` (text), `status` (text: `pending`/`sending`/`sent`/`failed`), `attempts` (int), `sent_at` (timestamptz), `updated_at` (timestamptz)
- unique on `(user_id, deal_id, channel)` — this constraint *is* the dedup guarantee
- `attempts`/`updated_at` drive the delivery lease + sweeper (see "Notification delivery reliability")

### Design notes
- `price_observations` is append-only and indexed for time-range scans.
- `route_baselines` is a recomputed cache keyed by route + month bucket (seasonality), not mutated per observation.
- The `notifications` unique constraint enforces idempotent alerting at the database level.

## Deal Detection Engine (the heart)

The naive approach (`alert if price < $X`) is useless: $300 to London is a steal, $300 to Chicago is a ripoff. A deal is only meaningful *relative to what is normal for that route at that time*. The engine does three things:

1. **Robust baselines.** Compute baselines from the rolling price history using **median and median-absolute-deviation (MAD)**, NOT mean and standard deviation — fares are right-skewed and full of outliers that wreck a mean.
2. **Seasonality.** "Normal" in December differs from June. Bucket baselines by month (`month_bucket`). The Travelpayouts month-matrix endpoint helps populate this. **Fragmentation fallback:** 12 buckets split already-thin routes into sparse samples, so use a baseline hierarchy — per-month bucket → global (all-month) baseline → seeded baseline — falling back down the chain when a bucket lacks enough samples, with confidence degrading at each step.
3. **Anomaly flagging + scoring.** Flag a deal when an observed price falls far enough below baseline (e.g., below p10, or several MADs under the median). Assign:
   - `deal_score` — normalized "how good," used for ranking the discovery feed.
   - `confidence` — driven by `sample_size` **and data freshness** (`source_expires_at` / ticket age) **and which baseline tier was used** (per-month > global > seeded); honestly surfaces the uneven, time-decaying data coverage. Few samples, stale data, or a seeded baseline -> low confidence.

**Cold-start handling:** seed initial baselines from the Travelpayouts trend / month-matrix endpoints on day one, rather than waiting weeks to accumulate history. Mark freshly-seeded routes as lower confidence until enough native observations accrue.

## Redis Streams Consumer Design

Three streams, each read by a consumer group. This is where idempotency, acks, and dead-lettering live. (The original design named two streams; a third, `stream:notifications`, was added in Phase 3 so the matcher and notifier scale, retry, and fail independently — consistent with the decoupled-alerting goal in the Architecture section.)

### Streams
- `stream:observations` — produced by ingestion workers, consumed by the detection engine.
- `stream:deal-events` — produced by the detection engine, consumed by the alert matcher.
- `stream:notifications` — produced by the alert matcher (one per matched user/deal), consumed by the notifier.

### Shared consumer runner
- All three stages run one generic loop, `shared.streams.run_consumer(stream, group, handler, ...)`, which does the `XREADGROUP` → handler → `XACK` cycle plus the reaper and dead-letter handling. Each stage only supplies its per-message `handler` (which raises on failure to trigger retry). This keeps the streaming machinery in one place instead of copy-pasted per worker.

### Consumer groups
- Use `XGROUP CREATE` per stream. Each logical consumer stage is a group; scale by adding consumers to the group (Redis distributes entries across them).
- Read with `XREADGROUP` (consumer name per worker instance), process, then `XACK` only after successful processing. Unacked entries remain in the Pending Entries List (PEL).

### Idempotency
- Producers attach a deterministic dedup key per message (e.g., a hash of route + dates + price + observation window). Consumers check/record processed keys (Redis SET with TTL, or a processed-table in Postgres) before acting, so reprocessing a redelivered message is a no-op.
- Detection results writing to `deals` and the alert matcher writing to `notifications` both rely on the DB unique constraints as the final idempotency backstop.

### Notification delivery reliability (Phase 3 hardening)
- The matcher writes the `notifications` ledger row (status `pending`), then publishes to `stream:notifications` (fast path). The DB unique `(user_id, deal_id, channel)` prevents re-alerting.
- The notifier delivers via an **atomic lease**: a single row-locked `UPDATE … SET status='sending' WHERE status='pending'` claims the row, so duplicate stream messages can't both send. On delivery failure it resets to `pending` and re-raises (stream redelivery retries); after `notification_max_attempts` it sets `failed` (surfaced, never silently dropped). Status machine: `pending → sending → sent | failed`.
- A **sweeper** (`notifier/sweeper.py`) closes the lost-publish / crashed-mid-send gap: on an interval it re-publishes `pending` rows older than a grace period and reclaims `sending` rows stuck past the lease, using `FOR UPDATE … SKIP LOCKED`. Re-publishing is safe because of the lease-claim above. This makes accepted matches **eventually delivered** even if a worker dies between the ledger commit and the stream publish.

### Retries + dead-letter
- On processing failure, do NOT ack. A reaper periodically scans the PEL with `XPENDING` / `XAUTOCLAIM` to reclaim entries idle beyond a threshold and redeliver them.
- Track a delivery count per entry. After N failed attempts, move the entry to a `stream:dead-letter` stream (or a `dead_letter` Postgres table) with the error context, then ack the original so it stops redelivering. Dead-lettered items are surfaced for inspection, never silently dropped.

### Backpressure
- Cap `XREADGROUP COUNT` per pull and use bounded streams (`XADD ... MAXLEN ~`) so a slow consumer doesn't let a stream grow without limit. The cached/interval-based ingestion naturally limits inflow.

## Known Gaps & Next Iteration (design review, 2026-06-09)

All four MVP phases are built and faithful to this document. A design review against the implementation surfaced the gaps below. These are **decided designs awaiting implementation** — when picking up work, start here, in this order. Items 1–3 are product-correctness in the core loop; item 4 deepens the engine (the product); item 5 is production hardening and can trail.

### 1. Matcher honesty: implement `flexible_dates`, drop `cabin`
The matcher (`matcher/matching.py`) fetches `flexible_dates` and `cabin` but uses neither — a business-class watch happily matches economy fares. Fix:
- Enforce the `flexible_dates` semantics defined on the `watches` model (lenient = depart in window; strict = whole trip in window).
- Migration `0004`: drop `watches.cabin`; remove it from the API schema and web form. The Data API has no cabin data, so the field is a false promise.
- Add unit tests for both behaviors (the absence of tests is *why* these fields stayed dead).

### 2. Alerting semantics: re-alert cooldown
`uq_deal` is keyed on exact price, so BOS→LON Aug 1 at $300 → $298 → $302 across three polling windows creates three deal rows — and the `(user_id, deal_id, channel)` ledger correctly treats each as new, sending three emails for what a human considers one deal. The observation-level dedup rule ("dedup per window, not globally") was deliberate; deal-level *alert* dedup was never specified. Decision:
- The matcher suppresses a notification when the same user was already notified about a deal on the same `(route_id, depart_date, return_date)` within `ALERT_COOLDOWN_HOURS` (default 72), **unless** the new price is materially better than the previously-alerted price (`ALERT_IMPROVEMENT_PCT`, default 5%).
- Implemented as a DB check (notifications ⋈ deals) in the matcher before writing the ledger row — consistent with the "DB is the idempotency backstop" philosophy. The unique constraint stays as-is; the cooldown sits in front of it.
- Deal *rows* are still created per detection (they are evidence for the engine); only the alert is suppressed. The discovery feed already collapses to best-per-route via `DISTINCT ON`.

### 3. Deal actionability: booking deep links
Deals tell the user a fare is great but give no way to act on it. The affiliate marker (`TRAVELPAYOUTS_MARKER`) exists precisely for Aviasales deep links — this closes the product loop and is how the data source is meant to be monetized. Decision:
- Construct the search deep link **at API read time** (a `booking_url` on `DealOut`) from origin/destination/dates + marker. No schema change, no stale stored URLs.
- Surface it on `DealCard`, the route-detail deal list, and in notification payloads.

### 4. Engine evaluation loop (precision feedback)
Nothing measures whether flagged deals are *real* — a gap in the original goal, not just the code. Cheap proxy using our own data: a deal that keeps re-appearing in later polling windows was real and stable; one that vanishes immediately was noise or a stale-cache artifact. Decision:
- Add `deals.confirmations` + `deals.last_confirmed_at` (migration with item 1's `0004`). When the engine processes an observation matching an open deal's `(route_id, depart_date, return_date)` at a price within tolerance (≤ ~105% of the deal price), increment instead of ignoring.
- Precision proxy = share of deals ever confirmed; log it per run, surface later in the UI. Eventually feed confirmation history back into `confidence`.

### 5. Production-readiness backlog (ordered, defer until 1–4 land)
- **X-RateLimit observability**: the client docstring claims to respect `X-RateLimit` headers but never reads them — only reactive 429/Retry-After handling exists. Log the headers; warn near the ceiling.
- **Data retention**: `price_observations` grows unbounded (~5–10k rows/day at current polling). Add a scheduled prune; keep ~13 months so month-bucket seasonality can eventually use a full year of native history.
- **Real email channel**: `notifier/channels.py` is a `LogChannel` stub. The channel interface is already pluggable — add a transactional provider (Resend/Postmark/SendGrid) behind it, plus an unsubscribe path.
- **Auth**: identity is a plaintext email query param; anyone can *list* anyone's watches by guessing an email (deletes are owner-scoped, listing is not). Replace email-as-identity with magic-link auth before any external exposure.
- **Pipeline observability**: stage lag (oldest unacked stream entry age), DLQ depth alerting, structured JSON logs.

### Explicitly still out of scope
Hotels, real booking flows (Duffel), multi-currency, Kafka. Unchanged from v1 decisions.

## Project Structure

```
farewatch/
├── ingestion/                 # Python — scheduled pollers
│   ├── workers/
│   ├── scheduler.py
│   └── travelpayouts_client.py
├── engine/                    # Python — deal detection
│   ├── baselines.py           # robust stats, seasonality
│   ├── detector.py            # anomaly flagging + scoring
│   └── consumer.py            # Redis Streams consumer (group, ack, DLQ)
├── matcher/                   # Python — deal events -> watches
│   └── consumer.py
├── notifier/                  # Python — delivery + dedup
│   └── consumer.py
├── api/                       # FastAPI — read layer for the front end
│   ├── main.py                # app + CORS + router wiring; /health
│   ├── deps.py                # pooled-connection request dependency
│   ├── schemas.py             # pydantic request/response models
│   ├── filtering.py           # pure confidence-tier helpers (unit-tested)
│   └── routes/                # feed.py, watches.py, route_detail.py
├── web/                       # Next.js 15 (App Router) + Tailwind
│   ├── app/
│   │   ├── feed/              # deals-from-your-city discovery feed
│   │   ├── watches/           # watch management (create/list/delete by email)
│   │   └── routes/[id]/       # per-route price-history chart (SVG, no chart lib)
│   ├── components/            # DealCard, ConfidenceBadge, PriceChart, WatchManager
│   └── lib/                   # typed API client, shared types, formatters
├── shared/                    # shared models, Redis stream helpers, db
│   ├── db.py
│   ├── streams.py             # XGROUP/XREADGROUP/XACK/XAUTOCLAIM helpers
│   └── models.py
├── migrations/                # SQL migrations
├── docker-compose.yml         # local: postgres + redis + workers
├── CLAUDE.md
└── README.md
```

## Development Notes

- Local dev via `docker-compose` (Postgres + Redis + the worker processes).
- Start with a curated origin-hub list to keep data dense and polling within rate limits; expand later.
- Respect the polling-cost trap: every new polled route multiplies API calls — measure call volume before scaling the route set.
- The detection engine is the showcase; keep ingestion, matching, notification, and the web layer deliberately thin.
- Seed baselines from Travelpayouts trend endpoints to soften cold-start.
- Use the DB unique constraints (`notifications`, `deals`) as the final idempotency backstop behind the stream-level dedup.