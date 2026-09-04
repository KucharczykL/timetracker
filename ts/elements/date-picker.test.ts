// @vitest-environment jsdom
import { describe, it, expect, beforeEach, vi } from "vitest";
import { DATE_PICKER_CHANGE_EVENT, type DatePickerChangeDetail } from "./date-picker.js";

const formatCalendarMonthYear = vi.hoisted(() => vi.fn(() => "Contract month"));
const calendarWeekdayLabels = vi.hoisted(() =>
  vi.fn(() => ["M1", "T2", "W3", "T4", "F5", "S6", "S7"]),
);

// segmentRules/dayPeriodLabels return null here, so the engine exercises its
// contract-less fallback path — these pages carry no presentation contract.
// The day is fixed, and must not be the runner's, to pin the zone the empty
// calendar opens in (#949).
vi.mock("../date-time-presentation.js", () => ({
  formatCalendarMonthYear,
  calendarWeekdayLabels,
  segmentRules: () => null,
  dayPeriodLabels: () => null,
  todayInPresentationZone: () => "2027-03-05",
}));

function segment(part: string, width: number, placeholder: string): string {
  return (
    `<input data-date-part="${part}" data-date-side="value" ` +
    `maxlength="${width}" placeholder="${placeholder}" />`
  );
}

// A minimal stand-in for the real <drop-down> element (its own behavior is
// covered by menu-behavior.test.ts): open()/close() just toggle the `hidden`
// attribute attachMenu itself would toggle, and close() fires the
// dropdown:hide bubble date-picker.ts listens for to resync aria-expanded.
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

function mount(): HTMLElement {
  document.body.replaceChildren();
  const dropdown = document.createElement("drop-down");
  const picker = document.createElement("date-picker");
  picker.innerHTML = `
    <input type="hidden" data-date-picker-hidden />
    <div data-date-picker-field>
      ${segment("year", 4, "YYYY")}${segment("month", 2, "MM")}${segment("day", 2, "DD")}
      <button data-date-picker-calendar-toggle></button>
    </div>
    <div data-date-range-calendar data-menu hidden>
      <button data-date-range-prev></button>
      <span data-date-range-month-label></span>
      <button data-date-range-next></button>
      <div data-date-range-grid></div>
      <button data-date-range-clear></button>
    </div>`;
  dropdown.appendChild(picker);
  document.body.appendChild(dropdown); // connectedCallback → initPicker
  return picker;
}

function typeDigits(input: HTMLInputElement, digits: string): void {
  input.focus();
  for (const digit of digits) {
    input.dispatchEvent(new KeyboardEvent("keydown", { key: digit, bubbles: true }));
  }
}

function pasteInto(input: HTMLInputElement, text: string): void {
  const event = new Event("paste", { bubbles: true, cancelable: true });
  Object.defineProperty(event, "clipboardData", { value: { getData: () => text } });
  input.dispatchEvent(event);
}

const hidden = (picker: HTMLElement) =>
  picker.querySelector<HTMLInputElement>("[data-date-picker-hidden]")!;

describe("date-picker segment typing", () => {
  beforeEach(() => document.body.replaceChildren());

  it("fills segments left to right and writes the hidden ISO value", () => {
    const picker = mount();
    const [year, month, day] = picker.querySelectorAll<HTMLInputElement>(
      "input[data-date-part]",
    );
    typeDigits(year, "2026");
    typeDigits(month, "06");
    typeDigits(day, "15");
    expect(hidden(picker).value).toBe("2026-06-15");
  });

  it("dispatches date-picker:change once the value completes", () => {
    const picker = mount();
    const details: DatePickerChangeDetail[] = [];
    picker.addEventListener(DATE_PICKER_CHANGE_EVENT, (event) => {
      details.push((event as CustomEvent<DatePickerChangeDetail>).detail);
    });
    const [year, month, day] = picker.querySelectorAll<HTMLInputElement>(
      "input[data-date-part]",
    );
    typeDigits(year, "2026");
    typeDigits(month, "06");
    typeDigits(day, "15");
    expect(details.at(-1)).toEqual({ value: "2026-06-15" });
  });

  it("does not fire while incomplete", () => {
    const picker = mount();
    let fired = 0;
    picker.addEventListener(DATE_PICKER_CHANGE_EVENT, () => (fired += 1));
    const year = picker.querySelector<HTMLInputElement>('input[data-date-part="year"]')!;
    typeDigits(year, "2026");
    expect(fired).toBe(0);
    expect(hidden(picker).value).toBe("");
  });

  it("Backspace clears the active segment and empties the hidden value", () => {
    const picker = mount();
    const [year, month, day] = picker.querySelectorAll<HTMLInputElement>(
      "input[data-date-part]",
    );
    typeDigits(year, "2026");
    typeDigits(month, "06");
    typeDigits(day, "15");
    expect(hidden(picker).value).toBe("2026-06-15");
    day.dispatchEvent(new KeyboardEvent("keydown", { key: "Backspace", bubbles: true }));
    expect(hidden(picker).value).toBe("");
  });
});

