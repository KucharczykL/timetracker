/**
 * The wire codec for a segmented datetime field.
 *
 * The value submitted is an **offset-qualified wall clock**
 * (`2026-07-27T14:30:00.000000+02:00`), not a UTC instant. Django's
 * `DateTimeField.to_python` runs `parse_datetime` before any strptime, so an
 * offset binds aware and `from_current_timezone` no-ops on it — the server
 * needs no change. Keeping the typed wall clock *and* the resolved offset in
 * one payload is also what makes a future per-timestamp timezone cheap: both
 * halves are already there.
 */

import { presentationClock } from "../date-time-presentation.js";
import type { PartValues } from "./date-field-core.js";

const EMPTY_PARTS: PartValues = {
  year: "",
  month: "",
  day: "",
  hour: "",
  minute: "",
  day_period: "",
};

/** `YYYY-MM-DDTHH:MM` with optional seconds, fraction, and offset. */
const WIRE_PATTERN =
  /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,6}))?)?(Z|[+-]\d{2}:\d{2})?$/;

function pad(value: number, width: number): string {
  return String(value).padStart(width, "0");
}

interface Residual {
  second: number;
  // Temporal splits sub-second precision into millisecond/microsecond/
  // nanosecond fields, each 0-999 — a 6-digit fraction is NOT a microsecond
  // count. Passing one clamps it (123456 becomes 999).
  millisecond: number;
  microsecond: number;
}

/** Sub-minute precision carried by the value the field was rendered with.
 *
 * `duration_calculated` is a database generated column over both session
 * timestamps, so silently dropping seconds on an untouched edit would shift
 * every duration by up to a second — the same bug class this exists to close.
 * The segments only go down to minutes, so the residual rides along untouched.
 */
function residualFrom(initialValue: string): Residual {
  const match = WIRE_PATTERN.exec(initialValue.trim());
  if (!match) return { second: 0, millisecond: 0, microsecond: 0 };
  const [, , , , , , second, fraction] = match;
  const digits = (fraction ?? "").padEnd(6, "0");
  return {
    second: second ? parseInt(second, 10) : 0,
    millisecond: parseInt(digits.slice(0, 3), 10),
    microsecond: parseInt(digits.slice(3, 6), 10),
  };
}

/** 12-hour segments (1–12 plus a period) → the 0–23 hour the wire carries. */
function hourFromTwelve(hour: number, period: number): number {
  const base = hour % 12;
  return period === 1 ? base + 12 : base;
}

/** The inverse: a 0–23 hour → its 1–12 form and day period. */
function twelveFromHour(hour: number): { hour: number; period: number } {
  return { hour: hour % 12 === 0 ? 12 : hour % 12, period: hour < 12 ? 0 : 1 };
}

export interface DateTimeCodec {
  encode(values: PartValues, complete: boolean): string;
  decode(value: string): PartValues;
}

export function createDateTimeCodec(initialValue: string): DateTimeCodec {
  const residual = residualFrom(initialValue);

  return {
    encode(values, complete) {
      const clock = presentationClock();
      if (!complete || !clock) return "";

      let hour = parseInt(values.hour, 10);
      if (clock.hourCycle === "h12") {
        hour = hourFromTwelve(hour, parseInt(values.day_period || "0", 10));
      }
      let plain: Temporal.PlainDateTime;
      try {
        plain = Temporal.PlainDateTime.from({
          year: parseInt(values.year, 10),
          month: parseInt(values.month, 10),
          day: parseInt(values.day, 10),
          hour,
          minute: parseInt(values.minute, 10),
          second: residual.second,
          millisecond: residual.millisecond,
          microsecond: residual.microsecond,
        });
      } catch {
        return ""; // an impossible date (e.g. 31 February) commits nothing
      }
      const wallClock = plain.toString({ fractionalSecondDigits: 6 });

      // "earlier" resolves an ambiguous wall clock to its first occurrence and
      // silently shifts a nonexistent one forward. Round-tripping tells the two
      // apart: only a gap comes back as a different wall clock. `"reject"`
      // cannot express this — it throws on ambiguity as well as on gaps.
      const zoned = plain.toZonedDateTime(clock.timeZone, {
        disambiguation: "earlier",
      });
      if (!zoned.toPlainDateTime().equals(plain)) {
        // A time that does not exist. Submit it bare and let Django reject it
        // with the message it already produces, rather than inventing an
        // instant the user never asked for.
        return wallClock;
      }
      return `${wallClock}${zoned.offset}`;
    },

    decode(value) {
      const match = WIRE_PATTERN.exec(value.trim());
      if (!match) return { ...EMPTY_PARTS };
      const [, year, month, day, hour, minute] = match;

      const clock = presentationClock();
      const parts: PartValues = {
        ...EMPTY_PARTS,
        year,
        month,
        day,
        hour,
        minute,
      };
      if (clock?.hourCycle === "h12") {
        const twelve = twelveFromHour(parseInt(hour, 10));
        parts.hour = pad(twelve.hour, 2);
        parts.day_period = pad(twelve.period, 2);
      }
      return parts;
    },
  };
}
