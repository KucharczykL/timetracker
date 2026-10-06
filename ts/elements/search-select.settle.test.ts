// @vitest-environment jsdom
//
// A pick that changes nothing, a held value, and leaving mid-edit.
import { describe, it, expect, beforeEach } from "vitest";
import "./search-select.js"; // side effect: customElements.define
import { hosted } from "../test-setup/search-select-host.js";
import type { SearchSelectChangeDetail, SearchSelectElement } from "./search-select.js";

Element.prototype.scrollIntoView = () => {};

interface MountOptions {
  held?: string;
  noneLabel?: string;
  revertOnLeave?: boolean;
  describedBy?: string;
}

const LABELS: Record<string, string> = { "1": "Deck", "2": "Switch" };

function mount({
  held,
  noneLabel = "Use site default (Deck)",
  revertOnLeave = true,
  describedBy,
}: MountOptions = {}): SearchSelectElement {
  document.body.replaceChildren();
  const host = document.createElement("search-select") as SearchSelectElement;
  host.setAttribute("name", "device");
  host.setAttribute("multi", "false");
  if (noneLabel) host.setAttribute("none-label", noneLabel);
  if (revertOnLeave) host.setAttribute("revert-on-leave", "true");
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
