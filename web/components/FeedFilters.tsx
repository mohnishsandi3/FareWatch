"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";

/** Filter bar for the discovery feed; pushes choices into the URL query so the
 * server component re-fetches. */
export default function FeedFilters() {
  const router = useRouter();
  const params = useSearchParams();

  const [origin, setOrigin] = useState(params.get("origin") ?? "");
  const [maxPrice, setMaxPrice] = useState(params.get("max_price") ?? "");
  const [minConfidence, setMinConfidence] = useState(params.get("min_confidence") ?? "");

  const apply = (e: React.FormEvent) => {
    e.preventDefault();
    const q = new URLSearchParams();
    if (origin.trim()) q.set("origin", origin.trim().toUpperCase());
    if (maxPrice.trim()) q.set("max_price", maxPrice.trim());
    if (minConfidence) q.set("min_confidence", minConfidence);
    router.push(`/feed${q.toString() ? `?${q}` : ""}`);
  };

  return (
    <form onSubmit={apply} className="flex flex-wrap items-end gap-3">
      <label className="flex flex-col text-sm">
        <span className="mb-1 text-gray-600">From (IATA)</span>
        <input
          value={origin}
          onChange={(e) => setOrigin(e.target.value)}
          maxLength={3}
          placeholder="BOS"
          className="input w-28"
        />
      </label>
      <label className="flex flex-col text-sm">
        <span className="mb-1 text-gray-600">Max price (USD)</span>
        <input
          value={maxPrice}
          onChange={(e) => setMaxPrice(e.target.value)}
          type="number"
          min={1}
          placeholder="any"
          className="input w-32"
        />
      </label>
      <label className="flex flex-col text-sm">
        <span className="mb-1 text-gray-600">Min confidence</span>
        <select
          value={minConfidence}
          onChange={(e) => setMinConfidence(e.target.value)}
          className="input w-40"
        >
          <option value="">Any</option>
          <option value="high">High only</option>
          <option value="medium">Medium &amp; up</option>
          <option value="low">Low &amp; up</option>
        </select>
      </label>
      <button className="rounded-lg bg-gray-900 px-4 py-2 text-sm font-medium text-white hover:bg-gray-700">
        Apply
      </button>
    </form>
  );
}
