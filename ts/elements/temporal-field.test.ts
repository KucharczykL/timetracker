// @vitest-environment jsdom
import { beforeEach, describe, expect, it } from "vitest";
// Bare, so the element still registers if the named uses below go.
import "./temporal-field.js";
import {
  TEMPORAL_FIELD_CHANGE_EVENT,
  adoptDraft,
  copyTemporalDraft,
  readDraft,
} from "./temporal-field.js";

const PARTS = ["year", "month", "day"] as const;
type PartOrder = readonly string[];
/** The three profile orders. */
const ORDERS: PartOrder[] = [
  ["year", "month", "day"],
  ["day", "month", "year"],
  ["month", "day", "year"],
];

type Draft = Record<string, string>;

/** The thirteen posted inputs, empty. */
const EMPTY_DRAFT: Draft = {
  kind: "unknown",
  start_year: "",
  start_month: "",
  start_day: "",
  start_decade: "",
  start_approximate: "",
  start_uncertain: "",
  end_year: "",
  end_month: "",
  end_day: "",
  end_decade: "",
  end_approximate: "",
  end_uncertain: "",
};

/** Digits right-aligned in the segment's width. */
function padded(text: string, width: number): string {
  return /^\d+$/.test(text) ? text.padStart(width, "0") : "";
}

/** One endpoint as the server renders it. */
function endpointMarkup(
  endpoint: string,
  openToggle: string,
  draft: Draft,
  order: PartOrder,
): string {
  const part = (name: string) => draft[`${endpoint}_${name}`] ?? "";
  const whole = part("decade") !== "";
  const buffers: Record<string, string> = {
    year: padded(whole ? part("decade") : part("year"), 4),
    month: whole ? "" : padded(part("month"), 2),
    day: whole ? "" : padded(part("day"), 2),
  };
  const shown = order.filter((name) => !whole || name === "year");
  const cells = order
    .map((name, index) => {
      const prefix =
        index > 0
          ? `<span data-temporal-prefix=""${name === shown[0] ? " hidden" : ""}>-</span>`
          : "";
      return `
      <span data-temporal-part="${name}"${shown.includes(name) ? "" : " hidden"}>
        ${prefix}
        <input data-date-part="${name}" data-date-side="${endpoint}"
               maxlength="${name === "year" ? 4 : 2}"
               placeholder="${name === "year" ? "YYYY" : name === "month" ? "MM" : "DD"}"
               value="${buffers[name]}">
      </span>`;
    })
    .join("");
  const box = (key: string) =>
    `<input type="checkbox" data-temporal-input="${endpoint}_${key}"${
      part(key) ? " checked" : ""
    }>`;
  return `
    <fieldset data-temporal-endpoint="${endpoint}">
      <legend data-temporal-extra="">${endpoint}</legend>
      <div data-temporal-native="">
        <input data-temporal-input="${endpoint}_year" value="${part("year")}">
        <input data-temporal-input="${endpoint}_month" value="${part("month")}">
        <input data-temporal-input="${endpoint}_day" value="${part("day")}">
        <input data-temporal-input="${endpoint}_decade" value="${part("decade")}">
      </div>
      <div data-temporal-segments="${endpoint}" hidden>
        <span data-date-field-side="${endpoint}">
          <input type="hidden" data-temporal-scratch="${endpoint}">
          ${cells}
          <span data-temporal-decade-suffix=""${whole ? "" : " hidden"}>s</span>
        </span>
      </div>
      <div data-temporal-extra="">
        ${box("approximate")}
        ${box("uncertain")}
      </div>
      <div data-temporal-extra="" hidden>
        <input type="checkbox" data-temporal-toggle="whole_decade_${endpoint}"${
          whole ? " checked" : ""
        }>
        ${openToggle ? `<input type="checkbox" data-temporal-toggle="${openToggle}">` : ""}
      </div>
    </fieldset>`;
}

