// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from "vitest";
import type {
  DateTimePresentationConfig,
  HourCycle,
  SegmentConfig,
  SegmentName,
  SegmentRun,
} from "./generated/date-time-presentation.js";

const reportClientError = vi.hoisted(() => vi.fn());

vi.mock("./client-errors.js", () => ({ reportClientError }));

const CONTRACT_ATTRIBUTE = "data-date-time-presentation";

function segment(
  name: SegmentName,
  run: SegmentRun,
  prefix: string,
  overrides: Partial<SegmentConfig> = {},
): SegmentConfig {
  const width = name === "year" ? 4 : 2;
  return {
    name,
    kind: "numeric",
    run,
    placeholder: name.toUpperCase(),
    input_length: width,
    display_min_digits: width,
    min_value: 0,
    max_value: 9999,
    display: { prefix, suffix: "" },
    segmented: { prefix, suffix: "" },
    ...overrides,
  };
}

function dateSegments(order: SegmentName[], separator: string): SegmentConfig[] {
  return order.map((name, index) =>
    segment(name, "date", index === 0 ? "" : separator),
  );
}

function timeSegments(
  hourCycle: HourCycle,
  timeSeparator: string,
  dateTimeSeparator: string,
): SegmentConfig[] {
  const segments = [
    segment("hour", "time", dateTimeSeparator, {
      min_value: hourCycle === "h12" ? 1 : 0,
      max_value: hourCycle === "h12" ? 12 : 23,
    }),
    segment("minute", "time", timeSeparator, { min_value: 0, max_value: 59 }),
  ];
  if (hourCycle === "h23") return segments;
  return [
    ...segments,
    segment("day_period", "time", " ", {
      kind: "day_period",
      placeholder: "--",
      display_min_digits: 0,
      min_value: 0,
      max_value: 1,
    }),
  ];
}

function configWith(
  order: SegmentName[],
  {
    hourCycle = "h23" as HourCycle,
    dateSeparator = "-",
    timeSeparator = ":",
    dateTimeSeparator = " ",
  } = {},
): DateTimePresentationConfig {
  return {
    version: 2,
    locale: "en-US",
    time_zone: "Europe/Prague",
    day_periods: { am: "AM", pm: "PM" },
    session_time_zone_display: "account",
    profile: {
      segments: [
        ...dateSegments(order, dateSeparator),
        ...timeSegments(hourCycle, timeSeparator, dateTimeSeparator),
      ],
      hour_cycle: hourCycle,
    },
  };
}

function validConfig(): DateTimePresentationConfig {
  return configWith(["year", "month", "day"]);
}

function installConfig(config: unknown): void {
  document.documentElement.setAttribute(CONTRACT_ATTRIBUTE, JSON.stringify(config));
}

async function importFormatter(): Promise<typeof import("./date-time-presentation.js")> {
  vi.resetModules();
  return import("./date-time-presentation.js");
}

function alteredConfig(change: (config: DateTimePresentationConfig) => void): unknown {
  const config = validConfig();
  change(config);
  return config;
}

/** The first segment of the date run — the one every shape test reaches for. */
function firstSegment(config: DateTimePresentationConfig): SegmentConfig {
  return config.profile.segments[0];
}

