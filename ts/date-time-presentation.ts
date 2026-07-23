import { reportClientError } from "./client-errors.js";
import type { DatePartName, HourCycle } from "./generated/date-time-presentation.js";

const CONTRACT_ATTRIBUTE = "data-date-time-presentation";
const DATE_PART_NAMES = new Set<DatePartName>(["day", "month", "year"]);
const TIME_MINIMUM_DIGITS = 2;
const NUMERIC_PART_NAMES = ["day", "month", "year", "hour", "minute"] as const;

type NumericPartName = (typeof NUMERIC_PART_NAMES)[number];

interface DatePart {
  name: DatePartName;
  displayMinimumDigits: number;
}

interface CompiledPresentation {
  locale: string;
  timeZone: string;
  dateParts: DatePart[];
  dateSeparator: string;
  timeSeparator: string;
  dateTimeSeparator: string;
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

function compilePresentation(raw: unknown): CompiledPresentation {
  const config = requireRecord(raw, "date-time presentation");
  if (config.version !== 1) invalidContract("version must be 1");

  const locale = requireNonemptyString(config, "locale");
  const timeZone = requireNonemptyString(config, "time_zone");
  const dayPeriods = requireRecord(config.day_periods, "day_periods");
  const profile = requireRecord(config.profile, "profile");
  const datePartsValue = profile.date_parts;
  if (!Array.isArray(datePartsValue)) invalidContract("profile.date_parts must be an array");

  const dateParts: DatePart[] = [];
  const seenDateParts = new Set<DatePartName>();
  for (const value of datePartsValue) {
    const part = requireRecord(value, "date part");
    const name = part.name;
    if (typeof name !== "string" || !DATE_PART_NAMES.has(name as DatePartName)) {
      invalidContract("date part name must be day, month, or year");
    }
    if (seenDateParts.has(name as DatePartName)) invalidContract("date part names must be unique");
    seenDateParts.add(name as DatePartName);

    requireString(part, "placeholder");
    requirePositiveInteger(part, "input_length");
    const displayMinimumDigits = requirePositiveInteger(part, "display_min_digits");
    if (displayMinimumDigits > 21) {
      invalidContract("display_min_digits must be no greater than 21");
    }
    dateParts.push({ name: name as DatePartName, displayMinimumDigits });
  }
  if (dateParts.length !== 3 || seenDateParts.size !== 3) {
    invalidContract("date_parts must contain day, month, and year exactly once");
  }

  const dateSeparator = requireString(profile, "date_separator");
  requireString(profile, "segmented_date_separator");
  const timeSeparator = requireString(profile, "time_separator");
  const dateTimeSeparator = requireString(profile, "date_time_separator");
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
  const widths = new Set([...dateParts.map((part) => part.displayMinimumDigits), TIME_MINIMUM_DIGITS]);
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
    dateParts,
    dateSeparator,
    timeSeparator,
    dateTimeSeparator,
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

function formatDateTime(
  iso: string,
  presentation: CompiledPresentation,
  includeDate: boolean,
): string {
  const value = Temporal.Instant.from(iso)
    .toZonedDateTimeISO(presentation.timeZone)
    .toPlainDateTime();
  const formatter = presentation.dateTimeFormatter;
  const parts = numericParts(formatter, value);
  const date = includeDate
    ? presentation.dateParts
        .map((part) => {
          const numberFormat = presentation.numberFormats.get(part.displayMinimumDigits);
          if (!numberFormat) throw new Error("missing date number formatter");
          return numberFormat.format(parts[part.name]);
        })
        .join(presentation.dateSeparator) + presentation.dateTimeSeparator
    : "";
  const timeNumberFormat = presentation.numberFormats.get(TIME_MINIMUM_DIGITS);
  if (!timeNumberFormat) throw new Error("missing time number formatter");
  const time = `${timeNumberFormat.format(parts.hour)}` +
    `${presentation.timeSeparator}${timeNumberFormat.format(parts.minute)}`;
  const dayPeriod =
    presentation.hourCycle === "h12"
      ? ` ${value.hour < 12 ? presentation.dayPeriods.am : presentation.dayPeriods.pm}`
      : "";
  return `${date}${time}${dayPeriod}`;
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

/** Format a session range with the server-provided browser presentation contract. */
export function formatSessionTimeRange(startISO: string, endISO: string | null): string | null {
  const presentation = getPresentation();
  if (!presentation) return null;

  try {
    const start = formatDateTime(startISO, presentation, true);
    return endISO === null ? start : `${start} — ${formatDateTime(endISO, presentation, false)}`;
  } catch (error) {
    reportClientError("date-time-presentation", errorDetail(error), { toast: false });
    return null;
  }
}