/** One whole control, as the server renders it. */
function fieldMarkup(
  stored: Draft = {},
  expanded = "false",
  order: PartOrder = PARTS,
  fieldName = "",
  copySource = "",
): string {
  const draft: Draft = { ...EMPTY_DRAFT, ...stored };
  // One radio group per field.
  const shapeName = `${fieldName || "field"}-end-shape`;
  const kindOption = (value: string, text: string) =>
    `<option value="${value}"${value === draft.kind ? " selected" : ""}>${text}</option>`;
  return `
    <temporal-field expanded="${expanded}"${
      fieldName ? ` field-name="${fieldName}"` : ""
    }>
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
        ${endpointMarkup("start", "open_start", draft, order)}
        <fieldset data-temporal-extra="" hidden>
          <legend>After the start date</legend>
          <input type="radio" name="${shapeName}" value="end_none"
                 data-temporal-toggle="end_none" disabled>
          <input type="radio" name="${shapeName}" value="end_date"
                 data-temporal-toggle="end_date" disabled>
          <input type="radio" name="${shapeName}" value="end_open"
                 data-temporal-toggle="end_open" disabled>
        </fieldset>
        <div data-temporal-end-group="">
          ${endpointMarkup("end", "", draft, order)}
        </div>
        <div hidden data-temporal-disclosure-row="">
          <button type="button" data-temporal-disclosure="" aria-expanded="false">
            <span data-temporal-disclosure-label="collapsed">I don't know the exact date</span>
            <span data-temporal-disclosure-label="expanded" hidden>I know the exact date</span>
          </button>
        </div>
        <p data-temporal-announcement="" role="status" aria-live="polite"></p>
        ${
          copySource
            ? `<button type="button" data-temporal-copy="${copySource}"
                       title="Fill Original release first" hidden disabled>
                 Use original release
               </button>`
            : ""
        }
      </div>
    </temporal-field>`;
}

/** What a commit writes back: the same draft, padded to the segments. */
function normalized(stored: Draft): Draft {
  const draft: Draft = { ...EMPTY_DRAFT, ...stored };
  ["start", "end"].forEach((endpoint) => {
    const whole = draft[`${endpoint}_decade`] !== "";
    draft[`${endpoint}_year`] = whole ? "" : padded(draft[`${endpoint}_year`], 4);
    draft[`${endpoint}_month`] = whole ? "" : padded(draft[`${endpoint}_month`], 2);
    draft[`${endpoint}_day`] = whole ? "" : padded(draft[`${endpoint}_day`], 2);
    draft[`${endpoint}_decade`] = whole ? padded(draft[`${endpoint}_decade`], 4) : "";
  });
  return draft;
}

function mountDraft(
  stored: Draft = {},
  expanded = "false",
  order: PartOrder = PARTS,
): HTMLElement {
  document.body.innerHTML = fieldMarkup(stored, expanded, order);
  return document.querySelector("temporal-field")!;
}

/** A source, and a target that copies it. */
function mountPair(
  sourceDraft: Draft = {},
  targetDraft: Draft = {},
  copySource = "original_release_date",
): { source: HTMLElement; target: HTMLElement } {
  document.body.innerHTML =
    fieldMarkup(sourceDraft, "false", PARTS, "original_release_date") +
    fieldMarkup(targetDraft, "false", PARTS, "release_date", copySource);
  const fields = document.querySelectorAll<HTMLElement>("temporal-field");
  return { source: fields[0], target: fields[1] };
}

function mount(
  expanded = "false",
  storedEndYear = "",
  storedKind = "unknown",
  order: PartOrder = PARTS,
  storedStartYear = "",
): HTMLElement {
  return mountDraft(
    { kind: storedKind, end_year: storedEndYear, start_year: storedStartYear },
    expanded,
    order,
  );
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
  }
}

/** Type from the first segment; auto-advance carries focus. */
function typeFrom(host: HTMLElement, endpoint: string, digits: string): void {
  host
    .querySelector<HTMLInputElement>(`input[data-date-part][data-date-side="${endpoint}"]`)!
    .focus();
  for (const digit of digits) {
    document.activeElement!.dispatchEvent(
      new KeyboardEvent("keydown", { key: digit, bubbles: true }),
    );
  }
}

