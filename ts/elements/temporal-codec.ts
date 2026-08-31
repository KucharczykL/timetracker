/**
 * The wire format one temporal endpoint's segments state.
 *
 * `dateCodec` encodes "" for anything short of a whole day, because a date
 * input has one precision. A temporal endpoint has five, so this codec
 * encodes the longest coarse-first run a person filled and ignores the rest.
 * The value it produces is never posted: it lives in an unnamed scratch
 * input and only exists so the shared engine can tell a change from a
 * keystroke that changed nothing.
 */
import type { FieldCodec, PartValues } from "./date-field-core.js";

/** The coarse-first run of filled parts, joined the way EDTF joins them. */
export function coarsestPrefix(values: PartValues): string {
  const year = values.year ?? "";
  const month = values.month ?? "";
  const day = values.day ?? "";
  if (!year) return "";
  if (!month) return year;
  if (!day) return `${year}-${month}`;
  return `${year}-${month}-${day}`;
}

export const temporalCodec: FieldCodec = {
  // `complete` says every segment is full, which no partial date is.
  encode(values) {
    return coarsestPrefix(values);
  },
  decode(value) {
    const pieces = value.split("-");
    return { year: pieces[0] ?? "", month: pieces[1] ?? "", day: pieces[2] ?? "" };
  },
};

/** The year a decade opens on: 1982 belongs to 1980. */
export function decadeStart(year: string): string {
  if (!/^\d+$/.test(year)) return "";
  return String(Math.floor(parseInt(year, 10) / 10) * 10);
}
