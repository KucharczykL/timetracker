// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Segment } from "../date-time-presentation.js";

const segmentRules = vi.hoisted(() => vi.fn<(name: string) => Segment | null>());
const dayPeriodLabels = vi.hoisted(() =>
  vi.fn<() => { am: string; pm: string } | null>(),
);

vi.mock("../date-time-presentation.js", () => ({ segmentRules, dayPeriodLabels }));

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
