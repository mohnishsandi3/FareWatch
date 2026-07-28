import Link from "next/link";

import type { Deal } from "@/lib/types";
import { money, shortDate } from "@/lib/format";
import ConfidenceBadge from "./ConfidenceBadge";

/** One discovery-feed card: a route, its price, and why it's flagged. */
export default function DealCard({ deal }: { deal: Deal }) {
  const pct = deal.pct_below_baseline;
  return (
    <Link
      href={`/routes/${deal.route_id}`}
      className="block rounded-xl border border-gray-200 bg-white p-5 shadow-sm transition hover:shadow-md hover:border-gray-300"
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-sm text-gray-500">
            {deal.origin} &rarr; {deal.destination}
          </div>
          <div className="mt-1 text-3xl font-semibold tracking-tight text-gray-900">
            {money(deal.price)}
          </div>
        </div>
        {pct != null && pct > 0 && (
          <div className="rounded-lg bg-conf-high/10 px-2.5 py-1 text-right">
            <div className="text-lg font-bold leading-none text-conf-high">
              -{pct}%
            </div>
            <div className="text-[10px] uppercase tracking-wide text-conf-high/80">
              below normal
            </div>
          </div>
        )}
      </div>

      <div className="mt-4 flex items-center justify-between">
        <div className="text-sm text-gray-600">
          {shortDate(deal.depart_date)}
          {deal.return_date ? ` – ${shortDate(deal.return_date)}` : ""}
        </div>
        <ConfidenceBadge level={deal.confidence} />
      </div>

      {deal.baseline_median != null && (
        <div className="mt-2 text-xs text-gray-400">
          Typical for this route: {money(deal.baseline_median)}
        </div>
      )}
    </Link>
  );
}
