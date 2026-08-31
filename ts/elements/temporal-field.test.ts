// @vitest-environment jsdom
import { beforeEach, describe, expect, it } from "vitest";
import "./temporal-field.js";

const PARTS = ["year", "month", "day"] as const;

function endpointMarkup(
  endpoint: string,
  openLabel: string,
  openToggle: string,
  storedYear = "",
): string {
  const cells = PARTS.map(
    (part, index) => `
      <span data-temporal-part="${part}">
        ${index > 0 ? '<span data-temporal-prefix="">-</span>' : ""}
        <input data-date-part="${part}" data-date-side="${endpoint}"
               maxlength="${part === "year" ? 4 : 2}"
               value="${part === "year" ? storedYear : ""}">
      </span>`,
  ).join("");
  return `
    <fieldset data-temporal-endpoint="${endpoint}">
      <legend data-temporal-extra="">${endpoint}</legend>
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
      <div data-temporal-extra="">
        <input type="checkbox" data-temporal-input="${endpoint}_approximate">
        <input type="checkbox" data-temporal-input="${endpoint}_uncertain">
      </div>
      <div data-temporal-extra="" hidden>
        <input type="checkbox" data-temporal-toggle="whole_decade_${endpoint}">
        <input type="checkbox" data-temporal-toggle="${openToggle}" aria-label="${openLabel}">
      </div>
    </fieldset>`;
}