describe("date-picker paste parsing (#485)", () => {
  beforeEach(() => document.body.replaceChildren());

  it("parses a pasted ISO date regardless of separator", () => {
    const picker = mount();
    const year = picker.querySelector<HTMLInputElement>('input[data-date-part="year"]')!;
    pasteInto(year, "2026-06-15");
    expect(hidden(picker).value).toBe("2026-06-15");
    pasteInto(year, "2026/06/16");
    expect(hidden(picker).value).toBe("2026-06-16");
  });

  it("parses a pasted date in the field's own segment order when not ISO-shaped", () => {
    const picker = mount(); // year, month, day order in this mount
    const year = picker.querySelector<HTMLInputElement>('input[data-date-part="year"]')!;
    pasteInto(year, "2026/06/15");
    expect(hidden(picker).value).toBe("2026-06-15");
  });

  it("rejects a pasted 2-digit year", () => {
    const picker = mount();
    const year = picker.querySelector<HTMLInputElement>('input[data-date-part="year"]')!;
    pasteInto(year, "26/06/15");
    expect(hidden(picker).value).toBe("");
  });

  it("swallows garbage paste text", () => {
    const picker = mount();
    const year = picker.querySelector<HTMLInputElement>('input[data-date-part="year"]')!;
    pasteInto(year, "not a date");
    expect(hidden(picker).value).toBe("");
  });
});

describe("date-picker calendar", () => {
  beforeEach(() => {
    document.body.replaceChildren();
    formatCalendarMonthYear.mockClear();
    calendarWeekdayLabels.mockClear();
  });

  it("opens on toggle click and renders a 42-cell grid with no presets", () => {
    const picker = mount();
    picker
      .querySelector<HTMLElement>("[data-date-picker-calendar-toggle]")!
      .dispatchEvent(new MouseEvent("click", { bubbles: true }));
    const grid = picker.querySelector<HTMLElement>("[data-date-range-grid]")!;
    expect(grid.querySelectorAll("button[data-date]").length).toBe(42);
    expect(picker.querySelector("[data-date-range-preset]")).toBeNull();
    expect(
      picker.querySelector("[data-date-range-calendar]")!.hasAttribute("hidden"),
    ).toBe(false);
  });

  it("opens an empty field on the display zone's day (#949)", () => {
    const picker = mount();
    picker
      .querySelector<HTMLElement>("[data-date-picker-calendar-toggle]")!
      .dispatchEvent(new MouseEvent("click", { bubbles: true }));

    expect(formatCalendarMonthYear).toHaveBeenCalledWith(2027, 2);
    expect(
      picker.querySelector('[data-date="2027-03-05"]')!.getAttribute("aria-current"),
    ).toBe("date");
  });

  it("picking a day commits the value and closes the popup immediately", () => {
    const picker = mount();
    picker
      .querySelector<HTMLElement>("[data-date-picker-calendar-toggle]")!
      .dispatchEvent(new MouseEvent("click", { bubbles: true }));
    const dayButton = picker.querySelector<HTMLElement>("button[data-date]")!;
    dayButton.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    expect(hidden(picker).value).toBe(dayButton.getAttribute("data-date"));
    expect(
      picker.querySelector("[data-date-range-calendar]")!.hasAttribute("hidden"),
    ).toBe(true);
  });

  it("Clear empties the value and keeps the popup open", () => {
    const picker = mount();
    picker
      .querySelector<HTMLElement>("[data-date-picker-calendar-toggle]")!
      .dispatchEvent(new MouseEvent("click", { bubbles: true }));
    const dayButton = picker.querySelector<HTMLElement>("button[data-date]")!;
    dayButton.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    expect(hidden(picker).value).not.toBe("");

    picker
      .querySelector<HTMLElement>("[data-date-picker-calendar-toggle]")!
      .dispatchEvent(new MouseEvent("click", { bubbles: true }));
    picker
      .querySelector<HTMLElement>("[data-date-range-clear]")!
      .dispatchEvent(new MouseEvent("click", { bubbles: true }));
    expect(hidden(picker).value).toBe("");
    expect(
      picker.querySelector("[data-date-range-calendar]")!.hasAttribute("hidden"),
    ).toBe(false);
  });
});
