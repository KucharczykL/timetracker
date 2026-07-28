// @vitest-environment jsdom
import { describe, expect, it, vi } from "vitest";

const presentationClock = vi.hoisted(() =>
  vi.fn<() => { timeZone: string; hourCycle: "h12" | "h23" } | null>(),
);
const dayPeriodLabels = vi.hoisted(() =>
  vi.fn<() => { am: string; pm: string } | null>(() => ({ am: "AM", pm: "PM" })),
);
const reportClientError = vi.hoisted(() => vi.fn());

vi.mock("../date-time-presentation.js", () => ({
  presentationClock,
  dayPeriodLabels,
  // The engine module the codec's paste grammar delegates its date half to
  // reads these; both are absent on a page with no contract.
  segmentRules: () => null,
}));

vi.mock("../client-errors.js", () => ({ reportClientError }));

async function codecModule(timeZone: string, hourCycle: "h12" | "h23") {
  presentationClock.mockReturnValue({ timeZone, hourCycle });
  vi.resetModules();
  return import("./date-time-codec.js");
}

async function codecFor(
  timeZone: string,
  hourCycle: "h12" | "h23" = "h23",
  initialValue = "",
) {
  const { createDateTimeCodec } = await codecModule(timeZone, hourCycle);
  return createDateTimeCodec(initialValue);
}

const PARTS = {
  year: "2026",
  month: "07",
  day: "27",
  hour: "14",
  minute: "30",
};

describe("date-time codec encode", () => {
  it("emits an offset-qualified wall clock, not a UTC instant", async () => {
    const codec = await codecFor("Europe/Prague");

    // The typed wall clock survives verbatim; the offset rides alongside it.
    // Django binds this aware, and a later per-timestamp timezone can read
    // back both halves.
    expect(codec.encode(PARTS, true)).toBe("2026-07-27T14:30:00.000000+02:00");
  });

  it("returns nothing while the field is incomplete", async () => {
    const codec = await codecFor("Europe/Prague");

    expect(codec.encode({ ...PARTS, minute: "" }, false)).toBe("");
  });

  it("resolves an ambiguous wall clock to the earlier offset", async () => {
    const codec = await codecFor("America/New_York");

    // 2026-11-01T01:30 happens twice; "earlier" picks EDT (-04:00).
    expect(
      codec.encode({ ...PARTS, month: "11", day: "01", hour: "01", minute: "30" }, true),
    ).toBe("2026-11-01T01:30:00.000000-04:00");
  });

  it("submits a bare wall clock for a nonexistent time so the server rejects it", async () => {
    const codec = await codecFor("America/New_York");

    // 2026-03-08T02:30 does not exist. Temporal would happily shift it; we
    // detect the shift by round-tripping and hand Django the naive value,
    // which produces the existing "couldn't be interpreted" error.
    expect(
      codec.encode({ ...PARTS, month: "03", day: "08", hour: "02", minute: "30" }, true),
    ).toBe("2026-03-08T02:30:00.000000");
  });

  it("keeps the seconds and microseconds it was rendered with", async () => {
    // duration_calculated is a generated column over both timestamps, so
    // dropping sub-minute precision on an untouched edit shifts durations.
    const codec = await codecFor(
      "Europe/Prague",
      "h23",
      "2026-07-27T14:30:41.123456+02:00",
    );

    expect(codec.encode(PARTS, true)).toBe("2026-07-27T14:30:41.123456+02:00");
  });

  it("folds a 12-hour clock and its day period into a 24-hour wall clock", async () => {
    const codec = await codecFor("Europe/Prague", "h12");

    const afternoon = { ...PARTS, hour: "02", minute: "30", day_period: "01" };
    expect(codec.encode(afternoon, true)).toBe("2026-07-27T14:30:00.000000+02:00");

    const midnight = { ...PARTS, hour: "12", minute: "05", day_period: "00" };
    expect(codec.encode(midnight, true)).toBe("2026-07-27T00:05:00.000000+02:00");

    const noon = { ...PARTS, hour: "12", minute: "05", day_period: "01" };
    expect(codec.encode(noon, true)).toBe("2026-07-27T12:05:00.000000+02:00");
  });

  it("encodes nothing when the contract is unusable", async () => {
    presentationClock.mockReturnValue(null);
    vi.resetModules();
    const { createDateTimeCodec } = await import("./date-time-codec.js");

    expect(createDateTimeCodec("").encode(PARTS, true)).toBe("");
  });

  it("encodes against the zone the resolver names, not the contract's", async () => {
    const { createDateTimeCodec } = await codecModule("Europe/Prague", "h23");
    const codec = createDateTimeCodec("", () => "Asia/Tokyo");

    expect(codec.encode(PARTS, true)).toBe("2026-07-27T14:30:00.000000+09:00");
  });

  it("falls back to the contract zone when the resolver has nothing", async () => {
    const { createDateTimeCodec } = await codecModule("Europe/Prague", "h23");
    const codec = createDateTimeCodec("", () => null);

    expect(codec.encode(PARTS, true)).toBe("2026-07-27T14:30:00.000000+02:00");
  });

  it("submits a resolver-zone DST gap bare, exactly like a contract-zone gap", async () => {
    const { createDateTimeCodec } = await codecModule("Asia/Tokyo", "h23");
    const codec = createDateTimeCodec("", () => "America/New_York");

    // 02:30 on 2026-03-08 does not exist in New York; Tokyo would accept it.
    expect(
      codec.encode({ ...PARTS, month: "03", day: "08", hour: "02" }, true),
    ).toBe("2026-03-08T02:30:00.000000");
  });

  it("submits bare when the resolver names a zone this runtime does not know", async () => {
    const { createDateTimeCodec } = await codecModule("Europe/Prague", "h23");
    const codec = createDateTimeCodec("", () => "Not/AZone");

    expect(codec.encode(PARTS, true)).toBe("2026-07-27T14:30:00.000000");
    expect(reportClientError).toHaveBeenCalled();
  });
});

