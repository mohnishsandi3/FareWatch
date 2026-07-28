import type { Confidence } from "@/lib/types";

const STYLES: Record<Confidence, string> = {
  high: "bg-conf-high/10 text-conf-high ring-conf-high/30",
  medium: "bg-conf-medium/10 text-conf-medium ring-conf-medium/30",
  low: "bg-conf-low/10 text-conf-low ring-conf-low/30",
};

const LABEL: Record<Confidence, string> = {
  high: "High confidence",
  medium: "Medium confidence",
  low: "Low confidence",
};

/** Honestly surfaces uneven data coverage — a core FareWatch product decision. */
export default function ConfidenceBadge({ level }: { level: Confidence }) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${STYLES[level]}`}
      title="Driven by sample size, data freshness, and which baseline tier was used"
    >
      {LABEL[level]}
    </span>
  );
}
