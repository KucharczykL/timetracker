import { reportClientError } from "./client-errors.js";
import type {
  HourCycle,
  SegmentKind,
  SegmentName,
  SegmentRun,
} from "./generated/date-time-presentation.js";

const CONTRACT_ATTRIBUTE = "data-date-time-presentation";
const SEGMENT_NAMES = new Set<SegmentName>([
  "day",
  "month",
  "year",
  "hour",
  "minute",
  "day_period",
]);
const SEGMENT_KINDS = new Set<SegmentKind>(["numeric", "day_period"]);
const SEGMENT_RUNS = new Set<SegmentRun>(["date", "time"]);
const REQUIRED_DATE_SEGMENTS: SegmentName[] = ["day", "month", "year"];
const NUMERIC_PART_NAMES = ["day", "month", "year", "hour", "minute"] as const;

type NumericPartName = (typeof NUMERIC_PART_NAMES)[number];

export interface Affixes {
  prefix: string;
  suffix: string;
}

export interface Segment {
  name: SegmentName;
  kind: SegmentKind;
  run: SegmentRun;
  placeholder: string;
  inputLength: number;
  displayMinimumDigits: number;
  minimumValue: number;
  maximumValue: number;
  display: Affixes;
  segmented: Affixes;
}

interface CompiledPresentation {
  locale: string;
  timeZone: string;
  segments: Segment[];
  hourCycle: HourCycle;
  dayPeriods: { am: string; pm: string };
  dateTimeFormatter: Intl.DateTimeFormat;
  calendarMonthYearFormatter: Intl.DateTimeFormat;
  calendarWeekdayFormatter: Intl.DateTimeFormat;
  numberFormats: Map<number, Intl.NumberFormat>;
}

let cachedPresentation: CompiledPresentation | null | undefined;

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function invalidContract(message: string): never {
  throw new Error(message);
}

function requireRecord(value: unknown, name: string): Record<string, unknown> {
  if (!isRecord(value)) invalidContract(`${name} must be an object`);
  return value;
}

function requireString(record: Record<string, unknown>, name: string): string {
  const value = record[name];
  if (typeof value !== "string") invalidContract(`${name} must be a string`);
  return value;
}

function requireNonemptyString(record: Record<string, unknown>, name: string): string {
  const value = requireString(record, name);
  if (!value) invalidContract(`${name} must not be empty`);
  return value;
}

function requirePositiveInteger(record: Record<string, unknown>, name: string): number {
  const value = record[name];
  if (!Number.isInteger(value) || (value as number) < 1) {
    invalidContract(`${name} must be a positive integer`);
  }
  return value as number;
}

function requireInteger(record: Record<string, unknown>, name: string): number {
  const value = record[name];
  if (!Number.isInteger(value)) invalidContract(`${name} must be an integer`);
  return value as number;
}

function requireAffixes(value: unknown, name: string): Affixes {
  const record = requireRecord(value, name);
  return {
    prefix: requireString(record, "prefix"),
    suffix: requireString(record, "suffix"),
  };
}

function compileSegment(value: unknown): Segment {
  const raw = requireRecord(value, "segment");
  const name = raw.name;
  if (typeof name !== "string" || !SEGMENT_NAMES.has(name as SegmentName)) {
    invalidContract(`unknown segment name ${String(name)}`);
  }
  const kind = raw.kind;
  if (typeof kind !== "string" || !SEGMENT_KINDS.has(kind as SegmentKind)) {
    invalidContract("segment kind must be numeric or day_period");
  }
  const run = raw.run;
  if (typeof run !== "string" || !SEGMENT_RUNS.has(run as SegmentRun)) {
    invalidContract("segment run must be date or time");
  }

  // Only numeric segments are zero-padded, so only they need a positive width;
  // the day period carries 0 rather than a meaningless 1.
  const displayMinimumDigits =
    kind === "numeric" ? requirePositiveInteger(raw, "display_min_digits") : 0;
  if (displayMinimumDigits > 21) {
    invalidContract("display_min_digits must be no greater than 21");
  }
  const minimumValue = requireInteger(raw, "min_value");
  const maximumValue = requireInteger(raw, "max_value");
  if (minimumValue > maximumValue) invalidContract("min_value must not exceed max_value");

  return {
    name: name as SegmentName,
    kind: kind as SegmentKind,
    run: run as SegmentRun,
    placeholder: requireString(raw, "placeholder"),
    inputLength: requirePositiveInteger(raw, "input_length"),
    displayMinimumDigits,
    minimumValue,
    maximumValue,
    display: requireAffixes(raw.display, "display"),
    segmented: requireAffixes(raw.segmented, "segmented"),
  };
}