describe("date-time codec decode", () => {
  it("splits an offset-qualified value into segments", async () => {
    const codec = await codecFor("Europe/Prague");

    expect(codec.decode("2026-07-27T14:30:41.123456+02:00")).toMatchObject({
      year: "2026",
      month: "07",
      day: "27",
      hour: "14",
      minute: "30",
    });
  });

  it("also reads the naive shape a rejected submission renders back", async () => {
    // A DST-gap rejection re-renders the form bound, and BoundField.value()
    // hands back the raw POST string — which has no offset. Without this the
    // field would come back empty and eat the user's input.
    const codec = await codecFor("Europe/Prague");

    expect(codec.decode("2026-03-08T02:30:00.000000")).toMatchObject({
      year: "2026",
      month: "03",
      day: "08",
      hour: "02",
      minute: "30",
    });
  });

  it("also reads the datetime-local shape, with no seconds", async () => {
    const codec = await codecFor("Europe/Prague");

    expect(codec.decode("2026-07-27T14:30")).toMatchObject({
      hour: "14",
      minute: "30",
    });
  });

  it("splits a 12-hour clock back into hour and day period", async () => {
    const codec = await codecFor("Europe/Prague", "h12");

    expect(codec.decode("2026-07-27T14:30:00.000000+02:00")).toMatchObject({
      hour: "02",
      minute: "30",
      day_period: "01",
    });
    expect(codec.decode("2026-07-27T00:05:00.000000+02:00")).toMatchObject({
      hour: "12",
      day_period: "00",
    });
    expect(codec.decode("2026-07-27T12:05:00.000000+02:00")).toMatchObject({
      hour: "12",
      day_period: "01",
    });
  });

  it("returns empty segments for a blank or unparseable value", async () => {
    const codec = await codecFor("Europe/Prague");

    for (const value of ["", "not a datetime"]) {
      expect(codec.decode(value)).toMatchObject({
        year: "",
        month: "",
        day: "",
        hour: "",
        minute: "",
      });
    }
  });

  it("round-trips what it encodes", async () => {
    const codec = await codecFor("Europe/Prague", "h12");
    const parts = { ...PARTS, hour: "02", minute: "30", day_period: "01" };

    expect(codec.decode(codec.encode(parts, true))).toMatchObject(parts);
  });
});

describe("pasted wall clock", () => {
  const ISO_DATE_PARTS = ["year", "month", "day"];
  const MDY_DATE_PARTS = ["month", "day", "year"];

  async function parse(text: string, dateParts = ISO_DATE_PARTS, hourCycle: "h12" | "h23" = "h23") {
    const { parsePastedWallClock } = await codecModule("Europe/Prague", hourCycle);
    return parsePastedWallClock(text, dateParts);
  }

  it("reads an ISO datetime, T glue and all", async () => {
    expect(await parse("2026-07-27T14:30")).toEqual({
      date: "2026-07-27",
      hour: "14",
      minute: "30",
    });
  });

  it("drops seconds and a trailing offset, which the segments do not show", async () => {
    expect(await parse("2026-07-27T14:30:59.123456+02:00")).toEqual({
      date: "2026-07-27",
      hour: "14",
      minute: "30",
    });
  });

  it("folds a day period in the profile's own order", async () => {
    expect(await parse("07/27/2026 02:30 PM", MDY_DATE_PARTS, "h12")).toEqual({
      date: "2026-07-27",
      hour: "14",
      minute: "30",
    });
  });

  it("reads midnight from a 12-hour clock", async () => {
    expect(await parse("07/27/2026 12:30 AM", MDY_DATE_PARTS, "h12")).toEqual({
      date: "2026-07-27",
      hour: "00",
      minute: "30",
    });
  });

  it("accepts a bare date, leaving the time to the caller", async () => {
    expect(await parse("2026-07-27")).toEqual({ date: "2026-07-27", hour: "", minute: "" });
  });

  it("accepts a bare time, leaving the date to the caller", async () => {
    expect(await parse("14:30")).toEqual({ date: "", hour: "14", minute: "30" });
  });

  it("refuses a half it cannot read rather than taking the other one", async () => {
    // A present-but-unreadable half means the text was something else; keeping
    // the readable half of it would be a guess.
    expect(await parse("not a date 14:30")).toBeNull();
    expect(await parse("2026-07-27 25:99")).toBeNull();
    expect(await parse("hello")).toBeNull();
  });

  it("still refuses a 2-digit year, like the date grammar it delegates to", async () => {
    expect(await parse("26-07-27 14:30")).toBeNull();
  });
});
