import { getFeed } from "@/lib/api";
import type { Deal } from "@/lib/types";
import DealCard from "@/components/DealCard";
import FeedFilters from "@/components/FeedFilters";

// Always render fresh — deals change continuously.
export const dynamic = "force-dynamic";

interface SearchParams {
  origin?: string;
  max_price?: string;
  min_confidence?: string;
}

export default async function FeedPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const sp = await searchParams;

  let deals: Deal[] = [];
  let error: string | null = null;
  try {
    const res = await getFeed({
      origin: sp.origin,
      maxPrice: sp.max_price ? Number(sp.max_price) : undefined,
      minConfidence: sp.min_confidence,
      recencyDays: 7,
      limit: 60,
    });
    deals = res.items;
  } catch {
    error = "Couldn't reach the FareWatch API. Is it running on :8000?";
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Deals right now</h1>
        <p className="mt-1 text-sm text-gray-500">
          The best current fare per route, ranked by how good the deal is and how
          confident we are in it.
        </p>
      </div>

      <FeedFilters />

      {error ? (
        <div className="rounded-lg bg-conf-low/10 px-4 py-3 text-sm text-conf-low ring-1 ring-conf-low/30">
          {error}
        </div>
      ) : deals.length === 0 ? (
        <p className="text-sm text-gray-500">
          No deals match yet. Try widening the filters, or seed/ingest more data.
        </p>
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {deals.map((d) => (
            <DealCard key={d.id} deal={d} />
          ))}
        </div>
      )}
    </div>
  );
}