const invalidContracts = [
  { name: "an absent contract", raw: null },
  { name: "invalid JSON", raw: "{not json" },
  // v1 is the shape this validator used to accept; it must now be rejected.
  { name: "a v1 contract", raw: JSON.stringify({ ...validConfig(), version: 1 }) },
  { name: "a non-record profile", raw: JSON.stringify({ ...validConfig(), profile: [] }) },
  {
    name: "duplicate segment names",
    raw: JSON.stringify(
      alteredConfig((config) => {
        config.profile.segments[0] = segment("day", "date", "");
      }),
    ),
  },
  {
    name: "an incomplete date run",
    raw: JSON.stringify(
      alteredConfig((config) => {
        config.profile.segments = config.profile.segments.filter(
          (part) => part.name !== "month",
        );
      }),
    ),
  },
  {
    name: "an unknown segment name",
    raw: JSON.stringify(
      alteredConfig((config) => {
        (firstSegment(config) as { name: unknown }).name = "century";
      }),
    ),
  },
  {
    name: "an unknown segment kind",
    raw: JSON.stringify(
      alteredConfig((config) => {
        (firstSegment(config) as { kind: unknown }).kind = "text";
      }),
    ),
  },
  {
    name: "an unknown segment run",
    raw: JSON.stringify(
      alteredConfig((config) => {
        (firstSegment(config) as { run: unknown }).run = "era";
      }),
    ),
  },
  {
    name: "inverted bounds",
    raw: JSON.stringify(
      alteredConfig((config) => {
        firstSegment(config).min_value = 10;
        firstSegment(config).max_value = 1;
      }),
    ),
  },
  {
    name: "a non-integer bound",
    raw: JSON.stringify(
      alteredConfig((config) => {
        (firstSegment(config) as { min_value: unknown }).min_value = "1";
      }),
    ),
  },
  {
    name: "a non-string placeholder",
    raw: JSON.stringify(
      alteredConfig((config) => {
        (firstSegment(config) as { placeholder: unknown }).placeholder = 1;
      }),
    ),
  },
  {
    name: "a non-record affix group",
    raw: JSON.stringify(
      alteredConfig((config) => {
        (firstSegment(config) as { display: unknown }).display = "-";
      }),
    ),
  },
  {
    name: "a non-string affix",
    raw: JSON.stringify(
      alteredConfig((config) => {
        (firstSegment(config).display as { prefix: unknown }).prefix = 1;
      }),
    ),
  },
  {
    name: "a non-string day-period label",
    raw: JSON.stringify(
      alteredConfig((config) => {
        (config.day_periods as { am: unknown }).am = 1;
      }),
    ),
  },
  {
    name: "an unsupported hour cycle",
    raw: JSON.stringify(
      alteredConfig((config) => {
        (config.profile as { hour_cycle: unknown }).hour_cycle = "h24";
      }),
    ),
  },
  {
    name: "an invalid locale",
    raw: JSON.stringify(
      alteredConfig((config) => {
        config.locale = "not a locale";
      }),
    ),
  },
  {
    name: "an invalid time zone",
    raw: JSON.stringify(
      alteredConfig((config) => {
        config.time_zone = "Mars/Olympus";
      }),
    ),
  },
  {
    name: "an input width of zero",
    raw: JSON.stringify(
      alteredConfig((config) => {
        firstSegment(config).input_length = 0;
      }),
    ),
  },
  {
    name: "a display width of zero",
    raw: JSON.stringify(
      alteredConfig((config) => {
        firstSegment(config).display_min_digits = 0;
      }),
    ),
  },
  {
    name: "a display width above Intl's maximum",
    raw: JSON.stringify(
      alteredConfig((config) => {
        firstSegment(config).display_min_digits = 22;
      }),
    ),
  },
];


describe("nowInPresentationZone", () => {
  beforeEach(() => {
    reportClientError.mockClear();
    document.documentElement.removeAttribute(CONTRACT_ATTRIBUTE);
  });

  it("reads the clock in the contract's zone, not the browser's", async () => {
    installConfig(
      alteredConfig((config) => {
        // Fixed UTC+14 year-round, so the expected offset needs no DST logic
        // and is far enough from any plausible test-runner zone to be decisive.
        config.time_zone = "Pacific/Kiritimati";
      }),
    );
    const { nowInPresentationZone } = await importFormatter();

    const value = nowInPresentationZone();
    expect(value).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/);

    const minutesAheadOfUTC = Temporal.PlainDateTime.from(value!)
      .since(Temporal.Now.plainDateTimeISO("UTC"))
      .total({ unit: "minute" });
    expect(Math.abs(minutesAheadOfUTC - 14 * 60)).toBeLessThan(2);
    expect(reportClientError).not.toHaveBeenCalled();
  });

  it("truncates to the minute the datetime-local input accepts", async () => {
    installConfig(validConfig());
    const { nowInPresentationZone } = await importFormatter();

    expect(nowInPresentationZone()).toHaveLength("2026-07-27T08:34".length);
  });

  it("returns null on a missing contract so callers can degrade", async () => {
    const { nowInPresentationZone } = await importFormatter();

    expect(nowInPresentationZone()).toBeNull();
    expect(reportClientError).toHaveBeenCalledTimes(1);
  });

  it("projects into an override zone when one is named", async () => {
    installConfig(
      alteredConfig((config) => {
        // The contract says +14 year-round; the override says +09. Reading
        // back +09 is only possible if the override won.
        config.time_zone = "Pacific/Kiritimati";
      }),
    );
    const { nowInPresentationZone } = await importFormatter();

    const value = nowInPresentationZone("Asia/Tokyo");
    expect(value).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/);

    const minutesAheadOfUTC = Temporal.PlainDateTime.from(value!)
      .since(Temporal.Now.plainDateTimeISO("UTC"))
      .total({ unit: "minute" });
    expect(Math.abs(minutesAheadOfUTC - 9 * 60)).toBeLessThan(2);
    expect(reportClientError).not.toHaveBeenCalled();
  });

  it("toasts and returns null for an override zone tzdata does not know", async () => {
    installConfig(validConfig());
    const { nowInPresentationZone } = await importFormatter();

    expect(nowInPresentationZone("Not/AZone")).toBeNull();
    // A click is waiting on this one, unlike the contract-zone failures.
    expect(reportClientError).toHaveBeenCalledWith(
      "date-time-presentation",
      expect.any(String),
      { toast: true },
    );
  });
});

