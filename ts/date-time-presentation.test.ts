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

describe("formatSessionTimeRange", () => {
  beforeEach(() => {
    reportClientError.mockClear();
    document.documentElement.removeAttribute(CONTRACT_ATTRIBUTE);
  });

  it("formats a finished default range", async () => {
    installConfig(validConfig());
    const { formatSessionTimeRange } = await importFormatter();

    expect(
      formatSessionTimeRange("2026-07-02T17:05:00Z", "2026-07-02T19:15:00Z"),
    ).toBe("2026-07-02 19:05 — 21:15");
    expect(reportClientError).not.toHaveBeenCalled();
  });

  it("converts an instant into the configured zone before extracting date parts", async () => {
    installConfig(
      alteredConfig((config) => {
        config.time_zone = "Pacific/Kiritimati";
      }),
    );
    const { formatSessionTimeRange } = await importFormatter();

    expect(formatSessionTimeRange("2026-01-01T23:30:00Z", null)).toBe("2026-01-02 13:30");
  });

  it("uses the contract's segment order, punctuation, and display widths", async () => {
    installConfig(
      alteredConfig((config) => {
        const narrowed = configWith(["year", "month", "day"], {
          dateSeparator: "·",
          timeSeparator: "h",
          dateTimeSeparator: " @ ",
        });
        for (const part of narrowed.profile.segments) {
          if (part.run === "date") part.display_min_digits = 1;
        }
        config.profile = narrowed.profile;
      }),
    );
    const { formatSessionTimeRange } = await importFormatter();

    expect(formatSessionTimeRange("2026-07-02T17:05:00Z", null)).toBe("2026·7·2 @ 19h05");
  });

  it("renders a segment's suffix, not only its prefix", async () => {
    installConfig(
      alteredConfig((config) => {
        // The suffix-shaped case a leading-separator-only model cannot express.
        const labels = ["年", "月", "日"];
        config.profile.segments
          .filter((part) => part.run === "date")
          .forEach((part, index) => {
            part.display = { prefix: "", suffix: labels[index] };
          });
      }),
    );
    const { formatSessionTimeRange } = await importFormatter();

    // The date run's own prefixes are gone, but the hour keeps the date/time
    // glue on its prefix — the two sides compose rather than replacing.
    expect(formatSessionTimeRange("2026-07-02T17:05:00Z", null)).toBe(
      "2026年07月02日 19:05",
    );
  });

  it("uses the contract's h12 day-period labels instead of Intl labels", async () => {
    installConfig(
      alteredConfig((config) => {
        config.profile = configWith(["year", "month", "day"], {
          hourCycle: "h12",
        }).profile;
        config.day_periods = { am: "before", pm: "after" };
      }),
    );
    const { formatSessionTimeRange } = await importFormatter();

    expect(
      formatSessionTimeRange("2026-07-02T03:05:00Z", "2026-07-02T17:15:00Z"),
    ).toBe("2026-07-02 05:05 before — 07:15 after");
  });

  it("formats the registered DMY 24-hour profile", async () => {
    installConfig(
      configWith(["day", "month", "year"], { dateSeparator: "/" }),
    );
    const { formatSessionTimeRange } = await importFormatter();

    expect(
      formatSessionTimeRange("2026-07-02T17:05:00Z", "2026-07-02T19:15:00Z"),
    ).toBe("02/07/2026 19:05 — 21:15");
  });

  it("formats the registered MDY 12-hour profile", async () => {
    installConfig(
      configWith(["month", "day", "year"], {
        dateSeparator: "/",
        hourCycle: "h12",
      }),
    );
    const { formatSessionTimeRange } = await importFormatter();

    expect(
      formatSessionTimeRange("2026-07-02T17:05:00Z", "2026-07-02T19:15:00Z"),
    ).toBe("07/02/2026 07:05 PM — 09:15 PM");
  });

  it.each(invalidContracts)("returns null and reports $name only once", async ({ raw }) => {
    if (raw !== null) document.documentElement.setAttribute(CONTRACT_ATTRIBUTE, raw);
    const { formatSessionTimeRange } = await importFormatter();

    expect(formatSessionTimeRange("2026-07-02T17:05:00Z", null)).toBeNull();
    expect(formatSessionTimeRange("2026-07-02T17:05:00Z", null)).toBeNull();
    expect(reportClientError).toHaveBeenCalledTimes(1);
    expect(reportClientError).toHaveBeenCalledWith(
      "date-time-presentation",
      expect.any(String),
      { toast: false },
    );
  });

  it("returns null instead of throwing for a malformed API timestamp", async () => {
    installConfig(validConfig());
    const { formatSessionTimeRange } = await importFormatter();

    expect(() => formatSessionTimeRange("not an ISO timestamp", null)).not.toThrow();
    expect(formatSessionTimeRange("not an ISO timestamp", null)).toBeNull();
    expect(reportClientError).toHaveBeenCalledWith(
      "date-time-presentation",
      expect.any(String),
      { toast: false },
    );
  });

  it("ignores endpoint zones under the account preference", async () => {
    installConfig(
      alteredConfig((config) => {
        config.session_time_zone_display = "account";
      }),
    );
    const { formatSessionTimeRange } = await importFormatter();

    expect(
      formatSessionTimeRange(
        "2026-07-01T12:00:00Z",
        "2026-07-01T13:00:00Z",
        { zone: "Asia/Tokyo", label: "JST" },
        { zone: "Asia/Tokyo", label: "JST" },
      ),
    ).toBe("2026-07-01 14:00 — 15:00");
  });

  it("renders the session's own zone with the server's label under the own preference", async () => {
    installConfig(
      alteredConfig((config) => {
        config.session_time_zone_display = "own";
      }),
    );
    const { formatSessionTimeRange } = await importFormatter();

    // The label is the server's string, verbatim — Intl's own "short" name for
    // Asia/Tokyo is "GMT+9", which would silently disagree with the
    // server-rendered rows in the same table.
    expect(
      formatSessionTimeRange(
        "2026-07-01T12:00:00Z",
        "2026-07-01T13:00:00Z",
        { zone: "Asia/Tokyo", label: "JST" },
        { zone: "Asia/Tokyo", label: "JST" },
      ),
    ).toBe("2026-07-01 21:00 JST — 2026-07-01 22:00 JST");
  });

  it("labels only the endpoint the server labelled", async () => {
    installConfig(
      alteredConfig((config) => {
        config.session_time_zone_display = "own";
      }),
    );
    const { formatSessionTimeRange } = await importFormatter();

    expect(
      formatSessionTimeRange(
        "2026-07-01T12:00:00Z",
        "2026-07-01T13:00:00Z",
        { zone: "Europe/Prague", label: null },
        { zone: "Asia/Tokyo", label: "JST" },
      ),
    ).toBe("2026-07-01 14:00 — 2026-07-01 22:00 JST");
  });

  it("gives a labelled end its own date across the date line", async () => {
    installConfig(
      alteredConfig((config) => {
        config.session_time_zone_display = "own";
      }),
    );
    const { formatSessionTimeRange } = await importFormatter();

    // 21:00 UTC is 06:00 the next day in Tokyo; a bare "06:00 JST" after a
    // 14:00 start reads as the same evening.
    expect(
      formatSessionTimeRange(
        "2026-07-01T12:00:00Z",
        "2026-07-01T21:00:00Z",
        { zone: null, label: null },
        { zone: "Asia/Tokyo", label: "JST" },
      ),
    ).toBe("2026-07-01 14:00 — 2026-07-02 06:00 JST");
  });

  it("renders the account zone when the server sent no label", async () => {
    installConfig(
      alteredConfig((config) => {
        config.session_time_zone_display = "own";
      }),
    );
    const { formatSessionTimeRange } = await importFormatter();

    expect(
      formatSessionTimeRange("2026-07-01T12:00:00Z", null, { zone: null, label: null }),
    ).toBe("2026-07-01 14:00");
  });

  it("treats a contract without the display key as account", async () => {
    installConfig(
      alteredConfig((config) => {
        delete (config as Partial<DateTimePresentationConfig>).session_time_zone_display;
      }),
    );
    const { formatSessionTimeRange } = await importFormatter();

    expect(
      formatSessionTimeRange("2026-07-01T12:00:00Z", null, {
        zone: "Asia/Tokyo",
        label: "JST",
      }),
    ).toBe("2026-07-01 14:00");
  });

  it("returns null when the runtime does not know the stored zone", async () => {
    installConfig(
      alteredConfig((config) => {
        config.session_time_zone_display = "own";
      }),
    );
    const { formatSessionTimeRange } = await importFormatter();

    // Null leaves session-row.ts's server-rendered cell untouched, which is
    // the correct value — better than a client guess with a wrong wall clock.
    expect(
      formatSessionTimeRange("2026-07-01T12:00:00Z", null, {
        zone: "Not/AZone",
        label: "XXX",
      }),
    ).toBeNull();
    expect(reportClientError).toHaveBeenCalled();
  });
});

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