function compilePresentation(raw: unknown): CompiledPresentation {
  const config = requireRecord(raw, "date-time presentation");
  if (config.version !== 2) invalidContract("version must be 2");

  const locale = requireNonemptyString(config, "locale");
  const timeZone = requireNonemptyString(config, "time_zone");
  const dayPeriods = requireRecord(config.day_periods, "day_periods");
  const profile = requireRecord(config.profile, "profile");
  const segmentsValue = profile.segments;
  if (!Array.isArray(segmentsValue)) invalidContract("profile.segments must be an array");

  const segments = segmentsValue.map(compileSegment);
  const seen = new Set<SegmentName>();
  for (const segment of segments) {
    if (seen.has(segment.name)) invalidContract("segment names must be unique");
    seen.add(segment.name);
  }
  // The widget cannot render a partial date, so this stays a contract-level
  // invariant rather than a per-widget check.
  const dateNames = segments.filter((s) => s.run === "date").map((s) => s.name);
  if (
    dateNames.length !== REQUIRED_DATE_SEGMENTS.length ||
    !REQUIRED_DATE_SEGMENTS.every((name) => dateNames.includes(name))
  ) {
    invalidContract("the date run must contain day, month, and year exactly once");
  }

  const hourCycle = profile.hour_cycle;
  if (hourCycle !== "h12" && hourCycle !== "h23") {
    invalidContract("hour_cycle must be h12 or h23");
  }

  const am = requireString(dayPeriods, "am");
  const pm = requireString(dayPeriods, "pm");
  const dateTimeFormatter = new Intl.DateTimeFormat(locale, {
    calendar: "iso8601",
    numberingSystem: "latn",
    timeZone,
    day: "numeric",
    month: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "numeric",
    hourCycle,
  });
  const calendarMonthYearFormatter = new Intl.DateTimeFormat(locale, {
    calendar: "gregory",
    numberingSystem: "latn",
    timeZone,
    month: "long",
    year: "numeric",
  });
  const calendarWeekdayFormatter = new Intl.DateTimeFormat(locale, {
    calendar: "gregory",
    numberingSystem: "latn",
    timeZone,
    weekday: "short",
  });
  const numberFormats = new Map<number, Intl.NumberFormat>();
  const widths = new Set(
    segments
      .filter((segment) => segment.kind === "numeric")
      .map((segment) => segment.displayMinimumDigits),
  );
  for (const width of widths) {
    numberFormats.set(
      width,
      new Intl.NumberFormat(locale, {
        numberingSystem: "latn",
        useGrouping: false,
        minimumIntegerDigits: width,
        maximumFractionDigits: 0,
      }),
    );
  }

  return {
    locale,
    timeZone,
    segments,
    hourCycle,
    dayPeriods: { am, pm },
    dateTimeFormatter,
    calendarMonthYearFormatter,
    calendarWeekdayFormatter,
    numberFormats,
  };
}

function errorDetail(error: unknown): string {
  try {
    return error instanceof Error ? error.message : String(error);
  } catch {
    return "unknown error";
  }
}

function getPresentation(): CompiledPresentation | null {
  if (cachedPresentation !== undefined) return cachedPresentation;

  try {
    const raw = document.documentElement.getAttribute(CONTRACT_ATTRIBUTE);
    if (raw === null) invalidContract("contract attribute is missing");
    cachedPresentation = compilePresentation(JSON.parse(raw));
  } catch (error) {
    cachedPresentation = null;
    reportClientError("date-time-presentation", errorDetail(error), { toast: false });
  }
  return cachedPresentation;
}

function numericParts(
  formatter: Intl.DateTimeFormat,
  value: Temporal.PlainDateTime,
): Record<NumericPartName, number> {
  const values: Partial<Record<NumericPartName, number>> = {};
  for (const part of formatter.formatToParts(value)) {
    if (!NUMERIC_PART_NAMES.includes(part.type as NumericPartName)) continue;
    const number = Number(part.value);
    if (!Number.isInteger(number)) throw new Error(`invalid numeric ${part.type} part`);
    values[part.type as NumericPartName] = number;
  }
  for (const name of NUMERIC_PART_NAMES) {
    if (values[name] === undefined) throw new Error(`missing numeric ${name} part`);
  }
  return values as Record<NumericPartName, number>;
}

