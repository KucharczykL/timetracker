/**
 * The wire format one temporal endpoint's segments state.
 *
 * `dateCodec` encodes "" for anything short of a whole day, because a date
 * input has one precision. A temporal endpoint has five, and its parts can
 * arrive in any order the profile shows them, so this codec encodes every
 * part, filled or not. The value it produces is never posted: it lives in an
 * unnamed scratch input and only exists so the shared engine can tell a
 * change from a keystroke that changed nothing.
 */
import type { FieldCodec } from "./date-field-core.js";

export const temporalCodec: FieldCodec = {
  // `complete` says every segment is full, which no partial date is.
  encode(values) {
    const year = values.year ?? "";
    const month = values.month ?? "";
    const day = values.day ?? "";
    if (!year && !month && !day) return "";
    return `${year}-${month}-${day}`;
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