function mount(expanded = "false", storedEndYear = ""): HTMLElement {
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
        <div data-temporal-end-group="">
          ${endpointMarkup("end", "Ongoing, no end date", "open_end", storedEndYear)}
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

function toggle(host: HTMLElement, name: string): HTMLInputElement {
  return host.querySelector<HTMLInputElement>(`[data-temporal-toggle="${name}"]`)!;
}

function check(host: HTMLElement, name: string, checked = true): void {
  const box = toggle(host, name);
  box.checked = checked;
  box.dispatchEvent(new Event("change", { bubbles: true }));
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

  it("reveals the extras when somebody says they do not know", () => {
    const host = mount();

    host.querySelector<HTMLButtonElement>("[data-temporal-disclosure]")!.click();

    host.querySelectorAll("[data-temporal-extra]").forEach((extra) => {
      expect(extra.hasAttribute("hidden")).toBe(false);
    });
    expect(
      host.querySelector("[data-temporal-disclosure-row]")!.hasAttribute("hidden"),
    ).toBe(true);
  });

  it("opens already expanded when the stored value needs it", () => {
    const host = mount("true");

    expect(
      host.querySelector("[data-temporal-disclosure-row]")!.hasAttribute("hidden"),
    ).toBe(true);
    expect(
      toggle(host, "add_end").closest("[data-temporal-extra]")!.hasAttribute("hidden"),
    ).toBe(false);
  });

  it("keeps the end field away until somebody adds one", () => {
    const host = mount("true");

    expect(
      host.querySelector("[data-temporal-end-group]")!.hasAttribute("hidden"),
    ).toBe(true);

    check(host, "add_end");

    expect(
      host.querySelector("[data-temporal-end-group]")!.hasAttribute("hidden"),
    ).toBe(false);
  });

  it("becomes a range once both ends say something", () => {
    const host = mount("true");
    check(host, "add_end");

    type(host, "start", "year", "1984");
    type(host, "end", "year", "1986");

    expect(named(host, "kind").value).toBe("range");
    expect(named(host, "end_year").value).toBe("1986");
  });

  it("forgets an end nobody wants any more", () => {
    const host = mount("true");
    check(host, "add_end");
    type(host, "start", "year", "1984");
    type(host, "end", "year", "1986");

    check(host, "add_end", false);

    expect(named(host, "end_year").value).toBe("");
    expect(named(host, "kind").value).toBe("date");
  });

  it("snaps the typed year down to the ten it belongs to", () => {
    const host = mount("true");
    type(host, "start", "year", "1982");

    check(host, "whole_decade_start");

    expect(segment(host, "start", "year").value).toBe("1980");
    expect(named(host, "start_decade").value).toBe("1980");
    expect(named(host, "start_year").value).toBe("");
  });

  it("shows one cell and the trailing letter", () => {
    const host = mount("true");
    type(host, "start", "year", "1982");

    check(host, "whole_decade_start");

    const cell = (part: string) =>
      host.querySelector(
        `[data-temporal-endpoint="start"] [data-temporal-part="${part}"]`,
      )!;
    expect(cell("month").hasAttribute("hidden")).toBe(true);
    expect(cell("day").hasAttribute("hidden")).toBe(true);
    expect(
      host
        .querySelector('[data-temporal-endpoint="start"] [data-temporal-decade-suffix]')!
        .hasAttribute("hidden"),
    ).toBe(false);
  });

  it("hides the separator the leading cell no longer needs", () => {
    const host = mount("true");
    type(host, "start", "year", "1982");

    check(host, "whole_decade_start");

    const prefixes = host.querySelectorAll(
      '[data-temporal-endpoint="start"] [data-temporal-part]:not([hidden]) [data-temporal-prefix]',
    );
    prefixes.forEach((prefix) => expect(prefix.hasAttribute("hidden")).toBe(true));
  });

  it("gives back the year somebody actually typed", () => {
    const host = mount("true");
    type(host, "start", "year", "1982");
    check(host, "whole_decade_start");

    check(host, "whole_decade_start", false);

    expect(segment(host, "start", "year").value).toBe("1982");
    expect(named(host, "start_year").value).toBe("1982");
    expect(named(host, "start_decade").value).toBe("");
  });

  it("keeps snapping a year typed while the box is checked", () => {
    const host = mount("true");
    check(host, "whole_decade_start");

    type(host, "start", "year", "1975");

    expect(named(host, "start_decade").value).toBe("1970");
  });

  it("states no decade until the year is whole", () => {
    const host = mount("true");
    check(host, "whole_decade_start");

    type(host, "start", "year", "19");

    expect(named(host, "start_decade").value).toBe("");
  });

  it("opens the end and calls it since", () => {
    const host = mount("true");
    check(host, "add_end");
    type(host, "start", "year", "1984");
    type(host, "end", "year", "1986");

    check(host, "open_end");

    expect(named(host, "kind").value).toBe("since");
    expect(named(host, "end_year").value).toBe("");
  });

  it("opens the start and calls it until", () => {
    const host = mount("true");
    check(host, "add_end");
    type(host, "start", "year", "1984");
    type(host, "end", "year", "1986");

    check(host, "open_start");

    expect(named(host, "kind").value).toBe("until");
    expect(named(host, "start_year").value).toBe("");
  });

  it("brings the end along when the start opens", () => {
    const host = mount("true");

    check(host, "open_start");

    expect(toggle(host, "add_end").checked).toBe(true);
    expect(
      host.querySelector("[data-temporal-end-group]")!.hasAttribute("hidden"),
    ).toBe(false);
  });

  it("refuses to open both ends at once", () => {
    const host = mount("true");
    check(host, "add_end");

    check(host, "open_end");
    check(host, "open_start");

    expect(toggle(host, "open_end").checked).toBe(false);
  });

  it("says the precision it arrived at", () => {
    const host = mount("true");
    const region = host.querySelector("[data-temporal-announcement]")!;

    type(host, "start", "year", "1984");
    expect(region.textContent).toBe("Year precision");

    type(host, "start", "month", "06");
    expect(region.textContent).toBe("Month precision");

    check(host, "whole_decade_start");
    expect(region.textContent).toBe("Decade precision");
  });

  it("says nothing while nothing changed", () => {
    const host = mount("true");
    const region = host.querySelector("[data-temporal-announcement]")!;

    expect(region.textContent).toBe("");
  });

  it("takes no qualifier on an end it has opened", () => {
    const host = mount("true");
    check(host, "add_end");
    named(host, "end_approximate").checked = true;

    check(host, "open_end");

    expect(named(host, "end_approximate").checked).toBe(false);
    expect(named(host, "end_approximate").disabled).toBe(true);
    expect(named(host, "end_uncertain").disabled).toBe(true);
    expect(toggle(host, "whole_decade_end").disabled).toBe(true);
  });

  it("gives the qualifier back when the end closes again", () => {
    const host = mount("true");
    check(host, "add_end");
    check(host, "open_end");

    check(host, "open_end", false);

    expect(named(host, "end_approximate").disabled).toBe(false);
    expect(
      host.querySelector('[data-temporal-segments="end"]')!.hasAttribute("hidden"),
    ).toBe(false);
  });

  it("drops the qualifier of an end nobody wants", () => {
    const host = mount("true");
    check(host, "add_end");
    named(host, "end_uncertain").checked = true;

    check(host, "add_end", false);

    expect(named(host, "end_uncertain").checked).toBe(false);
  });

  it("closes an open end when the end itself goes", () => {
    const host = mount("true");
    check(host, "open_start");

    check(host, "add_end", false);

    expect(toggle(host, "open_start").checked).toBe(false);
    expect(named(host, "start_approximate").disabled).toBe(false);
    expect(named(host, "kind").value).toBe("unknown");
  });

  it("adopts an end the server already stored", () => {
    const host = mount("true", "1986");

    expect(
      host.querySelector("[data-temporal-end-group]")!.hasAttribute("hidden"),
    ).toBe(false);
    expect(toggle(host, "add_end").checked).toBe(true);
  });
});
