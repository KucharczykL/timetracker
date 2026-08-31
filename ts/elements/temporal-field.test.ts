// @vitest-environment jsdom
import { beforeEach, describe, expect, it } from "vitest";
import "./temporal-field.js";

const PARTS = ["year", "month", "day"] as const;

function endpointMarkup(endpoint: string, openToggle = "", storedYear = ""): string {
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
        ${openToggle ? `<input type="checkbox" data-temporal-toggle="${openToggle}">` : ""}
      </div>
    </fieldset>`;
}

function mount(
  expanded = "false",
  storedEndYear = "",
  storedKind = "unknown",
): HTMLElement {
  const kindOption = (value: string, text: string) =>
    `<option value="${value}"${value === storedKind ? " selected" : ""}>${text}</option>`;
  document.body.innerHTML = `
    <temporal-field expanded="${expanded}">
      <div data-temporal-field="">
        <div data-temporal-native="">
          <select data-temporal-input="kind">
            ${kindOption("date", "Date")}
            ${kindOption("range", "Range")}
            ${kindOption("since", "Since")}
            ${kindOption("until", "Until")}
            ${kindOption("unknown", "Unknown")}
          </select>
        </div>
        ${endpointMarkup("start", "open_start")}
        <fieldset data-temporal-extra="" hidden>
          <legend>After the start date</legend>
          <input type="radio" name="end-shape" value="end_none"
                 data-temporal-toggle="end_none" disabled>
          <input type="radio" name="end-shape" value="end_date"
                 data-temporal-toggle="end_date" disabled>
          <input type="radio" name="end-shape" value="end_open"
                 data-temporal-toggle="end_open" disabled>
        </fieldset>
        <div data-temporal-end-group="">
          ${endpointMarkup("end", "", storedEndYear)}
        </div>
        <div hidden data-temporal-disclosure-row="">
          <button type="button" data-temporal-disclosure="" aria-expanded="false">
            <span data-temporal-disclosure-label="collapsed">I don't know the exact date</span>
            <span data-temporal-disclosure-label="expanded" hidden>I know the exact date</span>
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

function toggleDisclosure(host: HTMLElement): void {
  host.querySelector<HTMLButtonElement>("[data-temporal-disclosure]")!.click();
}

function label(host: HTMLElement, which: string): HTMLElement {
  return host.querySelector<HTMLElement>(
    `[data-temporal-disclosure-label="${which}"]`,
  )!;
}

/** Select one of the three end shapes, as a click would. */
function pick(host: HTMLElement, shape: string): void {
  const radio = toggle(host, shape);
  radio.checked = true;
  radio.dispatchEvent(new Event("change", { bubbles: true }));
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

    toggleDisclosure(host);

    host.querySelectorAll("[data-temporal-extra]").forEach((extra) => {
      expect(extra.hasAttribute("hidden")).toBe(false);
    });
    expect(label(host, "expanded").hasAttribute("hidden")).toBe(false);
    expect(label(host, "collapsed").hasAttribute("hidden")).toBe(true);
  });

  it("closes the extras again", () => {
    const host = mount();
    toggleDisclosure(host);

    toggleDisclosure(host);

    host.querySelectorAll("[data-temporal-extra]").forEach((extra) => {
      expect(extra.hasAttribute("hidden")).toBe(true);
    });
    expect(label(host, "collapsed").hasAttribute("hidden")).toBe(false);
  });

  it("offers no way to close while the extras hold the value", () => {
    const host = mount("true");

    check(host, "whole_decade_start");

    expect(
      host.querySelector("[data-temporal-disclosure-row]")!.hasAttribute("hidden"),
    ).toBe(true);

    check(host, "whole_decade_start", false);

    expect(
      host.querySelector("[data-temporal-disclosure-row]")!.hasAttribute("hidden"),
    ).toBe(false);
  });

  it("keeps an end date from being hidden away", () => {
    const host = mount("true");
    pick(host, "end_date");
    type(host, "end", "year", "1986");

    expect(
      host.querySelector("[data-temporal-disclosure-row]")!.hasAttribute("hidden"),
    ).toBe(true);
  });

  it("opens already expanded when the stored value needs it", () => {
    const host = mount("true");

    expect(label(host, "expanded").hasAttribute("hidden")).toBe(false);
    expect(
      toggle(host, "end_date").closest("[data-temporal-extra]")!.hasAttribute("hidden"),
    ).toBe(false);
  });

  it("hands the end choices over to whoever opened them", () => {
    const host = mount("true");

    ["end_none", "end_date", "end_open"].forEach((shape) => {
      expect(toggle(host, shape).disabled).toBe(false);
    });
  });

  it("keeps the end field away until somebody adds one", () => {
    const host = mount("true");

    expect(
      host.querySelector("[data-temporal-end-group]")!.hasAttribute("hidden"),
    ).toBe(true);

    pick(host, "end_date");

    expect(
      host.querySelector("[data-temporal-end-group]")!.hasAttribute("hidden"),
    ).toBe(false);
  });

  it("becomes a range once both ends say something", () => {
    const host = mount("true");
    pick(host, "end_date");

    type(host, "start", "year", "1984");
    type(host, "end", "year", "1986");

    expect(named(host, "kind").value).toBe("range");
    expect(named(host, "end_year").value).toBe("1986");
  });

  it("forgets an end nobody wants any more", () => {
    const host = mount("true");
    pick(host, "end_date");
    type(host, "start", "year", "1984");
    type(host, "end", "year", "1986");

    pick(host, "end_none");

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

  it("still going leaves the value a since", () => {
    const host = mount("true");
    pick(host, "end_date");
    type(host, "start", "year", "1984");
    type(host, "end", "year", "1986");

    pick(host, "end_open");

    expect(named(host, "kind").value).toBe("since");
    expect(named(host, "end_year").value).toBe("");
    expect(
      host.querySelector("[data-temporal-end-group]")!.hasAttribute("hidden"),
    ).toBe(true);
  });

  it("opens the start and calls it until", () => {
    const host = mount("true");
    pick(host, "end_date");
    type(host, "start", "year", "1984");
    type(host, "end", "year", "1986");

    check(host, "open_start");

    expect(named(host, "kind").value).toBe("until");
    expect(named(host, "start_year").value).toBe("");
  });

  it("brings the end along when the start opens", () => {
    const host = mount("true");

    check(host, "open_start");

    expect(toggle(host, "end_date").checked).toBe(true);
    expect(
      host.querySelector("[data-temporal-end-group]")!.hasAttribute("hidden"),
    ).toBe(false);
  });

  it("leaves no other end to choose while the start is open", () => {
    const host = mount("true");

    check(host, "open_start");

    ["end_none", "end_date", "end_open"].forEach((shape) => {
      expect(toggle(host, shape).disabled).toBe(true);
    });
  });

  it("gives the end choices back when the start closes", () => {
    const host = mount("true");
    check(host, "open_start");

    check(host, "open_start", false);

    expect(toggle(host, "end_none").disabled).toBe(false);
    expect(toggle(host, "end_date").checked).toBe(true);
    expect(named(host, "start_approximate").disabled).toBe(false);
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

  it("takes no qualifier on an open start", () => {
    const host = mount("true");
    named(host, "start_approximate").checked = true;

    check(host, "open_start");

    expect(named(host, "start_approximate").checked).toBe(false);
    expect(named(host, "start_approximate").disabled).toBe(true);
    expect(named(host, "start_uncertain").disabled).toBe(true);
    expect(toggle(host, "whole_decade_start").disabled).toBe(true);
    expect(
      host.querySelector('[data-temporal-segments="start"]')!.hasAttribute("hidden"),
    ).toBe(true);
  });

  it("drops the qualifier of an end nobody wants", () => {
    const host = mount("true");
    pick(host, "end_date");
    named(host, "end_uncertain").checked = true;

    pick(host, "end_none");

    expect(named(host, "end_uncertain").checked).toBe(false);
  });

  it("adopts an end the server already stored", () => {
    const host = mount("true", "1986", "range");

    expect(
      host.querySelector("[data-temporal-end-group]")!.hasAttribute("hidden"),
    ).toBe(false);
    expect(toggle(host, "end_date").checked).toBe(true);
  });

  it("keeps a stored since a since", () => {
    const host = mount("true", "", "since");

    expect(toggle(host, "end_open").checked).toBe(true);

    type(host, "start", "year", "1984");

    expect(named(host, "kind").value).toBe("since");
  });

  it("keeps a stored until an until", () => {
    const host = mount("true", "1986", "until");

    expect(toggle(host, "open_start").checked).toBe(true);
    expect(toggle(host, "end_date").checked).toBe(true);

    type(host, "end", "month", "06");

    expect(named(host, "kind").value).toBe("until");
  });
});
