// @vitest-environment jsdom
//
// A pinned row that holds none.
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import "./search-select.js"; // side effect: customElements.define
import type { SearchSelectChangeDetail, SearchSelectOption } from "./search-select.js";

Element.prototype.scrollIntoView = () => {};

interface NoneHost extends HTMLElement {
  setSelected(value: string, label?: string): void;
  setOptions(options: SearchSelectOption[]): void;
}

interface Held {
  value: string;
  label: string;
}

interface MountOptions {
  held?: Held;
  noneLabel?: string;
  createRow?: boolean;
  attributes?: Record<string, string>;
  formFields?: string;
  staticRows?: boolean;
}

const ROW_TEMPLATE = `<template data-search-select-template="row"><div
  data-search-select-option role="option" aria-selected="false"
><span data-search-select-label></span></div></template>`;

function markup({
  held,
  noneLabel = "No device",
  createRow = false,
  staticRows = true,
}: MountOptions): string {
  const pills = held
    ? `<input type="hidden" name="device" value="${held.value}">`
    : noneLabel
      ? '<input type="hidden" name="device" value="" data-search-select-none>'
      : "";
  const boxText = held ? held.label : noneLabel;
  const noneRow = noneLabel
    ? `<div role="option" aria-selected="false" data-search-select-none-option
        data-label="${noneLabel}"><span>${noneLabel}</span></div>`
    : "";
  const rows = staticRows
    ? `<div data-search-select-option data-value="1" data-label="Deck" role="option"><span data-search-select-label>Deck</span></div>
      <div data-search-select-option data-value="2" data-label="Switch" role="option"><span data-search-select-label>Switch</span></div>`
    : "";
  return `
    <div data-search-select-pills>${pills}</div>
    <input data-search-select-search value="${boxText}" />
    <button type="button" data-search-select-clear aria-label="Clear">×</button>
    <div data-search-select-options hidden>
      ${noneRow}
      ${rows}
      <div data-search-select-no-results class="hidden">No results</div>
      ${createRow ? '<div data-search-select-create hidden><span data-label></span></div>' : ""}
    </div>
    ${ROW_TEMPLATE}
  `;
}

function build(options: MountOptions = {}): NoneHost {
  const host = document.createElement("search-select") as NoneHost;
  host.setAttribute("name", "device");
  host.setAttribute("multi", "false");
  const noneLabel = options.noneLabel ?? "No device";
  if (noneLabel) host.setAttribute("none-label", noneLabel);
  if (options.createRow) host.setAttribute("create-url", "/api/devices/");
  for (const [attribute, value] of Object.entries(options.attributes ?? {})) {
    host.setAttribute(attribute, value);
  }
  host.innerHTML = markup(options);
  return host;
}

function mount(options: MountOptions = {}): NoneHost {
  document.body.replaceChildren();
  const host = build(options);
  if (options.formFields === undefined) {
    document.body.appendChild(host);
  } else {
    const form = document.createElement("form");
    form.innerHTML = options.formFields;
    form.appendChild(host);
    document.body.appendChild(form);
  }
  return host;
}

const searchBox = (host: HTMLElement) =>
  host.querySelector<HTMLInputElement>("[data-search-select-search]")!;
const clearButton = (host: HTMLElement) =>
  host.querySelector<HTMLButtonElement>("[data-search-select-clear]")!;
const noneRow = (host: HTMLElement) =>
  host.querySelector<HTMLElement>("[data-search-select-none-option]")!;
const noneInput = (host: HTMLElement) =>
  host.querySelector<HTMLInputElement>("[data-search-select-pills] input[data-search-select-none]");
const hiddenInputs = (host: HTMLElement) =>
  Array.from(
    host.querySelectorAll<HTMLInputElement>('[data-search-select-pills] input[type="hidden"]')
  );
const highlighted = (host: HTMLElement) =>
  host.querySelector<HTMLElement>("[data-search-select-options] [data-search-select-highlighted]");

function holdsNone(host: HTMLElement, label = "No device") {
  expect(noneInput(host)).not.toBeNull();
  expect(noneInput(host)!.value).toBe("");
  expect(hiddenInputs(host)).toHaveLength(1);
  expect(searchBox(host).value).toBe(label);
}

function type(host: HTMLElement, text: string) {
  const search = searchBox(host);
  search.value = text;
  search.dispatchEvent(new Event("input", { bubbles: true }));
}

function press(host: HTMLElement, key: string) {
  searchBox(host).dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true }));
}

type Recorded = { type: string; detail: SearchSelectChangeDetail | { name: string } };

function record(host: HTMLElement): Recorded[] {
  const events: Recorded[] = [];
  for (const type of ["search-select:change", "search-select:clear"]) {
    host.addEventListener(type, event =>
      events.push({ type, detail: (event as CustomEvent).detail })
    );
  }
  return events;
}

