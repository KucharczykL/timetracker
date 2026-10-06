// @vitest-environment jsdom
//
// Re-picks, silent holds, and leaving mid-edit.
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import "./search-select.js"; // side effect: customElements.define
import { hosted } from "../test-setup/search-select-host.js";
import type { SearchSelectChangeDetail, SearchSelectElement } from "./search-select.js";

Element.prototype.scrollIntoView = () => {};

interface MountOptions {
  held?: string;
  noneLabel?: string;
  revertOnLeave?: boolean;
  describedBy?: string;
  searchUrl?: string;
}

const LABELS: Record<string, string> = { "1": "Deck", "2": "Switch" };

function mount({
  held,
  noneLabel = "Use site default (Deck)",
  revertOnLeave = true,
  describedBy,
  searchUrl,
}: MountOptions = {}): SearchSelectElement {
  document.body.replaceChildren();
  const host = document.createElement("search-select") as SearchSelectElement;
  host.setAttribute("name", "device");
  host.setAttribute("multi", "false");
  if (noneLabel) host.setAttribute("none-label", noneLabel);
  if (revertOnLeave) host.setAttribute("revert-on-leave", "true");
  if (searchUrl) host.setAttribute("search-url", searchUrl);
  const pills = held
    ? `<input type="hidden" name="device" value="${held}">`
    : noneLabel
      ? '<input type="hidden" name="device" value="" data-search-select-none>'
      : "";
  const noneRow = noneLabel
    ? `<div role="option" data-search-select-none-option data-label="${noneLabel}"><span>${noneLabel}</span></div>`
    : "";
  const rows = Object.entries(LABELS)
    .map(
      ([value, label]) =>
        `<div data-search-select-option data-value="${value}" data-label="${label}" role="option"><span data-search-select-label>${label}</span></div>`
    )
    .join("");
  host.innerHTML = `
    <div data-search-select-pills>${pills}</div>
    <input data-search-select-search value="${held ? LABELS[held] : noneLabel}"
      ${describedBy ? `aria-describedby="${describedBy}"` : ""} />
    <button type="button" data-search-select-clear aria-label="Clear">×</button>
    <span data-search-select-status role="status"></span>
    <div data-search-select-options hidden>${noneRow}${rows}
      <div data-search-select-no-results class="hidden">No results</div>
    </div>
    <button type="button" data-outside>elsewhere</button>
  `;
  const outside = host.querySelector("[data-outside]")!;
  document.body.appendChild(hosted(host));
  document.body.appendChild(outside);
  return host;
}

const searchBox = (host: HTMLElement) =>
  host.querySelector<HTMLInputElement>("[data-search-select-search]")!;
const clearButton = (host: HTMLElement) =>
  host.querySelector<HTMLButtonElement>("[data-search-select-clear]")!;
const row = (host: HTMLElement, value: string) =>
  host.querySelector<HTMLElement>(`[data-search-select-option][data-value="${value}"]`)!;
const noneRow = (host: HTMLElement) =>
  host.querySelector<HTMLElement>("[data-search-select-none-option]")!;
const outside = () => document.querySelector<HTMLButtonElement>("[data-outside]")!;

interface Held {
  values: string[];
  none: boolean;
  text: string;
}

function held(host: HTMLElement): Held {
  const inputs = Array.from(
    host.querySelectorAll<HTMLInputElement>('[data-search-select-pills] input[type="hidden"]')
  );
  return {
    values: inputs.filter(input => !input.hasAttribute("data-search-select-none")).map(input => input.value),
    none: inputs.some(input => input.hasAttribute("data-search-select-none")),
    text: searchBox(host).value,
  };
}

function record(host: HTMLElement): SearchSelectChangeDetail[] {
  const events: SearchSelectChangeDetail[] = [];
  host.addEventListener("search-select:change", event =>
    events.push((event as CustomEvent<SearchSelectChangeDetail>).detail)
  );
  return events;
}

function type(host: HTMLElement, text: string) {
  const search = searchBox(host);
  search.focus();
  search.value = text;
  search.dispatchEvent(new Event("input", { bubbles: true }));
}

function leaveTo(host: HTMLElement, target: HTMLElement | null) {
  searchBox(host).dispatchEvent(
    new FocusEvent("focusout", { bubbles: true, relatedTarget: target })
  );
}

