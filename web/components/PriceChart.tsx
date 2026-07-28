import type { Baseline, Deal, ObservationPoint } from "@/lib/types";
import { money, shortDate } from "@/lib/format";

interface Props {
  observations: ObservationPoint[];
  baselines: Baseline[];
  deals: Deal[];
}

const W = 760;
const H = 280;
const PAD = { top: 16, right: 16, bottom: 28, left: 48 };

/**
 * Dependency-free SVG price-history chart — deliberately no charting library
 * (keeps the web layer thin, per CLAUDE.md). Plots observed prices over time
 * with the learned median + p10 baselines overlaid, so a flagged deal visibly
 * sits below "normal". Renders fine as a server component (no interactivity).
 */
export default function PriceChart({ observations, baselines, deals }: Props) {
  if (observations.length === 0) {
    return (
      <div className="flex h-48 items-center justify-center rounded-lg border border-dashed border-gray-300 text-sm text-gray-400">
        No price history yet for this route.
      </div>
    );
  }

  // Prefer the global (all-month) baseline tier for the reference lines.
  const global = baselines.find((b) => b.month_bucket === 0) ?? baselines[0];
  const median = global?.median_price ?? null;
  const p10 = global?.p10_price ?? null;

  const times = observations.map((o) => Date.parse(o.observed_at));
  const prices = observations.map((o) => o.price);
  const candidates = [
    ...prices,
    ...(median != null ? [median] : []),
    ...(p10 != null ? [p10] : []),
    ...deals.map((d) => d.price),
  ];
  const tMin = Math.min(...times);
  const tMax = Math.max(...times);
  const yMin = Math.min(...candidates) * 0.95;
  const yMax = Math.max(...candidates) * 1.05;

  const plotW = W - PAD.left - PAD.right;
  const plotH = H - PAD.top - PAD.bottom;

  const x = (t: number) =>
    PAD.left + (tMax === tMin ? plotW / 2 : ((t - tMin) / (tMax - tMin)) * plotW);
  const y = (p: number) =>
    PAD.top + (yMax === yMin ? plotH / 2 : (1 - (p - yMin) / (yMax - yMin)) * plotH);

  const linePath = observations
    .map((o, i) => `${i === 0 ? "M" : "L"} ${x(times[i]).toFixed(1)} ${y(o.price).toFixed(1)}`)
    .join(" ");

  return (
    <figure className="w-full overflow-x-auto">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="w-full min-w-[640px]"
        role="img"
        aria-label="Price history with baseline overlay"
      >
        {/* y gridlines + labels */}
        {[yMin, (yMin + yMax) / 2, yMax].map((v, i) => (
          <g key={i}>
            <line
              x1={PAD.left}
              x2={W - PAD.right}
              y1={y(v)}
              y2={y(v)}
              stroke="#f1f5f9"
            />
            <text x={4} y={y(v) + 4} className="fill-gray-400 text-[10px]">
              {money(v)}
            </text>
          </g>
        ))}

        {/* baseline (median) reference line */}
        {median != null && (
          <>
            <line
              x1={PAD.left}
              x2={W - PAD.right}
              y1={y(median)}
              y2={y(median)}
              stroke="#94a3b8"
              strokeDasharray="5 4"
            />
            <text x={W - PAD.right} y={y(median) - 4} textAnchor="end" className="fill-gray-500 text-[10px]">
              median {money(median)}
            </text>
          </>
        )}

        {/* p10 "good deal" threshold */}
        {p10 != null && (
          <>
            <line
              x1={PAD.left}
              x2={W - PAD.right}
              y1={y(p10)}
              y2={y(p10)}
              stroke="#16a34a"
              strokeDasharray="2 3"
            />
            <text x={W - PAD.right} y={y(p10) - 4} textAnchor="end" className="fill-conf-high text-[10px]">
              p10 {money(p10)}
            </text>
          </>
        )}

        {/* observed price line */}
        <path d={linePath} fill="none" stroke="#2563eb" strokeWidth={1.75} />

        {/* deal markers */}
        {deals.map((d) => (
          <circle
            key={d.id}
            cx={x(Date.parse(d.detected_at))}
            cy={y(d.price)}
            r={4}
            className="fill-conf-high"
            stroke="#fff"
            strokeWidth={1.5}
          >
            <title>
              Deal: {money(d.price)} ({d.confidence}) on {shortDate(d.detected_at)}
            </title>
          </circle>
        ))}

        {/* x range labels */}
        <text x={PAD.left} y={H - 8} className="fill-gray-400 text-[10px]">
          {shortDate(new Date(tMin).toISOString())}
        </text>
        <text x={W - PAD.right} y={H - 8} textAnchor="end" className="fill-gray-400 text-[10px]">
          {shortDate(new Date(tMax).toISOString())}
        </text>
      </svg>
      <figcaption className="mt-2 text-xs text-gray-400">
        Blue: observed cheapest fares. Dashed grey: route median. Dotted green:
        p10 (the &ldquo;good deal&rdquo; threshold). Green dots: flagged deals.
      </figcaption>
    </figure>
  );
}
