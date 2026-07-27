// @vitest-environment jsdom
import { describe, it, expect, beforeEach, vi } from "vitest";

const formatCalendarMonthYear = vi.hoisted(() => vi.fn(() => "Contract month"));
const calendarWeekdayLabels = vi.hoisted(() =>
  vi.fn(() => ["M1", "T2", "W3", "T4", "F5", "S6", "S7"]),
);
const nowInPresentationZone = vi.hoisted(() => vi.fn<() => string | null>());
const segmentRules = vi.hoisted(() => {
  const rules: Record<string, unknown> = {
    year: { kind: "numeric", run: "date", minimumValue: 1, maximumValue: 9999 },
    month: { kind: "numeric", run: "date", minimumValue: 1, maximumValue: 12 },
    day: { kind: "numeric", run: "date", minimumValue: 1, maximumValue: 31 },
    hour: { kind: "numeric", run: "time", minimumValue: 0, maximumValue: 23 },
    minute: { kind: "numeric", run: "time", minimumValue: 0, maximumValue: 59 },
  };
  return vi.fn((name: string) => rules[name] ?? null);
});

vi.mock("../date-time-presentation.js", () => ({
  formatCalendarMonthYear,
  calendarWeekdayLabels,
  segmentRules,
  dayPeriodLabels: () => null,
  presentationClock: () => ({ timeZone: "Europe/Prague", hourCycle: "h23" }),
  nowInPresentationZone,
}));

import "./date-time-field.js";

// The server renders each segment's value alongside the hidden one; the engine
// adopts them as typed buffers on upgrade. The fixture has to do the same, or
// it is not testing the markup the widget actually ships with.
function renderedSegments(value: string): Record<string, string> {
  const match = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})/.exec(value);
  if (!match) return {};
  const [, year, month, day, hour, minute] = match;
  return { year, month, day, hour, minute };
}

function segment(
  part: string,
  width: number,
  placeholder: string,
  value = "",
): string {
  return (
    `<input data-date-part="${part}" data-date-side="value" value="${value}" ` +
    `maxlength="${width}" placeholder="${placeholder}" />`
  );
}

// A minimal stand-in for the real <drop-down> element (its own behavior is
// covered by menu-behavior.test.ts).
class FakeDropDown extends HTMLElement {
  open(): void {
    this.querySelector("[data-menu]")?.removeAttribute("hidden");
  }
  close(): void {
    const menu = this.querySelector("[data-menu]");
    if (!menu || menu.hasAttribute("hidden")) return;
    menu.setAttribute("hidden", "");
    this.dispatchEvent(new CustomEvent("dropdown:hide", { bubbles: true }));
  }
}
if (!customElements.get("drop-down")) customElements.define("drop-down", FakeDropDown);

function markup(fieldName: string, copyTo: string, value = ""): string {
  const shown = renderedSegments(value);
  return `
    <drop-down>
      <date-time-field field-name="${fieldName}">
        <div data-date-picker-field>
          <input type="hidden" name="${fieldName}" value="${value}" data-date-time-hidden />
          ${segment("year", 4, "YYYY", shown.year)}${segment("month", 2, "MM", shown.month)}${segment("day", 2, "DD", shown.day)}
          ${segment("hour", 2, "HH", shown.hour)}${segment("minute", 2, "mm", shown.minute)}
          <button data-date-picker-calendar-toggle></button>
          <button data-date-time-copy="${copyTo}"></button>
        </div>
        <div data-date-range-calendar data-menu hidden>
          <button data-date-range-prev></button>
          <span data-date-range-month-label></span>
          <button data-date-range-next></button>
          <div data-date-range-grid></div>
          <button data-date-range-now></button>
          <button data-date-range-clear></button>
        </div>
      </date-time-field>
    </drop-down>`;
}

function mount(value = ""): { start: HTMLElement; end: HTMLElement } {
  document.body.replaceChildren();
  document.body.innerHTML =
    markup("timestamp_start", "timestamp_end", value) +
    markup("timestamp_end", "timestamp_start");
  const [start, end] = Array.from(
    document.querySelectorAll<HTMLElement>("date-time-field"),
  );
  return { start, end };
}

const hidden = (field: HTMLElement) =>
  field.querySelector<HTMLInputElement>("[data-date-time-hidden]")!;

const partInput = (field: HTMLElement, part: string) =>
  field.querySelector<HTMLInputElement>(`input[data-date-part="${part}"]`)!;

function typeInto(field: HTMLElement, part: string, digits: string): void {
  const input = partInput(field, part);
  input.focus();
  for (const digit of digits) {
    input.dispatchEvent(new KeyboardEvent("keydown", { key: digit, bubbles: true }));
  }
}

function fillWholeField(field: HTMLElement): void {
  typeInto(field, "year", "2026");
  typeInto(field, "month", "07");
  typeInto(field, "day", "27");
  typeInto(field, "hour", "14");
  typeInto(field, "minute", "30");
}

