// Shapes returned by the FareWatch read API (api/schemas.py). Kept in sync by
// hand — the API is the source of truth.

export type Confidence = "high" | "medium" | "low";

export interface Deal {
  id: string;
  route_id: string;
  origin: string;
  destination: string;
  price: number;
  depart_date: string | null;
  return_date: string | null;
  baseline_median: number | null;
  deal_score: number;
  confidence: Confidence;
  detected_at: string;
  expires_at: string | null;
  pct_below_baseline: number | null;
}

export interface FeedResponse {
  count: number;
  items: Deal[];
}

export interface Watch {
  id: string;
  user_id: string;
  origin: string;
  destination: string | null;
  max_price: number | null;
  date_window_start: string;
  date_window_end: string;
  flexible_dates: boolean;
  cabin: string;
  active: boolean;
  created_at: string;
}

export interface WatchCreate {
  email: string;
  origin: string;
  destination?: string | null;
  max_price?: number | null;
  date_window_start: string;
  date_window_end: string;
  flexible_dates?: boolean;
  cabin?: string;
}

export interface Route {
  id: string;
  origin: string;
  destination: string;
  created_at: string;
}

export interface ObservationPoint {
  observed_at: string;
  depart_date: string | null;
  return_date: string | null;
  price: number;
  transfers: number;
}

export interface Baseline {
  month_bucket: number; // 0 = global fallback, 1-12 = seasonal
  median_price: number | null;
  p10_price: number | null;
  mad: number | null;
  sample_size: number;
  seeded: boolean;
  updated_at: string;
}

export interface RouteHistory {
  route: Route;
  observations: ObservationPoint[];
  baselines: Baseline[];
  deals: Deal[];
}