const changes = (events: Recorded[]) =>
  events
    .filter(event => event.type === "search-select:change")
    .map(event => event.detail as SearchSelectChangeDetail);

describe("<search-select> none: picking it", () => {
  beforeEach(() => document.body.replaceChildren());

  it("holds none on a click and says so", () => {
    const host = mount({ held: { value: "1", label: "Deck" } });
    const events = record(host);
    searchBox(host).focus();
    noneRow(host).click();
    holdsNone(host);
    expect(changes(events)).toEqual([
      { name: "device", values: [], last: null, none: true },
    ]);
  });

  it("reaches the row by arrow keys both ways and holds none on Enter", () => {
    const host = mount({ held: { value: "1", label: "Deck" } });
    const events = record(host);
    searchBox(host).focus();
    const reach = (key: string) => {
      for (let step = 0; step < 4 && highlighted(host) !== noneRow(host); step++) {
        press(host, key);
      }
      expect(highlighted(host)).toBe(noneRow(host));
    };
    reach("ArrowDown");
    press(host, "ArrowDown");
    reach("ArrowUp");
    expect(() => press(host, "Enter")).not.toThrow();
    holdsNone(host);
    expect(changes(events).at(-1)?.none).toBe(true);
  });

  it("is replaced by a programmatic set", () => {
    const host = mount();
    host.setSelected("2", "Switch");
    expect(noneInput(host)).toBeNull();
    expect(hiddenInputs(host).map(input => input.value)).toEqual(["2"]);
  });
});

describe("<search-select> none: the clear ×", () => {
  beforeEach(() => document.body.replaceChildren());

  it("hides while none is held", () => {
    expect(clearButton(mount()).hidden).toBe(true);
    expect(clearButton(mount({ held: { value: "1", label: "Deck" } })).hidden).toBe(false);
  });

  it("holds none from a held value, then clears", () => {
    const host = mount({ held: { value: "1", label: "Deck" } });
    const events = record(host);
    clearButton(host).click();
    holdsNone(host);
    expect(events.map(event => event.type)).toEqual([
      "search-select:change",
      "search-select:clear",
    ]);
    expect(changes(events)[0].none).toBe(true);
    expect(clearButton(host).hidden).toBe(true);
  });

  it("holds none from typed text", () => {
    const host = mount();
    searchBox(host).focus();
    type(host, "De");
    expect(clearButton(host).hidden).toBe(false);
    const events = record(host);
    clearButton(host).click();
    holdsNone(host);
    expect(changes(events)).toEqual([
      { name: "device", values: [], last: null, none: true },
    ]);
  });
});

describe("<search-select> none: typing", () => {
  beforeEach(() => document.body.replaceChildren());

  it("drops a held value to nothing picked, not none", () => {
    const host = mount({ held: { value: "1", label: "Deck" } });
    const events = record(host);
    searchBox(host).focus();
    type(host, "S");
    expect(hiddenInputs(host)).toHaveLength(0);
    expect(changes(events)).toEqual([
      { name: "device", values: [], last: null, none: false },
    ]);
  });

  it("drops a held none to nothing picked", () => {
    const host = mount();
    const events = record(host);
    searchBox(host).focus();
    type(host, "S");
    expect(hiddenInputs(host)).toHaveLength(0);
    expect(changes(events)).toEqual([
      { name: "device", values: [], last: null, none: false },
    ]);
  });

  it("never highlights the none row for a partial query", () => {
    const host = mount({ held: { value: "1", label: "Deck" } });
    searchBox(host).focus();
    type(host, "No");
    expect(highlighted(host)).not.toBe(noneRow(host));
    type(host, "Sw");
    expect(noneRow(host).style.display).not.toBe("none");
    expect(noneRow(host).hidden).toBe(false);
  });

  it("does not pick none on Enter over a panel with no value rows", () => {
    const host = mount({ held: { value: "1", label: "Deck" }, staticRows: false });
    searchBox(host).focus();
    press(host, "Enter");
    expect(noneInput(host)).toBeNull();
    expect(hiddenInputs(host).map(input => input.value)).toEqual(["1"]);
  });

  it("highlights the none row for its exact label, and Enter holds none", () => {
    const host = mount({ held: { value: "1", label: "Deck" } });
    searchBox(host).focus();
    type(host, "no device");
    expect(highlighted(host)).toBe(noneRow(host));
    press(host, "Enter");
    holdsNone(host);
  });

  it("offers no create row for the none label", () => {
    const host = mount({ createRow: true });
    searchBox(host).focus();
    type(host, "No device");
    expect(host.querySelector<HTMLElement>("[data-search-select-create]")!.hidden).toBe(
      true
    );
  });
});

