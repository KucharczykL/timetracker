// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Segment } from "../date-time-presentation.js";

const segmentRules = vi.hoisted(() => vi.fn<(name: string) => Segment | null>());
const dayPeriodLabels = vi.hoisted(() =>
  vi.fn<() => { am: string; pm: string } | null>(),
);

const todayInPresentationZone = vi.hoisted(() => vi.fn<() => string | null>(() => null));

vi.mock("../date-time-presentation.js", () => ({
  segmentRules,
  dayPeriodLabels,
  todayInPresentationZone,
}));

function rules(name: string, minimum: number, maximum: number, kind = "numeric"): Segment {
  return {
    name,
    kind,
    run: "date",
    placeholder: name.toUpperCase(),
    inputLength: 2,
    displayMinimumDigits: 2,
    minimumValue: minimum,
    maximumValue: maximum,
    display: { prefix: "", suffix: "" },
    segmented: { prefix: "", suffix: "" },
  } as Segment;
}

function mountSegment(part: string, width = 2, placeholder = "MM"): HTMLInputElement {
  document.body.innerHTML =
    `<div data-field><input data-date-part="${part}" data-date-side="value" ` +
    `maxlength="${width}" placeholder="${placeholder}" /></div>`;
  return document.querySelector("input")!;
}

async function importCore(): Promise<typeof import("./date-field-core.js")> {
  vi.resetModules();
  return import("./date-field-core.js");
}

describe("segmentSpec", () => {
  beforeEach(() => {
    segmentRules.mockReset();
    dayPeriodLabels.mockReset();
    segmentRules.mockReturnValue(null);
    dayPeriodLabels.mockReturnValue(null);
  });

  it("refuses an unknown part instead of treating it as a day", async () => {
    // The old partRange fell through to day (1-31) for anything it did not
    // recognise, so an hour segment would have been silently clamped.
    const { segmentSpec } = await importCore();

    expect(segmentSpec(mountSegment("fortnight"))).toBeNull();
  });

  it("takes bounds from the presentation contract", async () => {
    segmentRules.mockImplementation((name) =>
      name === "hour" ? rules("hour", 1, 12) : null,
    );
    const { segmentSpec } = await importCore();

    const spec = segmentSpec(mountSegment("hour", 2, "HH"));

    // 1-12, not 0-23: the h12 branch lives in the contract, not in the engine.
    expect(spec).toMatchObject({ minimum: 1, maximum: 12 });
  });

  it("falls back to static bounds when the contract is unreadable", async () => {
    const { segmentSpec } = await importCore();

    expect(segmentSpec(mountSegment("month"))).toMatchObject({
      minimum: 1,
      maximum: 12,
      fillFromRight: false,
    });
    expect(segmentSpec(mountSegment("year", 4, "YYYY"))).toMatchObject({
      minimum: 1,
      maximum: 9999,
      fillFromRight: true,
    });
  });

  it("starts an empty year at the current year, other parts at their minimum", async () => {
    const { segmentSpec } = await importCore();

    expect(segmentSpec(mountSegment("year", 4, "YYYY"))?.emptyValue).toBe(
      new Date().getFullYear(),
    );
    expect(segmentSpec(mountSegment("day", 2, "DD"))?.emptyValue).toBe(1);
  });
});