function region(host: HTMLElement): Element {
  return host.querySelector("[data-temporal-announcement]")!;
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

  describe.each(ORDERS)("with the segments ordered %s, %s, %s", (...order) => {
    const digitsFor: Record<string, string> = { year: "1984", month: "06", day: "22" };

    it("writes a whole typed day", () => {
      const host = mount("false", "", "unknown", order);

      typeFrom(host, "start", order.map((part) => digitsFor[part]).join(""));

      expect(named(host, "start_year").value).toBe("1984");
      expect(named(host, "start_month").value).toBe("06");
      expect(named(host, "start_day").value).toBe("22");
      expect(named(host, "kind").value).toBe("date");
    });

    it("writes a typed year", () => {
      const host = mount("false", "", "unknown", order);

      type(host, "start", "year", "1984");

      expect(named(host, "start_year").value).toBe("1984");
      expect(named(host, "kind").value).toBe("date");
    });
  });

  it("keeps a day typed before its year", () => {
    const host = mount("false", "", "unknown", ["day", "month", "year"]);

    type(host, "start", "day", "22");

    expect(segment(host, "start", "day").value).toBe("22");
    expect(named(host, "start_day").value).toBe("22");
    expect(named(host, "kind").value).toBe("date");
  });

  it("names the hole", () => {
    const host = mount("false", "", "unknown", ["day", "month", "year"]);

    type(host, "start", "day", "22");
    expect(region(host).textContent).toBe("Day needs a year and a month");

    type(host, "start", "year", "1984");
    expect(region(host).textContent).toBe("Day needs a month");

    type(host, "start", "month", "06");
    expect(region(host).textContent).toBe("Day precision");
  });

  it("leaves finer parts when a coarser one is cleared", () => {
    const host = mount();

    typeFrom(host, "start", "19840622");
    segment(host, "start", "year").focus();
    document.activeElement!.dispatchEvent(
      new KeyboardEvent("keydown", { key: "Backspace", bubbles: true }),
    );

    expect(named(host, "start_year").value).toBe("");
    expect(named(host, "start_month").value).toBe("06");
    expect(named(host, "start_day").value).toBe("22");
    expect(region(host).textContent).toBe("Day needs a year");
  });

  it("names a month typed before its year", () => {
    const host = mount("false", "", "unknown", ["month", "day", "year"]);

    typeFrom(host, "start", "06");

    expect(named(host, "start_month").value).toBe("06");
    expect(named(host, "kind").value).toBe("date");
    expect(region(host).textContent).toBe("Month needs a year");
  });

  it("clears a stored year", () => {
    const host = mount("false", "", "date", PARTS, "1984");

    segment(host, "start", "year").focus();
    document.activeElement!.dispatchEvent(
      new KeyboardEvent("keydown", { key: "Backspace", bubbles: true }),
    );

    expect(named(host, "start_year").value).toBe("");
    expect(named(host, "kind").value).toBe("unknown");
  });

  it("keeps committing after the decade snap", () => {
    const host = mount("true");

    type(host, "start", "year", "1982");
    check(host, "whole_decade_start");
    expect(named(host, "start_decade").value).toBe("1980");

    segment(host, "start", "year").focus();
    document.activeElement!.dispatchEvent(
      new KeyboardEvent("keydown", { key: "Backspace", bubbles: true }),
    );
    expect(named(host, "start_decade").value).toBe("");

    type(host, "start", "year", "1982");
    expect(segment(host, "start", "year").value).toBe("1980");
    expect(named(host, "start_decade").value).toBe("1980");
  });

  it("posts a half-typed decade for the server to refuse", () => {
    const host = mount("true");

    check(host, "whole_decade_start");
    type(host, "start", "year", "198");

    expect(named(host, "start_decade").value).toBe("198");
    expect(named(host, "kind").value).toBe("date");
    expect(region(host).textContent).toBe("Decade needs four digits");
  });

  it("keeps a year typed under the decade box", () => {
    const host = mount("true");

    type(host, "start", "year", "1985");
    check(host, "whole_decade_start");
    type(host, "start", "year", "2001");
    check(host, "whole_decade_start", false);

    // The snap comes back, not the year it was ticked over.
    expect(segment(host, "start", "year").value).toBe("2000");
    expect(named(host, "start_year").value).toBe("2000");
  });

  it("states no date from a hidden buffer under a decade", () => {
    const host = mount("true", "", "unknown", ["day", "month", "year"]);

    type(host, "start", "day", "22");
    check(host, "whole_decade_start");

    expect(named(host, "kind").value).toBe("unknown");
    expect(named(host, "start_day").value).toBe("");

    check(host, "whole_decade_start", false);

    expect(named(host, "kind").value).toBe("date");
    expect(named(host, "start_day").value).toBe("22");
    expect(region(host).textContent).toBe("Day needs a year and a month");
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
    const host = mount();
    toggleDisclosure(host);

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
    const host = mount();
    toggleDisclosure(host);
    pick(host, "end_date");
    type(host, "end", "year", "1986");

    expect(
      host.querySelector("[data-temporal-disclosure-row]")!.hasAttribute("hidden"),
    ).toBe(true);
  });

  it("opens already expanded when the stored value needs it", () => {
    const host = mountDraft({ kind: "date", start_year: "1997", start_uncertain: "on" });

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

  it("posts a half-typed year for the server to refuse", () => {
    const host = mount("true");
    check(host, "whole_decade_start");

    type(host, "start", "year", "19");

    expect(named(host, "start_decade").value).toBe("19");
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

  /** Every shape the server can render. */
  const STORED_SHAPES: Array<[string, Draft]> = [
    ["nothing", {}],
    ["a day", { kind: "date", start_year: "1997", start_month: "3", start_day: "15" }],
    ["a year alone", { kind: "date", start_year: "1997" }],
    ["a year and a month", { kind: "date", start_year: "1997", start_month: "3" }],
    [
      "an approximate day",
      { kind: "date", start_year: "1997", start_month: "3", start_approximate: "on" },
    ],
    ["an uncertain year", { kind: "date", start_year: "1997", start_uncertain: "on" }],
    ["a whole decade", { kind: "date", start_decade: "1990" }],
    ["a range", { kind: "range", start_year: "1997", end_year: "1999" }],
    ["a since", { kind: "since", start_year: "1997" }],
    ["an until", { kind: "until", end_year: "1999" }],
    // Two the server refuses and echoes back. A load must not repair
    // them, or the sentence refusing them names a value nobody sees.
    ["a decade off its boundary", { kind: "date", start_decade: "1995" }],
    ["a decade beside a year", { kind: "date", start_year: "1997", start_decade: "1990" }],
  ];

  it.each(STORED_SHAPES)("keeps what the server stored: %s", (_name, stored) => {
    const host = mountDraft(stored, "true");

    expect(readDraft(host)).toEqual({ ...EMPTY_DRAFT, ...stored });
  });

  it.each(STORED_SHAPES)("adopts its own draft unchanged: %s", (_name, stored) => {
    const host = mountDraft(stored, "true");
    const before = readDraft(host);

    adoptDraft(host, readDraft(host));

    expect(readDraft(host)).toEqual(before);
  });
});

describe("temporal-field copy", () => {
  beforeEach(() => {
    document.body.innerHTML = "";
  });

  function isExpanded(host: HTMLElement): boolean {
    return (
      host
        .querySelector("[data-temporal-disclosure]")!
        .getAttribute("aria-expanded") === "true"
    );
  }

  function part(host: HTMLElement, endpoint: string, name: string): HTMLElement {
    return host.querySelector<HTMLElement>(
      `[data-temporal-endpoint="${endpoint}"] [data-temporal-part="${name}"]`,
    )!;
  }

  it("copies a day whole", () => {
    const { source, target } = mountPair({
      kind: "date",
      start_year: "1997",
      start_month: "3",
      start_day: "15",
    });

    copyTemporalDraft(source, target);

    expect(readDraft(target)).toEqual(
      normalized({ kind: "date", start_year: "1997", start_month: "3", start_day: "15" }),
    );
    expect(named(target, "kind").value).toBe("date");
  });

  it("copies a range onto both ends", () => {
    const { source, target } = mountPair({
      kind: "range",
      start_year: "1997",
      end_year: "1999",
    });

    copyTemporalDraft(source, target);

    expect(named(target, "end_year").value).toBe("1999");
    expect(toggle(target, "end_date").checked).toBe(true);
    expect(named(target, "kind").value).toBe("range");
  });

  it("copies a since as a since", () => {
    const { source, target } = mountPair({ kind: "since", start_year: "1997" });

    copyTemporalDraft(source, target);

    expect(toggle(target, "end_open").checked).toBe(true);
    expect(named(target, "kind").value).toBe("since");
  });

  it("copies an until as an until", () => {
    const { source, target } = mountPair({ kind: "until", end_year: "1999" });

    copyTemporalDraft(source, target);

    expect(toggle(target, "open_start").checked).toBe(true);
    expect(toggle(target, "end_date").checked).toBe(true);
    expect(named(target, "kind").value).toBe("until");
    expect(toggle(target, "end_none").disabled).toBe(true);
  });

  it("hands the end choices back when a date lands on an until", () => {
    const { source, target } = mountPair(
      { kind: "date", start_year: "1997" },
      { kind: "until", end_year: "1999" },
    );

    copyTemporalDraft(source, target);

    expect(toggle(target, "open_start").checked).toBe(false);
    ["end_none", "end_date", "end_open"].forEach((shape) => {
      expect(toggle(target, shape).disabled).toBe(false);
    });
    expect(named(target, "end_year").value).toBe("");
  });

  it("opens a collapsed target that a since needs open", () => {
    const { source, target } = mountPair({ kind: "since", start_year: "1997" });
    expect(isExpanded(target)).toBe(false);

    copyTemporalDraft(source, target);

    expect(isExpanded(target)).toBe(true);
  });

  it("copies a whole decade with its box", () => {
    const { source, target } = mountPair({ kind: "date", start_decade: "1990" });

    copyTemporalDraft(source, target);

    expect(toggle(target, "whole_decade_start").checked).toBe(true);
    expect(named(target, "start_decade").value).toBe("1990");
    expect(named(target, "start_year").value).toBe("");
    expect(part(target, "start", "month").hasAttribute("hidden")).toBe(true);
    expect(part(target, "start", "day").hasAttribute("hidden")).toBe(true);
  });

  it("copies both qualifiers and opens for them", () => {
    const { source, target } = mountPair({
      kind: "date",
      start_year: "1997",
      start_approximate: "on",
      start_uncertain: "on",
    });

    copyTemporalDraft(source, target);

    expect(named(target, "start_approximate").checked).toBe(true);
    expect(named(target, "start_uncertain").checked).toBe(true);
    expect(isExpanded(target)).toBe(true);
  });

  it("leaves nothing of the value it overwrites", () => {
    const { source, target } = mountPair(
      { kind: "date", start_year: "1997" },
      { kind: "date", start_year: "2019", start_month: "8", start_day: "4" },
    );

    copyTemporalDraft(source, target);

    expect(named(target, "start_year").value).toBe("1997");
    expect(named(target, "start_month").value).toBe("");
    expect(named(target, "start_day").value).toBe("");
  });

  it("empties a target from a source that states nothing", () => {
    const { source, target } = mountPair({}, { kind: "date", start_year: "2019" });

    copyTemporalDraft(source, target);

    expect(named(target, "start_year").value).toBe("");
    expect(named(target, "kind").value).toBe("unknown");
  });

  it("announces every commit, because typing announces none", () => {
    const { source } = mountPair();
    const heard: string[] = [];
    document.body.addEventListener(TEMPORAL_FIELD_CHANGE_EVENT, () => {
      heard.push(named(source, "kind").value);
    });

    type(source, "start", "year", "1997");

    expect(heard).toContain("date");
  });
});

describe("temporal-field copy control", () => {
  beforeEach(() => {
    document.body.innerHTML = "";
  });

  function copyButton(host: HTMLElement): HTMLButtonElement {
    return host.querySelector<HTMLButtonElement>("[data-temporal-copy]")!;
  }

  it("shows and enables the button a filled source stands behind", () => {
    const { target } = mountPair({ kind: "date", start_year: "1997" });

    expect(copyButton(target).hasAttribute("hidden")).toBe(false);
    expect(copyButton(target).disabled).toBe(false);
  });

  it("copies the source on a press", () => {
    const { target } = mountPair({
      kind: "date",
      start_year: "1997",
      start_month: "3",
    });

    copyButton(target).click();

    expect(named(target, "start_year").value).toBe("1997");
    expect(named(target, "start_month").value).toBe("03");
  });

  it("leaves the button disabled while the source states nothing", () => {
    const { target } = mountPair();

    expect(copyButton(target).disabled).toBe(true);
    expect(copyButton(target).hasAttribute("hidden")).toBe(false);
  });

  it("enables the button when the source fills without a reload", () => {
    const { source, target } = mountPair();
    expect(copyButton(target).disabled).toBe(true);

    type(source, "start", "year", "1997");

    expect(copyButton(target).disabled).toBe(false);
  });

  it("stays disabled and quiet when the source is on no page", () => {
    const { target } = mountPair({ kind: "date", start_year: "1997" }, {}, "absent");

    expect(copyButton(target).disabled).toBe(true);
    expect(() => copyButton(target).click()).not.toThrow();
    expect(named(target, "start_year").value).toBe("");
  });
});

describe("temporal-field copy, the cases that bit", () => {
  beforeEach(() => {
    document.body.innerHTML = "";
  });

  it("forgets the year the target remembered", () => {
    const { source, target } = mountPair({ kind: "date", start_decade: "1990" });
    type(target, "start", "year", "1995");
    check(target, "whole_decade_start");

    copyTemporalDraft(source, target);
    check(target, "whole_decade_start", false);

    expect(named(target, "start_year").value).toBe("1990");
  });

  it("takes the decade box off a target that had one", () => {
    const { source, target } = mountPair(
      { kind: "date", start_year: "1997", start_month: "3" },
      { kind: "date", start_decade: "1980" },
    );

    copyTemporalDraft(source, target);

    expect(toggle(target, "whole_decade_start").checked).toBe(false);
    expect(named(target, "start_decade").value).toBe("");
    expect(named(target, "start_month").value).toBe("03");
    expect(
      target
        .querySelector('[data-temporal-endpoint="start"] [data-temporal-part="month"]')!
        .hasAttribute("hidden"),
    ).toBe(false);
  });

  it("snaps a copied end decade to its own boundary", () => {
    const { source, target } = mountPair({
      kind: "range",
      start_year: "1997",
      end_decade: "1995",
    });

    copyTemporalDraft(source, target);

    expect(segment(target, "end", "year").dataset.typedDigits).toBe(
      named(target, "end_decade").value,
    );
  });

  it("stays disabled while the source states a hole", () => {
    const { source, target } = mountPair();
    const button = target.querySelector<HTMLButtonElement>("[data-temporal-copy]")!;
    check(source, "whole_decade_start");

    type(source, "start", "year", "19");

    expect(button.disabled).toBe(true);
  });

  it("takes its title away once it works", () => {
    const { source, target } = mountPair();
    const button = target.querySelector<HTMLButtonElement>("[data-temporal-copy]")!;
    expect(button.getAttribute("title")).toBe("Fill Original release first");

    type(source, "start", "year", "1997");

    expect(button.hasAttribute("title")).toBe(false);
  });

  it("drops an end qualifier that has no end date", () => {
    const { source, target } = mountPair({
      kind: "date",
      start_year: "1997",
      end_uncertain: "on",
    });

    copyTemporalDraft(source, target);

    expect(named(target, "end_uncertain").checked).toBe(false);
    expect(named(target, "end_uncertain").value).toBe("on");
    expect(readDraft(target).end_uncertain).toBe("");
  });

  it("backspaces a copied end year", () => {
    const { source, target } = mountPair({
      kind: "range",
      start_year: "1997",
      end_year: "1999",
    });
    copyTemporalDraft(source, target);

    segment(target, "end", "year").focus();
    document.activeElement!.dispatchEvent(
      new KeyboardEvent("keydown", { key: "Backspace", bubbles: true }),
    );

    expect(named(target, "end_year").value).toBe("");
  });
});
