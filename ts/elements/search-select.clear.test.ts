// @vitest-environment jsdom
//
// The clear ×: visibility, press, events, focus.
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import "./search-select.js"; // side effect: customElements.define
import type {
  SearchSelectChangeDetail,
  SearchSelectClearDetail,
} from "./search-select.js";

Element.prototype.scrollIntoView = () => {};

interface Seed {
  value: string;
  label: string;
}

interface StatefulHost extends HTMLElement {
  _searchSelectSetSelected?: (value: string, label?: string) => void;
  _searchSelectClear?: () => void;
}

interface MountOptions {
  multi?: boolean;
  attributes?: Record<string, string>;
  withButton?: boolean;
  staticRows?: boolean;
}

const ROW_TEMPLATE = `<template data-search-select-template="row"><div
  data-search-select-option role="option" aria-selected="false"
><span data-search-select-label></span></div></template>`;

function mount(
  seeds: Seed[],
  {
    multi = false,
    attributes = {},
    withButton = true,
    staticRows = true,
  }: MountOptions = {},
): StatefulHost {
  document.body.replaceChildren();
  const host = document.createElement("search-select") as StatefulHost;
  host.setAttribute("name", "device");
  host.setAttribute("multi", String(multi));
  for (const [attribute, value] of Object.entries(attributes)) {
    host.setAttribute(attribute, value);
  }
  const hidden = seeds
    .map(
      seed =>
        (multi
          ? `<span data-pill data-value="${seed.value}">${seed.label}` +
            `<button type="button" data-pill-remove>×</button></span>`
          : "") + `<input type="hidden" name="device" value="${seed.value}">`,
    )
    .join("");
  const boxText = multi ? "" : (seeds[0]?.label ?? "");
  const button = withButton
    ? `<button type="button" data-search-select-clear aria-label="Clear"${
        seeds.length ? "" : " hidden"
      }>×</button>`
    : "";
  const rows = staticRows
    ? `<div data-search-select-option data-value="1" role="option"><span data-search-select-label>Deck</span></div>
      <div data-search-select-option data-value="2" role="option"><span data-search-select-label>Switch</span></div>`
    : "";
  host.innerHTML = `
    <div data-search-select-pills>${hidden}</div>
    <input data-search-select-search value="${boxText}" />
    ${button}
    <div data-search-select-options class="hidden">
      ${rows}
      <div data-search-select-no-results class="hidden">No results</div>
    </div>
    ${ROW_TEMPLATE}
  `;
  document.body.appendChild(host);
  return host;
}

const searchBox = (host: HTMLElement) =>
  host.querySelector<HTMLInputElement>("[data-search-select-search]")!;
const clearButton = (host: HTMLElement) =>
  host.querySelector<HTMLButtonElement>("[data-search-select-clear]")!;
const heldValues = (host: HTMLElement) =>
  Array.from(
    host.querySelectorAll<HTMLInputElement>(
      '[data-search-select-pills] input[type="hidden"]',
    ),
  ).map(input => input.value);

function type(host: HTMLElement, text: string) {
  const search = searchBox(host);
  search.value = text;
  search.dispatchEvent(new Event("input", { bubbles: true }));
}

type Recorded = { type: string; detail: unknown };

function record(host: HTMLElement): Recorded[] {
  const events: Recorded[] = [];
  for (const type of ["search-select:change", "search-select:clear"]) {
    host.addEventListener(type, event =>
      events.push({ type, detail: (event as CustomEvent).detail }),
    );
  }
  return events;
}

describe("<search-select> clear ×: visibility", () => {
  beforeEach(() => document.body.replaceChildren());

  it("hides with nothing held and shows with a committed value", () => {
    expect(clearButton(mount([])).hidden).toBe(true);
    expect(clearButton(mount([{ value: "1", label: "Deck" }])).hidden).toBe(false);
  });

  it("follows a typed query", () => {
    const host = mount([]);
    type(host, "De");
    expect(clearButton(host).hidden).toBe(false);
    type(host, "");
    expect(clearButton(host).hidden).toBe(true);
  });

  it("follows a pick, a programmatic set and a silent clear", () => {
    const host = mount([]);
    host.querySelector<HTMLElement>('[data-value="1"]')!.click();
    expect(clearButton(host).hidden).toBe(false);
    host._searchSelectClear!();
    expect(clearButton(host).hidden).toBe(true);
    host._searchSelectSetSelected!("2", "Switch");
    expect(clearButton(host).hidden).toBe(false);
  });

  it("hides after the last multi pill goes", () => {
    const host = mount([{ value: "1", label: "Deck" }], { multi: true });
    expect(clearButton(host).hidden).toBe(false);
    host.querySelector<HTMLButtonElement>("[data-pill-remove]")!.click();
    expect(clearButton(host).hidden).toBe(true);
  });
});