describe("segment ARIA", () => {
  beforeEach(() => {
    segmentRules.mockReset();
    dayPeriodLabels.mockReset();
    segmentRules.mockReturnValue(null);
    dayPeriodLabels.mockReturnValue(null);
  });

  it("exposes each segment as a spinbutton with its bounds", async () => {
    const { setSegmentBuffer } = await importCore();
    const segment = mountSegment("month");

    setSegmentBuffer(segment, "07");

    expect(segment.getAttribute("role")).toBe("spinbutton");
    expect(segment.getAttribute("aria-valuemin")).toBe("1");
    expect(segment.getAttribute("aria-valuemax")).toBe("12");
    expect(segment.getAttribute("aria-valuenow")).toBe("7");
  });

  it("drops aria-valuenow while a segment is empty or half-typed", async () => {
    const { setSegmentBuffer } = await importCore();
    const segment = mountSegment("month");

    setSegmentBuffer(segment, "07");
    setSegmentBuffer(segment, "1");

    expect(segment.hasAttribute("aria-valuenow")).toBe(false);

    setSegmentBuffer(segment, "");
    expect(segment.hasAttribute("aria-valuenow")).toBe(false);
  });

  it("says an indeterminate segment out loud instead of falling back to zero", async () => {
    // Dropping aria-valuenow is not silence: a screen reader announces 0, so
    // an untouched field read every segment as "spinbutton, zero" while
    // showing YYYY.
    const { setSegmentBuffer } = await importCore();
    const segment = mountSegment("month");

    // bind() stamps every segment on upgrade, empty ones included.
    setSegmentBuffer(segment, "");
    expect(segment.getAttribute("aria-valuetext")).toBe("blank");

    setSegmentBuffer(segment, "1");
    expect(segment.getAttribute("aria-valuetext")).toBe("1");

    // Filled: the value is stated as text as well as as a number.
    setSegmentBuffer(segment, "07");
    expect(segment.getAttribute("aria-valuetext")).toBe("7");
    expect(segment.getAttribute("aria-valuenow")).toBe("7");

    setSegmentBuffer(segment, "");
    expect(segment.getAttribute("aria-valuetext")).toBe("blank");
  });

  it("shows the day period's label, keeping the buffer numeric", async () => {
    segmentRules.mockImplementation((name) =>
      name === "day_period" ? rules("day_period", 0, 1, "day_period") : null,
    );
    dayPeriodLabels.mockReturnValue({ am: "dop.", pm: "odp." });
    const { setSegmentBuffer, segmentBuffer } = await importCore();
    const segment = mountSegment("day_period", 2, "--");

    setSegmentBuffer(segment, "01");

    expect(segment.value).toBe("odp.");
    // The wire codec and arrow-stepping both read the numeric buffer.
    expect(segmentBuffer(segment)).toBe("01");
  });

  it("selects a day period by the contract's own label, not by a/p", async () => {
    segmentRules.mockImplementation((name) =>
      name === "day_period" ? rules("day_period", 0, 1, "day_period") : null,
    );
    // Django's cs locale: neither label starts with a or p.
    dayPeriodLabels.mockReturnValue({ am: "dop.", pm: "odp." });
    const { dayPeriodBufferForKey } = await importCore();

    expect(dayPeriodBufferForKey("d", 2)).toBe("00");
    expect(dayPeriodBufferForKey("o", 2)).toBe("01");
    expect(dayPeriodBufferForKey("a", 2)).toBe("");
  });

  it("states every segment's value as text so no reader recites a percentage", async () => {
    // A spinbutton with only aria-valuenow invites a position-in-range
    // reading: VoiceOver said "2026, 20.3 percent" for the year (2025/9998)
    // and "7, 54.5 percent" for the month (6/11). A date segment has no
    // meaningful position in its range.
    const { setSegmentBuffer } = await importCore();
    const year = mountSegment("year", 4, "YYYY");

    setSegmentBuffer(year, "2026");

    expect(year.getAttribute("aria-valuetext")).toBe("2026");
  });

  it("announces the day period as text, not as a number", async () => {
    segmentRules.mockImplementation((name) =>
      name === "day_period" ? rules("day_period", 0, 1, "day_period") : null,
    );
    dayPeriodLabels.mockReturnValue({ am: "dop.", pm: "odp." });
    const { setSegmentBuffer } = await importCore();
    const segment = mountSegment("day_period", 2, "--");

    setSegmentBuffer(segment, "01");

    expect(segment.getAttribute("aria-valuetext")).toBe("odp.");
  });
});

describe("field mousedown", () => {
  beforeEach(() => {
    segmentRules.mockReset();
    dayPeriodLabels.mockReset();
    segmentRules.mockReturnValue(null);
    dayPeriodLabels.mockReturnValue(null);
  });

  async function mountField(): Promise<HTMLElement> {
    const { bindSegmentField } = await importCore();
    document.body.innerHTML =
      '<div data-field><input data-date-part="month" data-date-side="value" ' +
      'maxlength="2"><label><input type="checkbox" id="qualifier">About</label></div>';
    const field = document.querySelector<HTMLElement>("[data-field]")!;
    bindSegmentField({
      picker: field,
      field,
      resolveHidden: () => null,
      onCommit: () => {},
    });
    return field;
  }

  it("leaves a control beside the segments its own focus", async () => {
    // A temporal field holds checkboxes inside the field, and stealing focus
    // from one bounced it between the box and the nearest segment.
    await mountField();
    const box = document.querySelector<HTMLInputElement>("#qualifier")!;

    const event = new MouseEvent("mousedown", { bubbles: true, cancelable: true });
    box.dispatchEvent(event);

    expect(event.defaultPrevented).toBe(false);
    expect(document.activeElement).not.toBe(
      document.querySelector("input[data-date-part]"),
    );
  });

  it("still sends blank space to the nearest segment", async () => {
    const field = await mountField();

    const event = new MouseEvent("mousedown", { bubbles: true, cancelable: true });
    field.dispatchEvent(event);

    expect(event.defaultPrevented).toBe(true);
    expect(document.activeElement).toBe(document.querySelector("input[data-date-part]"));
  });
});

describe("todayInDisplayZone", () => {
  beforeEach(() => {
    todayInPresentationZone.mockReset();
  });

  it("takes the day the contract states, at local midnight", async () => {
    todayInPresentationZone.mockReturnValue("2027-03-05");
    const { todayInDisplayZone } = await importCore();

    const today = todayInDisplayZone();
    expect([today.getFullYear(), today.getMonth(), today.getDate()]).toEqual([2027, 2, 5]);
    expect([today.getHours(), today.getMinutes(), today.getSeconds()]).toEqual([0, 0, 0]);
  });

  it("falls back to the browser's day when the contract cannot say", async () => {
    todayInPresentationZone.mockReturnValue(null);
    const { todayInDisplayZone, isoFromDate } = await importCore();

    const browserToday = new Date();
    expect(isoFromDate(todayInDisplayZone())).toBe(isoFromDate(browserToday));
    expect(todayInDisplayZone().getHours()).toBe(0);
  });
});
