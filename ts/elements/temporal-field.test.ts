// @vitest-environment jsdom
import { beforeEach, describe, expect, it } from "vitest";
import "./temporal-field.js";

const PARTS = ["year", "month", "day"] as const;

function endpointMarkup(
  endpoint: string,
  openLabel: string,
  openToggle: string,
): string {
  const cells = PARTS.map(
    (part, index) => `
      <span data-temporal-part="${part}">
        ${index > 0 ? '<span data-temporal-prefix="">-</span>' : ""}
        <input data-date-part="${part}" data-date-side="${endpoint}"
               maxlength="${part === "year" ? 4 : 2}" value="">
      </span>`,
  ).join("");
  return `
    <fieldset data-temporal-endpoint="${endpoint}">
      <legend data-temporal-extra="" hidden>${endpoint}</legend>
      <div data-temporal-native="">
        <input data-temporal-input="${endpoint}_year" value="">
        <input data-temporal-input="${endpoint}_month" value="">
        <input data-temporal-input="${endpoint}_day" value="">
        <input data-temporal-input="${endpoint}_decade" value="">
      </div>
      <div data-temporal-segments="${endpoint}" hidden>
        <span data-date-field-side="${endpoint}">
          <input type="hidden" data-temporal-scratch="${endpoint}">
          ${cells}
          <span data-temporal-decade-suffix="" hidden>s</span>
        </span>
      </div>
      <div data-temporal-extra="" hidden>
        <input type="checkbox" data-temporal-input="${endpoint}_approximate">
        <input type="checkbox" data-temporal-input="${endpoint}_uncertain">
        <input type="checkbox" data-temporal-toggle="whole_decade_${endpoint}">
        <input type="checkbox" data-temporal-toggle="${openToggle}" aria-label="${openLabel}">
      </div>
    </fieldset>`;
}

function mount(expanded = "false"): HTMLElement {
  document.body.innerHTML = `
    <temporal-field expanded="${expanded}">
      <div data-temporal-field="">
        <div data-temporal-native="">
          <select data-temporal-input="kind">
            <option value="date">Date</option>
            <option value="range">Range</option>
            <option value="since">Since</option>
            <option value="until">Until</option>
            <option value="unknown" selected>Unknown</option>
          </select>
        </div>
        ${endpointMarkup("start", "No known start", "open_start")}
        <div data-temporal-extra="" hidden>
          <input type="checkbox" data-temporal-toggle="add_end">
        </div>
        <div data-temporal-end-group="" hidden>
          ${endpointMarkup("end", "Ongoing, no end date", "open_end")}
        </div>
        <div hidden data-temporal-disclosure-row="">
          <button type="button" data-temporal-disclosure="" aria-expanded="false">
            I don't know the exact date
          </button>
        </div>
        <p data-temporal-announcement="" role="status" aria-live="polite"></p>
      </div>
    </temporal-field>`;
  return document.querySelector("temporal-field")!;
}

function segment(
  host: HTMLElement,
  endpoint: string,
  part: string,
): HTMLInputElement {
  return host.querySelector<HTMLInputElement>(
    `input[data-date-part="${part}"][data-date-side="${endpoint}"]`,
  )!;
}

function type(
  host: HTMLElement,
  endpoint: string,
  part: string,
  digits: string,
): void {
  const target = segment(host, endpoint, part);
  target.focus();
  for (const digit of digits) {
    target.dispatchEvent(new KeyboardEvent("keydown", { key: digit, bubbles: true }));
    target.dispatchEvent(new KeyboardEvent("keyup", { key: digit, bubbles: true }));
  }
}

function named(host: HTMLElement, key: string): HTMLInputElement {
  return host.querySelector<HTMLInputElement>(`[data-temporal-input="${key}"]`)!;
}

describe("temporal-field", () => {
  beforeEach(() => {
    document.body.innerHTML = "";
  });

  it("swaps the number inputs for the segments", () => {
    const host = mount();

    expect(
      host.querySelector('[data-temporal-segments="start"]')!.hasAttribute("hidden"),
    ).toBe(false);
    host.querySelectorAll("[data-temporal-native]").forEach((wrapper) => {
      expect(wrapper.hasAttribute("hidden")).toBe(true);
    });
  });

  it("offers the disclosure once it is the only way to say more", () => {
    const host = mount();

    expect(
      host.querySelector("[data-temporal-disclosure-row]")!.hasAttribute("hidden"),
    ).toBe(false);
  });

  it("keeps the extras closed until somebody asks", () => {
    const host = mount();

    host.querySelectorAll("[data-temporal-extra]").forEach((extra) => {
      expect(extra.hasAttribute("hidden")).toBe(true);
    });
  });

  it("writes a typed year into the input the server reads", () => {
    const host = mount();

    type(host, "start", "year", "1984");

    expect(named(host, "start_year").value).toBe("1984");
    expect(named(host, "kind").value).toBe("date");
  });

  it("writes a whole typed day", () => {
    const host = mount();

    type(host, "start", "year", "1984");
    type(host, "start", "month", "06");
    type(host, "start", "day", "22");

    expect(named(host, "start_month").value).toBe("06");
    expect(named(host, "start_day").value).toBe("22");
  });

  it("clears a part no coarser part can carry", () => {
    const host = mount();

    type(host, "start", "year", "1984");
    type(host, "start", "day", "22");

    expect(segment(host, "start", "day").value).toBe("");
    expect(named(host, "start_day").value).toBe("");
  });

  it("says unknown while nothing is filled", () => {
    const host = mount();

    expect(named(host, "kind").value).toBe("unknown");
  });
});
