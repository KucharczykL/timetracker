// The one TS home of the duration bucket text. Mirrors `duration_bucket_hint`
// and its range in common/components/filters.py; keep the two in step.

// Whole hours print bare, so `1` never reads `1.0`.
function hourText(hours: number): string {
  return String(hours);
}

// "0 h up to 1 h" for a finite value, else "".
export function durationBucketRange(value: string): string {
  const trimmed = value.trim();
  if (trimmed === "") return "";
  const hours = Number(trimmed);
  if (!Number.isFinite(hours)) return "";
  return `${hourText(hours)} h up to ${hourText(hours + 1)} h`;
}

// The hint under a duration input. Only EQUALS and NOT_EQUALS carry one.
export function durationBucketHint(modifier: string, value: string): string {
  const range = durationBucketRange(value);
  if (range === "") return "";
  if (modifier === "EQUALS") return range;
  if (modifier === "NOT_EQUALS") return `outside ${range}`;
  return "";
}
