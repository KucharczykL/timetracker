// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { DateTimePresentationConfig } from "./generated/date-time-presentation.js";

const reportClientError = vi.hoisted(() => vi.fn());

vi.mock("./client-errors.js", () => ({ reportClientError }));

const CONTRACT_ATTRIBUTE = "data-date-time-presentation";

function validConfig(): DateTimePresentationConfig {
  return {
    version: 1,
    locale: "en-US",
    time_zone: "Europe/Prague",
    day_periods: { am: "AM", pm: "PM" },
    profile: {
      date_parts: [
        { name: "day", placeholder: "DD", input_length: 2, display_min_digits: 2 },
        { name: "month", placeholder: "MM", input_length: 2, display_min_digits: 2 },
        { name: "year", placeholder: "YYYY", input_length: 4, display_min_digits: 4 },
      ],
      date_separator: "/",
      segmented_date_separator: "-",
      time_separator: ":",
      date_time_separator: " ",
      hour_cycle: "h23",
    },
  };
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

const invalidContracts = [
  { name: "an absent contract", raw: null },
  { name: "invalid JSON", raw: "{not json" },
  { name: "a v2 contract", raw: JSON.stringify({ ...validConfig(), version: 2 }) },
  { name: "a non-record profile", raw: JSON.stringify({ ...validConfig(), profile: [] }) },
  {
    name: "duplicate and missing date parts",
    raw: JSON.stringify(
      alteredConfig((config) => {
        config.profile.date_parts[2] = {
          name: "day",
          placeholder: "DD",
          input_length: 2,
          display_min_digits: 2,
        };
      }),
    ),
  },
  {
    name: "a non-string placeholder",
    raw: JSON.stringify(
      alteredConfig((config) => {
        (config.profile.date_parts[0] as { placeholder: unknown }).placeholder = 1;
      }),
    ),
  },
  {
    name: "non-string separators",
    raw: JSON.stringify(
      alteredConfig((config) => {
        (config.profile as { date_separator: unknown }).date_separator = 1;
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
        config.profile.date_parts[0].input_length = 0;
      }),
    ),
  },
  {
    name: "a display width of zero",
    raw: JSON.stringify(
      alteredConfig((config) => {
        config.profile.date_parts[0].display_min_digits = 0;
      }),
    ),
  },
  {
    name: "a display width above Intl's maximum",
    raw: JSON.stringify(
      alteredConfig((config) => {
        config.profile.date_parts[0].display_min_digits = 22;
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
    ).toBe("02/07/2026 19:05 — 21:15");
    expect(reportClientError).not.toHaveBeenCalled();
  });

  it("converts an instant into the configured zone before extracting date parts", async () => {
    installConfig(
      alteredConfig((config) => {
        config.time_zone = "Pacific/Kiritimati";
      }),
    );
    const { formatSessionTimeRange } = await importFormatter();

    expect(formatSessionTimeRange("2026-01-01T23:30:00Z", null)).toBe("02/01/2026 13:30");
  });

  it("uses the contract's date order, punctuation, and display widths", async () => {
    installConfig(
      alteredConfig((config) => {
        config.profile.date_parts = [
          { name: "year", placeholder: "YEAR", input_length: 9, display_min_digits: 1 },
          { name: "month", placeholder: "MONTH", input_length: 8, display_min_digits: 1 },
          { name: "day", placeholder: "DAY", input_length: 7, display_min_digits: 1 },
        ];
        config.profile.date_separator = "·";
        config.profile.time_separator = "h";
        config.profile.date_time_separator = " @ ";
      }),
    );
    const { formatSessionTimeRange } = await importFormatter();

    expect(formatSessionTimeRange("2026-07-02T17:05:00Z", null)).toBe("2026·7·2 @ 19h05");
  });

  it("uses the contract's h12 day-period labels instead of Intl labels", async () => {
    installConfig(
      alteredConfig((config) => {
        config.profile.hour_cycle = "h12";
        config.day_periods = { am: "before", pm: "after" };
      }),
    );
    const { formatSessionTimeRange } = await importFormatter();

    expect(
      formatSessionTimeRange("2026-07-02T03:05:00Z", "2026-07-02T17:15:00Z"),
    ).toBe("02/07/2026 05:05 before — 07:15 after");
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
});