function pasteInto(field: HTMLElement, part: string, text: string): void {
  const event = new Event("paste", { bubbles: true, cancelable: true });
  Object.defineProperty(event, "clipboardData", { value: { getData: () => text } });
  partInput(field, part).dispatchEvent(event);
}

function openCalendar(field: HTMLElement): void {
  field.querySelector<HTMLElement>("[data-date-picker-calendar-toggle]")!.click();
}

function pickDay(field: HTMLElement, isoString: string): void {
  field.querySelector<HTMLElement>(`button[data-date="${isoString}"]`)!.click();
}

beforeEach(() => {
  nowInPresentationZone.mockReturnValue("2026-07-27T14:30");
});

describe("date-time-field", () => {
  it("commits an offset-qualified wall clock once every segment is typed", () => {
    const { start } = mount();

    fillWholeField(start);

    expect(hidden(start).value).toBe("2026-07-27T14:30:00.000000+02:00");
  });

  it("commits nothing while the time half is still empty", () => {
    const { start } = mount();

    typeInto(start, "year", "2026");
    typeInto(start, "month", "07");
    typeInto(start, "day", "27");

    expect(hidden(start).value).toBe("");
  });

  it("keeps the typed time when a calendar day is picked", () => {
    const { start } = mount();
    fillWholeField(start);

    openCalendar(start);
    pickDay(start, "2026-07-04");

    expect(hidden(start).value).toBe("2026-07-04T14:30:00.000000+02:00");
    expect(partInput(start, "hour").value).toBe("14");
  });

  it("picks midnight when the calendar is the first thing touched", () => {
    const { start } = mount();

    openCalendar(start);
    pickDay(start, "2026-07-04");

    expect(hidden(start).value).toBe("2026-07-04T00:00:00.000000+02:00");
  });

  it("sets the whole value from the account's clock, not the browser's", () => {
    const { start } = mount();

    openCalendar(start);
    start.querySelector<HTMLElement>("[data-date-range-now]")!.click();

    expect(nowInPresentationZone).toHaveBeenCalled();
    expect(hidden(start).value).toBe("2026-07-27T14:30:00.000000+02:00");
    expect(partInput(start, "day").value).toBe("27");
  });

  it("clears every segment and the committed value", () => {
    const { start } = mount();
    fillWholeField(start);

    openCalendar(start);
    start.querySelector<HTMLElement>("[data-date-range-clear]")!.click();

    expect(hidden(start).value).toBe("");
    expect(partInput(start, "minute").value).toBe("");
  });

  it("copies its value into the field it names", () => {
    const { start, end } = mount();
    fillWholeField(start);

    start.querySelector<HTMLElement>("[data-date-time-copy]")!.click();

    expect(hidden(end).value).toBe(hidden(start).value);
    expect(partInput(end, "hour").value).toBe("14");
  });

  it("pastes a full datetime into both halves", () => {
    const { start } = mount();

    pasteInto(start, "year", "2026-07-27 14:30");

    expect(hidden(start).value).toBe("2026-07-27T14:30:00.000000+02:00");
  });

  it("pastes a bare date without disturbing the typed time", () => {
    const { start } = mount();
    fillWholeField(start);

    pasteInto(start, "year", "2026-12-24");

    expect(hidden(start).value).toBe("2026-12-24T14:30:00.000000+01:00");
  });

  it("pastes a bare time without disturbing the typed date", () => {
    const { start } = mount();
    fillWholeField(start);

    pasteInto(start, "hour", "09:05");

    expect(hidden(start).value).toBe("2026-07-27T09:05:00.000000+02:00");
  });

  it("ignores a paste it cannot read", () => {
    const { start } = mount();
    fillWholeField(start);

    pasteInto(start, "year", "sometime next week");

    expect(hidden(start).value).toBe("2026-07-27T14:30:00.000000+02:00");
  });

  it("carries the copied value's own seconds, not the target's", () => {
    // The residual belongs to the value: an edit-form timestamp copied into an
    // empty field must arrive whole.
    const { start, end } = mount("2026-07-27T14:30:41.123456+02:00");

    start.querySelector<HTMLElement>("[data-date-time-copy]")!.click();

    expect(hidden(end).value).toBe("2026-07-27T14:30:41.123456+02:00");
  });

  it("drops the seconds when Now replaces the value", () => {
    // "Now" names no seconds, so keeping the old ones would invent precision.
    const { start } = mount("2026-07-27T14:30:41.123456+02:00");

    openCalendar(start);
    start.querySelector<HTMLElement>("[data-date-range-now]")!.click();

    expect(hidden(start).value).toBe("2026-07-27T14:30:00.000000+02:00");
  });

  it("re-derives its segments from the value it was rendered with", () => {
    const { start } = mount("2026-07-27T14:30:41.123456+02:00");

    expect(partInput(start, "hour").value).toBe("14");
    // The sub-minute residual has no segment, but must survive an edit:
    // duration_calculated is a generated column over both timestamps.
    typeInto(start, "minute", "45");
    expect(hidden(start).value).toBe("2026-07-27T14:45:41.123456+02:00");
  });
});