describe("calendar presentation", () => {
  beforeEach(() => {
    reportClientError.mockClear();
    document.documentElement.removeAttribute(CONTRACT_ATTRIBUTE);
  });

  it("formats localized calendar chrome from the configured presentation", async () => {
    installConfig(
      alteredConfig((config) => {
        config.locale = "cs-CZ";
        config.time_zone = "Europe/Prague";
      }),
    );
    const { calendarWeekdayLabels, formatCalendarMonthYear } = await importFormatter();

    expect(formatCalendarMonthYear(2026, 0)).toBe("leden 2026");
    expect(calendarWeekdayLabels()).toEqual(["po", "út", "st", "čt", "pá", "so", "ne"]);
    expect(reportClientError).not.toHaveBeenCalled();
  });

  it.each(["America/Adak", "Pacific/Kiritimati"])(
    "keeps civil calendar dates stable in %s",
    async (timeZone) => {
      installConfig(
        alteredConfig((config) => {
          config.time_zone = timeZone;
        }),
      );
      const { calendarWeekdayLabels, formatCalendarMonthYear } = await importFormatter();

      expect(formatCalendarMonthYear(2026, 0)).toBe("January 2026");
      expect(calendarWeekdayLabels()).toEqual(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]);
    },
  );

  it("returns null calendar chrome and reports a missing contract once", async () => {
    const { calendarWeekdayLabels, formatCalendarMonthYear } = await importFormatter();

    expect(formatCalendarMonthYear(2026, 0)).toBeNull();
    expect(calendarWeekdayLabels()).toBeNull();
    expect(reportClientError).toHaveBeenCalledTimes(1);
    expect(reportClientError).toHaveBeenCalledWith(
      "date-time-presentation",
      expect.any(String),
      { toast: false },
    );
  });
});

describe("todayInPresentationZone", () => {
  beforeEach(() => {
    reportClientError.mockClear();
    document.documentElement.removeAttribute(CONTRACT_ATTRIBUTE);
  });

  it("names the day in the contract's zone, not the browser's", async () => {
    installConfig(
      alteredConfig((config) => {
        // Fixed UTC+14 year-round: the furthest tzdata gets from any plausible
        // test-runner zone, so a browser-clock answer cannot pass by accident.
        config.time_zone = "Pacific/Kiritimati";
      }),
    );
    const { todayInPresentationZone } = await importFormatter();

    expect(todayInPresentationZone()).toBe(
      new Intl.DateTimeFormat("en-CA", {
        timeZone: "Pacific/Kiritimati",
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
      }).format(new Date()),
    );
    expect(reportClientError).not.toHaveBeenCalled();
  });

  it("returns null on a missing contract so callers can degrade", async () => {
    const { todayInPresentationZone } = await importFormatter();

    expect(todayInPresentationZone()).toBeNull();
    expect(reportClientError).toHaveBeenCalledTimes(1);
  });
});
