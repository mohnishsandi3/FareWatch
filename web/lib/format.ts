// Small display helpers shared by feed + route views.

export function money(n: number, currency = "USD"): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    maximumFractionDigits: 0,
  }).format(n);
}

export function shortDate(iso: string | null): string {
  if (!iso) return "flexible";
  // Date-only strings (YYYY-MM-DD) are parsed as UTC; render in UTC to avoid
  // an off-by-one from the local timezone.
  const d = new Date(iso.length <= 10 ? `${iso}T00:00:00Z` : iso);
  return d.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  });
}
