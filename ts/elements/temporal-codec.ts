/**
 * Scratch codec: every part, typed in any order, never posted.
 *
 * The engine commits only when this value changes. A blank part must still
 * take its slot, or a day typed before its year changes nothing and is lost.
 */
import type { FieldCodec } from "./date-field-core.js";

export const temporalCodec: FieldCodec = {
  // Ignores `complete`: a partial value must encode too.
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
