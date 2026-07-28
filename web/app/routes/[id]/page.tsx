import Link from "next/link";

import { getRouteHistory } from "@/lib/api";
import type { RouteHistory } from "@/lib/types";
import { money, shortDate } from "@/lib/format";
import ConfidenceBadge from "@/components/ConfidenceBadge";
import PriceChart from "@/components/PriceChart";

export const dynamic = "force-dynamic";

const MONTHS = [
  "All",
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
];

export default async function RoutePage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;

  let data: RouteHistory | null = null;
  let error: string | null = null;
  try {
    data = await getRouteHistory(id, 90);
  } catch {
    error = "Couldn't load this route. It may not exist, or the API is down.";
  }

  if (error || !data) {
    return (
      <div className="space-y-4">
        <Link href="/feed" className="text-sm text-blue-600 hover:underline">
          &larr; Back to feed
        </Link>
        <div className="rounded-lg bg-conf-low/10 px-4 py-3 text-sm text-conf-low ring-1 ring-conf-low/30">
          {error}
        </div>
      </div>
    );
  }

  const { route, observations, baselines, deals } = data;

  return (
    <div className="space-y-8">
      <div>
        <Link href="/feed" className="text-sm text-blue-600 hover:underline">
          &larr; Back to feed
        </Link>
        <h1 className="mt-2 text-2xl font-bold tracking-tight">
          {route.origin} &rarr; {route.destination}
        </h1>
        <p className="mt-1 text-sm text-gray-500">
          {observations.length} observations over the last 90 days
        </p>
      </div>

      <section className="rounded-xl border border-gray-200 bg-white p-5">
        <h2 className="mb-4 text-lg font-semibold">Price history</h2>
        <PriceChart observations={observations} baselines={baselines} deals={deals} />
      </section>

      <section className="grid grid-cols-1 gap-8 lg:grid-cols-2">
        <div>
          <h2 className="mb-3 text-lg font-semibold">Baselines</h2>
          {baselines.length === 0 ? (
            <p className="text-sm text-gray-500">No baselines computed yet.</p>
          ) : (
            <table className="w-full overflow-hidden rounded-xl border border-gray-200 bg-white text-sm">
              <thead className="bg-gray-50 text-left text-gray-500">
                <tr>
                  <th className="px-3 py-2 font-medium">Bucket</th>
                  <th className="px-3 py-2 font-medium">Median</th>
                  <th className="px-3 py-2 font-medium">p10</th>
                  <th className="px-3 py-2 font-medium">Samples</th>
                  <th className="px-3 py-2 font-medium">Source</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {baselines.map((b) => (
                  <tr key={b.month_bucket}>
                    <td className="px-3 py-2">{MONTHS[b.month_bucket] ?? b.month_bucket}</td>
                    <td className="px-3 py-2">{b.median_price != null ? money(b.median_price) : "—"}</td>
                    <td className="px-3 py-2">{b.p10_price != null ? money(b.p10_price) : "—"}</td>
                    <td className="px-3 py-2">{b.sample_size}</td>
                    <td className="px-3 py-2">
                      {b.seeded ? (
                        <span className="text-conf-medium">seeded</span>
                      ) : (
                        <span className="text-conf-high">native</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div>
          <h2 className="mb-3 text-lg font-semibold">Recent deals</h2>
          {deals.length === 0 ? (
            <p className="text-sm text-gray-500">No deals flagged in this window.</p>
          ) : (
            <ul className="divide-y divide-gray-100 rounded-xl border border-gray-200 bg-white">
              {deals.map((d) => (
                <li key={d.id} className="flex items-center justify-between gap-4 p-4">
                  <div className="text-sm">
                    <div className="font-medium text-gray-900">{money(d.price)}</div>
                    <div className="text-gray-500">
                      {shortDate(d.depart_date)} · detected {shortDate(d.detected_at)}
                      {d.pct_below_baseline != null && d.pct_below_baseline > 0 && (
                        <span className="ml-1 text-conf-high">
                          ({d.pct_below_baseline}% below normal)
                        </span>
                      )}
                    </div>
                  </div>
                  <ConfidenceBadge level={d.confidence} />
                </li>
              ))}
            </ul>
          )}
        </div>
      </section>
    </div>
  );
}
