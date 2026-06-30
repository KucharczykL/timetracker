// @vitest-environment jsdom
import { describe, it, expect, beforeEach } from "vitest";
import { DATE_RANGE_CHANGE_EVENT, type DateRangeChangeDetail } from "./date-range-picker.js";

// Minimal-complete markup mirroring DateRangeField + DateRangeCalendar — only the
// data hooks the element wires. One "min" side of day/month/year segments plus the
// calendar scaffold createCalendarState dereferences (all queried non-null).
function segment(part: string, side: string, width: number, placeholder: string): string {
  return (
    `<input data-date-part="${part}" data-date-side="${side}" ` +
    `maxlength="${width}" placeholder="${placeholder}" />`
  );
}

function calendarScaffold(): string {
  return `
    <button data-date-range-calendar-toggle></button>
    <div data-date-range-calendar class="hidden">
      <button data-date-range-prev></button>
      <span data-date-range-month-label></span>
      <button data-date-range-next></button>
      <div data-date-range-grid></div>
      <button data-date-range-cancel></button>
      <button data-date-range-clear></button>
      <button data-date-range-select></button>
    </div>`;
}

function mount(): HTMLElement {
  document.body.replaceChildren();
  const picker = document.createElement("date-range-picker");
  picker.innerHTML = `
    <input type="hidden" data-date-range-hidden="min" />
    <input type="hidden" data-date-range-hidden="max" />
    <div data-date-range-field>
      ${segment("day", "min", 2, "DD")}${segment("month", "min", 2, "MM")}${segment("year", "min", 4, "YYYY")}
    </div>
    ${calendarScaffold()}`;
  document.body.appendChild(picker); // connectedCallback → initPicker
  return picker;
}

function typeDigits(input: HTMLInputElement, digits: string): void {
  input.focus();
  for (const digit of digits) {
    input.dispatchEvent(new KeyboardEvent("keydown", { key: digit, bubbles: true }));
  }
}

describe("date-range-picker change event (#192)", () => {
  beforeEach(() => document.body.replaceChildren());

  it("fires date-range:change with both bounds once a side completes", () => {
    const picker = mount();
    const details: DateRangeChangeDetail[] = [];
    picker.addEventListener(DATE_RANGE_CHANGE_EVENT, (event) => {
      details.push((event as CustomEvent<DateRangeChangeDetail>).detail);
    });

    const field = picker.querySelector<HTMLElement>("[data-date-range-field]")!;
    const [day, month, year] = field.querySelectorAll<HTMLInputElement>("input[data-date-part]");
    typeDigits(day, "15");
    typeDigits(month, "06");
    typeDigits(year, "2026");

    // The completing keystroke (last year digit) is when the ISO becomes valid.
    const last = details.at(-1);
    expect(last).toEqual({ min: "2026-06-15", max: "" });
    expect(picker.querySelector<HTMLInputElement>('[data-date-range-hidden="min"]')!.value).toBe(
      "2026-06-15",
    );
  });

  it("does not fire while a side is still incomplete", () => {
    const picker = mount();
    let fired = 0;
    picker.addEventListener(DATE_RANGE_CHANGE_EVENT, () => (fired += 1));

    const day = picker.querySelector<HTMLInputElement>('input[data-date-part="day"]')!;
    typeDigits(day, "15"); // day only — hidden stays "", no committed change

    expect(fired).toBe(0);
  });
});