function segmentText(
  segment: Segment,
  presentation: CompiledPresentation,
  parts: Record<NumericPartName, number>,
  value: Temporal.PlainDateTime,
): string {
  if (segment.kind === "day_period") {
    return value.hour < 12 ? presentation.dayPeriods.am : presentation.dayPeriods.pm;
  }
  const numberFormat = presentation.numberFormats.get(segment.displayMinimumDigits);
  if (!numberFormat) throw new Error("missing number formatter");
  return numberFormat.format(parts[segment.name as NumericPartName]);
}

/**
 * Render the segments belonging to `runs`, in profile order.
 *
 * The first emitted segment drops its prefix, which is the one rule that makes
 * date, time, and datetime the same walk: the date/time glue rides on the
 * hour's prefix and disappears when the hour leads.
 */
function formatDateTime(
  iso: string,
  presentation: CompiledPresentation,
  runs: readonly SegmentRun[],
): string {
  const value = Temporal.Instant.from(iso)
    .toZonedDateTimeISO(presentation.timeZone)
    .toPlainDateTime();
  const parts = numericParts(presentation.dateTimeFormatter, value);
  let rendered = "";
  let first = true;
  for (const segment of presentation.segments) {
    if (!runs.includes(segment.run)) continue;
    const prefix = first ? "" : segment.display.prefix;
    rendered += `${prefix}${segmentText(segment, presentation, parts, value)}${segment.display.suffix}`;
    first = false;
  }
  return rendered;
}

/** Convert a civil calendar date to a local-noon instant in the active zone. */
function calendarEpochAtLocalNoon(
  presentation: CompiledPresentation,
  year: number,
  monthIndex: number,
  day: number,
): number {
  return Temporal.PlainDate.from({ year, month: monthIndex + 1, day })
    .toZonedDateTime({
      timeZone: presentation.timeZone,
      plainTime: Temporal.PlainTime.from("12:00"),
    })
    .epochMilliseconds;
}

/** Format a calendar heading through the active presentation contract. */
export function formatCalendarMonthYear(year: number, monthIndex: number): string | null {
  const presentation = getPresentation();
  if (!presentation) return null;

  try {
    return presentation.calendarMonthYearFormatter.format(
      calendarEpochAtLocalNoon(presentation, year, monthIndex, 1),
    );
  } catch (error) {
    reportClientError("date-time-presentation", errorDetail(error), { toast: false });
    return null;
  }
}

/** Return localized weekday labels in the picker’s fixed Monday-first order. */
export function calendarWeekdayLabels(): readonly string[] | null {
  const presentation = getPresentation();
  if (!presentation) return null;

  try {
    // 2000-01-03 was a Monday. Consecutive civil dates preserve the grid order.
    return Array.from({ length: 7 }, (_, offset) =>
      presentation.calendarWeekdayFormatter.format(
        calendarEpochAtLocalNoon(presentation, 2000, 0, 3 + offset),
      ),
    );
  } catch (error) {
    reportClientError("date-time-presentation", errorDetail(error), { toast: false });
    return null;
  }
}

/**
 * The rules a segmented field needs for one segment, from the active contract.
 *
 * Returns `null` when the contract is unusable or does not describe this
 * segment, so the caller can fall back explicitly instead of guessing.
 */
export function segmentRules(name: string): Segment | null {
  const presentation = getPresentation();
  if (!presentation) return null;
  return presentation.segments.find((segment) => segment.name === name) ?? null;
}

/** The active contract's day-period labels, or `null` if it is unusable. */
export function dayPeriodLabels(): { am: string; pm: string } | null {
  return getPresentation()?.dayPeriods ?? null;
}

/**
 * The current wall clock in the contract's zone, shaped for a `datetime-local`
 * input. `null` when the contract is unusable, so callers can degrade to the
 * browser's clock rather than losing the button entirely.
 */
export function nowInPresentationZone(): string | null {
  const presentation = getPresentation();
  if (!presentation) return null;

  try {
    return Temporal.Now.plainDateTimeISO(presentation.timeZone).toString({
      smallestUnit: "minute",
    });
  } catch (error) {
    reportClientError("date-time-presentation", errorDetail(error), { toast: false });
    return null;
  }
}

/** Format a session range with the server-provided browser presentation contract. */
export function formatSessionTimeRange(startISO: string, endISO: string | null): string | null {
  const presentation = getPresentation();
  if (!presentation) return null;

  try {
    const start = formatDateTime(startISO, presentation, ["date", "time"]);
    return endISO === null
      ? start
      : `${start} — ${formatDateTime(endISO, presentation, ["time"])}`;
  } catch (error) {
    reportClientError("date-time-presentation", errorDetail(error), { toast: false });
    return null;
  }
}