describe("<search-select> clear ×: a press", () => {
  beforeEach(() => document.body.replaceChildren());
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("drops a committed single value, then announces change and clear", () => {
    const host = mount([{ value: "1", label: "Deck" }]);
    const events = record(host);
    clearButton(host).click();

    expect(heldValues(host)).toEqual([]);
    expect(searchBox(host).value).toBe("");
    expect(clearButton(host).hidden).toBe(true);
    expect(events.map(event => event.type)).toEqual([
      "search-select:change",
      "search-select:clear",
    ]);
    const change = events[0].detail as SearchSelectChangeDetail;
    expect(change.values).toEqual([]);
    expect(change.last).toBeNull();
  });

  it("announces a query-only press as a clear and no change", () => {
    const host = mount([]);
    type(host, "Sw");
    const events = record(host);
    clearButton(host).click();

    expect(searchBox(host).value).toBe("");
    expect(events.map(event => event.type)).toEqual(["search-select:clear"]);
    expect(events[0].detail as SearchSelectClearDetail).toEqual({ name: "device" });
  });

  it("drops every pill and the query in multi mode", () => {
    const host = mount(
      [
        { value: "1", label: "Deck" },
        { value: "2", label: "Switch" },
      ],
      { multi: true },
    );
    type(host, "Ga");
    const events = record(host);
    clearButton(host).click();

    expect(heldValues(host)).toEqual([]);
    expect(host.querySelector("[data-pill]")).toBeNull();
    expect(searchBox(host).value).toBe("");
    expect(events.map(event => event.type)).toEqual([
      "search-select:change",
      "search-select:clear",
    ]);
  });

  it("cancels a search the old query scheduled", () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn(() =>
      Promise.resolve({ ok: true, json: () => Promise.resolve([]) } as Response),
    );
    vi.stubGlobal("fetch", fetchMock);
    const host = mount([], { attributes: { "search-url": "/api/devices/search" } });
    type(host, "Sw");
    clearButton(host).click();
    vi.runAllTimers();

    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("shows every row again after clearing a filtering query", () => {
    const host = mount([]);
    type(host, "Sw");
    clearButton(host).click();
    const hiddenRows = Array.from(
      host.querySelectorAll<HTMLElement>("[data-search-select-option]"),
    ).filter(row => row.style.display === "none");
    expect(hiddenRows).toEqual([]);
  });

  it("keeps a cleared field empty when the next search answers one option", async () => {
    const fetchMock = vi.fn(() =>
      Promise.resolve({
        ok: true,
        json: () => Promise.resolve([{ value: "r1", label: "Playthrough 1", data: {} }]),
      } as Response),
    );
    vi.stubGlobal("fetch", fetchMock);
    const host = mount([{ value: "r1", label: "Playthrough 1" }], {
      attributes: {
        "search-url": "/api/playthrough/search",
        prefetch: "20",
        "commit-sole-option": "true",
      },
      staticRows: false,
    });
    clearButton(host).focus();
    clearButton(host).click();

    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());
    await vi.waitFor(() =>
      expect(host.querySelector("[data-search-select-option]")).not.toBeNull(),
    );
    expect(heldValues(host)).toEqual([]);

    host.querySelector<HTMLElement>("[data-search-select-option]")!.click();
    expect(heldValues(host)).toEqual(["r1"]);
  });
});

describe("<search-select> clear ×: focus", () => {
  beforeEach(() => document.body.replaceChildren());

  it("moves focus to the box after a press from the focused button", () => {
    const host = mount([{ value: "1", label: "Deck" }]);
    clearButton(host).focus();
    clearButton(host).click();
    expect(document.activeElement).toBe(searchBox(host));
  });

  it("leaves focus alone after a pointer press", () => {
    const host = mount([{ value: "1", label: "Deck" }]);
    const elsewhere = document.createElement("input");
    document.body.appendChild(elsewhere);
    elsewhere.focus();
    const mousedown = new MouseEvent("mousedown", { bubbles: true, cancelable: true });
    clearButton(host).dispatchEvent(mousedown);
    clearButton(host).click();

    expect(mousedown.defaultPrevented).toBe(true);
    expect(document.activeElement).toBe(elsewhere);
  });

  it("closes an open panel when the button takes focus", () => {
    const host = mount([]);
    searchBox(host).focus();
    type(host, "De");
    expect(searchBox(host).getAttribute("aria-expanded")).toBe("true");
    clearButton(host).focus();
    expect(searchBox(host).getAttribute("aria-expanded")).toBe("false");
  });

  it("changes nothing on a widget without the button", () => {
    const host = mount([{ value: "1", label: "Deck" }], { withButton: false });
    type(host, "Sw");
    expect(heldValues(host)).toEqual([]);
  });
});
