// Mirrors duration_bucket_hint in filters.py.

// Print whole hours without decimals.
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

// Hint for EQUALS and NOT_EQUALS only.
export function durationBucketHint(modifier: string, value: string): string {
  const range = durationBucketRange(value);
  if (range === "") return "";
  if (modifier === "EQUALS") return range;
  if (modifier === "NOT_EQUALS") return `outside ${range}`;
  return "";
}