describe("<search-select> a pick that changes nothing", () => {
  beforeEach(() => document.body.replaceChildren());

  it("emits nothing for the held option", () => {
    const host = mount({ held: "1" });
    const events = record(host);
    searchBox(host).focus();
    row(host, "1").click();
    expect(events).toEqual([]);
    expect(held(host)).toEqual({ values: ["1"], none: false, text: "Deck" });
  });

  it("emits nothing for the none row while none is held", () => {
    const host = mount();
    const events = record(host);
    searchBox(host).focus();
    noneRow(host).click();
    expect(events).toEqual([]);
  });

  it("emits for another option", () => {
    const host = mount({ held: "1" });
    const events = record(host);
    searchBox(host).focus();
    row(host, "2").click();
    expect(events.map(event => event.values)).toEqual([["2"]]);
  });

  it("emits the held option again after a drop", () => {
    const host = mount({ held: "1" });
    const events = record(host);
    type(host, "De");
    row(host, "1").click();
    expect(events.map(event => event.values)).toEqual([[], ["1"]]);
  });
});

describe("<search-select> holdValue and holdNone", () => {
  beforeEach(() => document.body.replaceChildren());

  it("holds an offered value with its row's label, silently", () => {
    const host = mount();
    const events = record(host);
    host.holdValue("2");
    expect(held(host)).toEqual({ values: ["2"], none: false, text: "Switch" });
    expect(clearButton(host).hidden).toBe(false);
    expect(events).toEqual([]);
  });

  it("holds none for a value no row offers", () => {
    const host = mount({ held: "1" });
    host.holdValue("9");
    expect(held(host)).toEqual({ values: [], none: true, text: "Use site default (Deck)" });
  });

  it("holds nothing for an unoffered value without a none row", () => {
    const host = mount({ held: "1", noneLabel: "" });
    host.holdValue("9");
    expect(held(host)).toEqual({ values: [], none: false, text: "" });
  });

  it("holds none silently", () => {
    const host = mount({ held: "1" });
    const events = record(host);
    host.holdNone();
    expect(held(host).none).toBe(true);
    expect(clearButton(host).hidden).toBe(true);
    expect(events).toEqual([]);
  });
});

describe("<search-select> revert-on-leave", () => {
  beforeEach(() => document.body.replaceChildren());

  it("holds the value again when focus leaves mid-edit, silently", () => {
    const host = mount({ held: "1" });
    type(host, "Sw");
    const events = record(host);
    leaveTo(host, outside());
    expect(held(host)).toEqual({ values: ["1"], none: false, text: "Deck" });
    expect(events).toEqual([]);
  });

  it("holds none again", () => {
    const host = mount();
    type(host, "Sw");
    leaveTo(host, null);
    expect(held(host)).toEqual({ values: [], none: true, text: "Use site default (Deck)" });
  });

  it("stays while focus moves to the ×", () => {
    const host = mount({ held: "1" });
    type(host, "Sw");
    leaveTo(host, clearButton(host));
    expect(held(host)).toEqual({ values: [], none: false, text: "Sw" });
  });

  it("keeps a pick made after the drop", () => {
    const host = mount({ held: "1" });
    type(host, "Sw");
    row(host, "2").click();
    leaveTo(host, outside());
    expect(held(host).values).toEqual(["2"]);
  });

  it("keeps the typed text without the prop", () => {
    const host = mount({ held: "1", revertOnLeave: false });
    type(host, "Sw");
    leaveTo(host, outside());
    expect(held(host)).toEqual({ values: [], none: false, text: "Sw" });
  });
});

describe("<search-select> aria-describedby", () => {
  it("keeps a rendered id beside the status", () => {
    const host = mount({ held: "1", describedBy: "help-id" });
    const ids = searchBox(host).getAttribute("aria-describedby")!.split(" ");
    expect(ids[0]).toBe("help-id");
    expect(ids).toHaveLength(2);
    expect(document.getElementById(ids[1])?.hasAttribute("data-search-select-status")).toBe(true);
  });
});

