# web/ — Next.js 15 front end (Phase 4)

The discovery dashboard for FareWatch. App Router + Tailwind, deliberately thin
(the detection engine is the product). Talks to the FastAPI read layer.

## Pages

```
app/
  page.tsx          → redirects to /feed
  feed/             "deals right now" — best fare per route, ranked by score + confidence
  watches/          watch management (create / list / delete by email; no auth yet)
  routes/[id]/      per-route price-history chart showing WHY a price is a deal
components/
  DealCard, ConfidenceBadge, FeedFilters, PriceChart (dependency-free SVG), WatchManager
lib/
  api.ts (typed fetch client), types.ts, format.ts
```

## Run locally

The API must be running first (see the repo README — `uvicorn api.main:app`).

```powershell
cd web
npm install
Copy-Item .env.example .env.local      # NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
npm run dev                             # http://localhost:3000
```

## Notes

- **No charting library** — `PriceChart` is hand-rolled SVG (overlays the route
  median + p10 baselines so a deal visibly sits below "normal"). Keeps deps tiny.
- **Identity is by email** for MVP (stored in `localStorage`); real auth is a
  later concern. The read API authorizes watch deletes by matching the email.
- Every deal shows a **confidence badge** (high/medium/low) — the honest
  surfacing of uneven data coverage that's core to the product.
- A production `Dockerfile` is included but the web service is intentionally not
  in `docker-compose.yml` (run it on the host for fast HMR during dev).
