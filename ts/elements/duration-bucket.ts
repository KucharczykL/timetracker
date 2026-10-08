// Same table as duration_bucket_hint in filters.py.

// Largest hour count a timedelta holds.
const MAX_DURATION_HOURS = 999_999_999 * 24;

// "0 h up to 1 h" for a finite value, else "".
export function durationBucketRange(value: string): string {
  const trimmed = value.trim();
  if (trimmed === "") return "";
  const hours = Number(trimmed);
  if (!Number.isFinite(hours) || Math.abs(hours) > MAX_DURATION_HOURS) return "";
  return `${String(hours)} h up to ${String(hours + 1)} h`;
}

// The hint under a duration input. Only EQUALS and NOT_EQUALS carry one.
export function durationBucketHint(modifier: string, value: string): string {
  const range = durationBucketRange(value);
  if (range === "") return "";
  if (modifier === "EQUALS") return range;
  if (modifier === "NOT_EQUALS") return `outside ${range}`;
  return "";
}