describe("<search-select> review cases", () => {
  beforeEach(() => document.body.replaceChildren());

  const press = (host: HTMLElement, key: string) =>
    searchBox(host).dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true }));

  it("keeps an open panel when the held value is held again", () => {
    const host = mount({ held: "1" });
    searchBox(host).focus();
    press(host, "ArrowDown");
    expect(searchBox(host).getAttribute("aria-expanded")).toBe("true");
    expect(host.holdValue("1")).toBe(true);
    expect(searchBox(host).getAttribute("aria-expanded")).toBe("true");
    host.holdNone();
    host.holdValue("1");
    expect(searchBox(host).getAttribute("aria-expanded")).toBe("false");
  });

  it("answers whether a row offered the value", () => {
    const host = mount({ held: "1" });
    expect(host.offers("2")).toBe(true);
    expect(host.offers("9")).toBe(false);
    expect(host.holdValue("9")).toBe(false);
  });

  it("forgets the dropped value once none is held from code", () => {
    const host = mount({ held: "1" });
    type(host, "Sw");
    host.holdNone();
    leaveTo(host, outside());
    expect(held(host).none).toBe(true);
    type(host, "De");
    leaveTo(host, outside());
    expect(held(host)).toEqual({ values: [], none: true, text: "Use site default (Deck)" });
  });

  it("emits nothing for Enter on the held row", () => {
    const host = mount({ held: "2" });
    const events = record(host);
    searchBox(host).focus();
    for (let step = 0; step < 4 && !row(host, "2").hasAttribute("data-search-select-highlighted"); step++) {
      press(host, "ArrowDown");
    }
    press(host, "Enter");
    expect(events).toEqual([]);
    expect(held(host).values).toEqual(["2"]);
  });

  it("emits nothing for a multi-select re-pick of a held value", () => {
    const host = mount({ held: "1", noneLabel: "" });
    host.setAttribute("multi", "true");
    const fresh = host.cloneNode(true) as SearchSelectElement;
    host.replaceWith(fresh);
    const events = record(fresh);
    searchBox(fresh).focus();
    row(fresh, "1").click();
    expect(events).toEqual([]);
    row(fresh, "2").click();
    expect(events.map(event => event.values)).toEqual([["1", "2"]]);
  });

  it("refuses a hold before it initialises", () => {
    const host = document.createElement("search-select") as SearchSelectElement;
    expect(() => host.holdNone()).toThrow(/not initialised/);
  });
});

describe("<search-select> a click into the focused box", () => {
  beforeEach(() => document.body.replaceChildren());

  it("opens the list again after a pick", () => {
    const host = mount({ held: "1" });
    searchBox(host).focus();
    row(host, "2").click();
    expect(searchBox(host).getAttribute("aria-expanded")).toBe("false");

    searchBox(host).click();

    expect(searchBox(host).getAttribute("aria-expanded")).toBe("true");
    expect(held(host).values).toEqual(["2"]);
  });

  it("leaves an open list open", () => {
    const host = mount({ held: "1" });
    searchBox(host).focus();
    searchBox(host).click();
    expect(searchBox(host).getAttribute("aria-expanded")).toBe("true");
  });
});

describe("<search-select> remembers what it held", () => {
  beforeEach(() => {
    document.body.replaceChildren();
    //: Never answers; × leaves the rows.
    vi.stubGlobal("fetch", vi.fn(() => new Promise(() => {})));
  });
  afterEach(() => vi.unstubAllGlobals());

  const searched = (options: MountOptions = {}) =>
    mount({ ...options, searchUrl: "/api/devices/search" });

  it("holds the rendered value after × dropped its row", () => {
    const host = searched({ held: "1" });
    clearButton(host).click();
    expect(row(host, "1")).toBeNull();
    expect(host.offers("1")).toBe(true);
    expect(host.holdValue("1")).toBe(true);
    expect(held(host)).toEqual({ values: ["1"], none: false, text: "Deck" });
  });

  it("holds a picked value after × dropped its row", () => {
    const host = searched({ held: "1" });
    row(host, "2").click();
    clearButton(host).click();
    expect(host.holdValue("2")).toBe(true);
    expect(held(host)).toEqual({ values: ["2"], none: false, text: "Switch" });
  });

  it("remembers no value it never held", () => {
    const host = searched({ held: "1" });
    clearButton(host).click();
    expect(host.offers("2")).toBe(false);
    expect(host.holdValue("2")).toBe(false);
    expect(held(host).none).toBe(true);
  });

  it("seeds nothing from a held none", () => {
    const host = searched();
    clearButton(host).click();
    expect(host.offers("")).toBe(false);
  });

  it("forgets every held value when the options are replaced", () => {
    const host = mount({ held: "1" });
    host.setOptions([{ value: "2", label: "Switch", data: {} }]);
    expect(host.offers("1")).toBe(false);
    expect(host.holdValue("1")).toBe(false);
  });
});
