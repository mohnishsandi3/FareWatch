// Tiny typed fetch wrapper around the FareWatch read API.
import type {
  Deal,
  FeedResponse,
  RouteHistory,
  Watch,
  WatchCreate,
} from "./types";

const BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") ||
  "http://localhost:8000";

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    // Always hit the API fresh — deals + watches change continuously.
    cache: "no-store",
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    ...init,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json())?.detail ?? detail;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, String(detail));
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = "ApiError";
  }
}

export interface FeedFilters {
  origin?: string;
  destination?: string;
  maxPrice?: number;
  minConfidence?: string;
  recencyDays?: number;
  limit?: number;
}

export function getFeed(f: FeedFilters = {}): Promise<FeedResponse> {
  const q = new URLSearchParams();
  if (f.origin) q.set("origin", f.origin);
  if (f.destination) q.set("destination", f.destination);
  if (f.maxPrice != null) q.set("max_price", String(f.maxPrice));
  if (f.minConfidence) q.set("min_confidence", f.minConfidence);
  if (f.recencyDays != null) q.set("recency_days", String(f.recencyDays));
  if (f.limit != null) q.set("limit", String(f.limit));
  const qs = q.toString();
  return req<FeedResponse>(`/feed${qs ? `?${qs}` : ""}`);
}

export function getRouteHistory(id: string, days = 90): Promise<RouteHistory> {
  return req<RouteHistory>(`/routes/${id}/history?days=${days}`);
}

export function listWatches(email: string): Promise<Watch[]> {
  return req<Watch[]>(`/watches?email=${encodeURIComponent(email)}`);
}

export function createWatch(body: WatchCreate): Promise<Watch> {
  return req<Watch>(`/watches`, { method: "POST", body: JSON.stringify(body) });
}

export function deactivateWatch(id: string, email: string): Promise<void> {
  return req<void>(`/watches/${id}?email=${encodeURIComponent(email)}`, {
    method: "DELETE",
  });
}

export type { Deal };