describe("<search-select> none: beside answers and dependencies", () => {
  beforeEach(() => document.body.replaceChildren());
  afterEach(() => vi.unstubAllGlobals());

  const answering = (rows: SearchSelectOption[]) =>
    vi.fn(() =>
      Promise.resolve({ ok: true, json: () => Promise.resolve(rows) } as Response)
    );

  it("keeps the row first and none held through a server answer", async () => {
    const fetchMock = answering([{ value: "9", label: "Deck", data: {} }]);
    vi.stubGlobal("fetch", fetchMock);
    const host = mount({
      staticRows: false,
      attributes: {
        "search-url": "/api/devices/search",
        prefetch: "20",
        "commit-sole-option": "true",
      },
    });
    searchBox(host).focus();
    await vi.waitFor(() =>
      expect(host.querySelector("[data-search-select-option]")).not.toBeNull()
    );
    const rows = host.querySelectorAll("[role='option']");
    expect(rows[0]).toBe(noneRow(host));
    holdsNone(host);
  });

  it("opens and prefetches an autofocused picker that holds none", async () => {
    const fetchMock = answering([{ value: "9", label: "Deck", data: {} }]);
    vi.stubGlobal("fetch", fetchMock);
    document.body.replaceChildren();
    const host = build({
      staticRows: false,
      attributes: { "search-url": "/api/devices/search", prefetch: "20" },
    });
    searchBox(host).setAttribute("autofocus", "");
    document.body.appendChild(host);
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());
    holdsNone(host);
    expect(document.activeElement).toBe(searchBox(host));
    expect(searchBox(host).getAttribute("aria-expanded")).toBe("true");
  });

  it("keeps the row through a typed query's server answer", async () => {
    vi.stubGlobal("fetch", answering([{ value: "9", label: "Switch", data: {} }]));
    const host = mount({
      staticRows: false,
      attributes: { "search-url": "/api/devices/search" },
    });
    searchBox(host).focus();
    type(host, "Sw");
    await vi.waitFor(() =>
      expect(host.querySelector("[data-search-select-option]")).not.toBeNull()
    );
    expect(host.querySelectorAll("[role='option']")[0]).toBe(noneRow(host));
    expect(noneRow(host).style.display).not.toBe("none");
  });

  it("keeps none held through setOptions", () => {
    const host = mount();
    host.setOptions([{ value: "5", label: "PC", data: {} }]);
    holdsNone(host);
    expect(host.querySelectorAll("[role='option']")[0]).toBe(noneRow(host));
  });

  it("turns a stale value into none through setOptions", () => {
    const host = mount({ held: { value: "1", label: "Deck" } });
    host.setOptions([{ value: "5", label: "PC", data: {} }]);
    holdsNone(host);
  });

  it("turns a held value into none on a dependency change, silently", async () => {
    vi.stubGlobal("fetch", answering([]));
    const host = mount({
      held: { value: "1", label: "Deck" },
      formFields: '<input type="hidden" name="game" value="g1" />',
      attributes: { params: JSON.stringify({ game: { field: "game" } }) },
    });
    const events = record(host);
    const game = document.querySelector<HTMLInputElement>('[name="game"]')!;
    game.value = "g2";
    game.dispatchEvent(new Event("change", { bubbles: true }));
    await vi.waitFor(() => holdsNone(host));
    expect(changes(events)).toEqual([]);
  });

  it("keeps a held none on a dependency change", async () => {
    vi.stubGlobal("fetch", answering([]));
    const host = mount({
      formFields: '<input type="hidden" name="game" value="g1" />',
      attributes: { params: JSON.stringify({ game: { field: "game" } }) },
    });
    const game = document.querySelector<HTMLInputElement>('[name="game"]')!;
    game.value = "g2";
    game.dispatchEvent(new Event("change", { bubbles: true }));
    await Promise.resolve();
    holdsNone(host);
  });

  it("holds none in each of two cloned pickers apart", () => {
    document.body.replaceChildren();
    const prototype = build({ held: { value: "1", label: "Deck" } });
    const first = prototype.cloneNode(true) as NoneHost;
    const second = prototype.cloneNode(true) as NoneHost;
    document.body.append(first, second);
    clearButton(first).click();
    holdsNone(first);
    expect(hiddenInputs(second).map(input => input.value)).toEqual(["1"]);
  });
});

describe("<search-select> without a none label", () => {
  beforeEach(() => document.body.replaceChildren());

  it("states none: false on every change", () => {
    const host = mount({ noneLabel: "", held: { value: "1", label: "Deck" } });
    const events = record(host);
    clearButton(host).click();
    host.querySelector<HTMLElement>('[data-value="2"]')!.click();
    expect(changes(events).map(change => change.none)).toEqual([false, false]);
    expect(hiddenInputs(host).map(input => input.value)).toEqual(["2"]);
  });
});
