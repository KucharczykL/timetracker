// @vitest-environment jsdom
// The preset-picker personality's shell additions (issue #297): the
// search-select:action event, refetchOptions' query reset, URL composition
// with a pre-existing query string, clearSelection, and the
// XSS-by-construction property of client-built rows (labels flow through
// textContent only — this vitest guards what the old server-fragment
// HTML-escaping pytest used to, see tests/test_filter_presets.py docstring).
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import "./search-select.js"; // side-effect: customElements.define
import type { SearchSelectChangeDetail, SearchSelectActionDetail } from "./search-select.js";

Element.prototype.scrollIntoView = () => {};

interface PresetWidget extends HTMLElement {
  setSelected(value: string, label?: string): void;
  refetchOptions(): void;
  clearSelection(): void;
}

// The same shape PresetSelect renders server-side (rows are only ever built
// from this template clone).
const ROW_TEMPLATE = `
  <template data-search-select-template="row">
    <div data-search-select-option role="option" aria-selected="false">
      <span data-search-select-label></span>
      <button type="button" tabindex="-1" data-search-select-action="delete" aria-label="Delete preset">×</button>
    </div>
  </template>`;

function mountPreset(): PresetWidget {
  const host = document.createElement("search-select") as PresetWidget;
  host.setAttribute("name", "preset");
  host.setAttribute("multi", "false");
  host.setAttribute("always-visible", "true");
  host.setAttribute("search-url", "/api/presets/?mode=games");
  host.setAttribute("prefetch", "100");
  host.innerHTML = `
    <div data-search-select-pills></div>
    <input data-search-select-search />
    <div data-search-select-options role="listbox">
      <div data-search-select-no-results class="hidden">No saved presets</div>
    </div>
    ${ROW_TEMPLATE}
  `;
  document.body.appendChild(host);
  return host;
}

const searchBox = (host: HTMLElement): HTMLInputElement =>
  host.querySelector<HTMLInputElement>("[data-search-select-search]")!;

const flushPromises = () => new Promise((resolve) => setTimeout(resolve, 0));

function stubFetch(items: unknown[]): string[] {
  const requestedUrls: string[] = [];
  vi.stubGlobal("fetch", (url: string) => {
    requestedUrls.push(String(url));
    return Promise.resolve({ json: () => Promise.resolve(items) });
  });
  return requestedUrls;
}

describe("preset personality shell additions (#297)", () => {
  beforeEach(() => document.body.replaceChildren());
  afterEach(() => vi.unstubAllGlobals());

  it("composes the fetch URL with the search-url's existing query string", async () => {
    const requestedUrls = stubFetch([]);
    const host = mountPreset();
    host.refetchOptions();
    await flushPromises();

    expect(requestedUrls).toHaveLength(1);
    const url = new URL(requestedUrls[0], "http://localhost");
    expect(url.pathname).toBe("/api/presets/");
    expect(url.searchParams.get("mode")).toBe("games"); // not double-`?`ed away
    expect(url.searchParams.get("q")).toBe("");
    expect(url.searchParams.get("limit")).toBe("100");
  });

  it("refetchOptions resets a committed label so it never becomes the query", async () => {
    const requestedUrls = stubFetch([]);
    const host = mountPreset();
    host.setSelected("1", "Backlog"); // committed pick leaves its label in the box
    expect(searchBox(host).value).toBe("Backlog");

    host.refetchOptions();
    await flushPromises();

    expect(searchBox(host).value).toBe("");
    expect(new URL(requestedUrls[0], "http://localhost").searchParams.get("q")).toBe("");
  });

  it("refetch marks the widget prefetched so a following focus doesn't double-fetch", async () => {
    const requestedUrls = stubFetch([]);
    const host = mountPreset();
    host.refetchOptions();
    await flushPromises();
    searchBox(host).dispatchEvent(new Event("focus"));
    await flushPromises();
    expect(requestedUrls).toHaveLength(1);
  });

  it("a delete-button click dispatches search-select:action, never a pick", async () => {
    stubFetch([{ value: "1", label: "Backlog", data: { filter: "{}" } }]);
    const host = mountPreset();
    host.refetchOptions();
    await flushPromises();

    const actions: SearchSelectActionDetail[] = [];
    let changes = 0;
    host.addEventListener("search-select:action", (event) =>
      actions.push((event as CustomEvent<SearchSelectActionDetail>).detail),
    );
    host.addEventListener("search-select:change", () => (changes += 1));

    host
      .querySelector<HTMLElement>("[data-search-select-option] [data-search-select-action]")!
      .click();

    expect(actions).toEqual([
      {
        name: "preset",
        action: "delete",
        option: { value: "1", label: "Backlog", data: { filter: "{}" } },
      },
    ]);
    expect(changes).toBe(0);
    expect(host.querySelector('input[type="hidden"]')).toBeNull(); // no commit
  });

  it("a row click picks: change event carries the filter JSON in last.data", async () => {
    stubFetch([{ value: "1", label: "Backlog", data: { filter: '{"a":1}' } }]);
    const host = mountPreset();
    host.refetchOptions();
    await flushPromises();

    const changes: SearchSelectChangeDetail[] = [];
    host.addEventListener("search-select:change", (event) =>
      changes.push((event as CustomEvent<SearchSelectChangeDetail>).detail),
    );
    host.querySelector<HTMLElement>("[data-search-select-option]")!.click();

    expect(changes).toHaveLength(1);
    expect(changes[0].last?.data.filter).toBe('{"a":1}');
    expect(changes[0].values).toEqual(["1"]);
  });

  it("a hostile label cannot inject markup — rows render via textContent", async () => {
    const hostile = '<img src=x onerror=alert(1)>';
    stubFetch([{ value: "1", label: hostile, data: { filter: "{}" } }]);
    const host = mountPreset();
    host.refetchOptions();
    await flushPromises();

    const labelSlot = host.querySelector<HTMLElement>(
      "[data-search-select-option] [data-search-select-label]",
    )!;
    expect(labelSlot.textContent).toBe(hostile); // the raw string, visible as text
    expect(host.querySelector("img")).toBeNull(); // …never as an element
  });

  it("clearSelection silently drops the committed pick", () => {
    const host = mountPreset();
    let changes = 0;
    host.addEventListener("search-select:change", () => (changes += 1));
    host.setSelected("1", "Backlog");

    host.clearSelection();

    expect(host.querySelector('input[type="hidden"]')).toBeNull();
    expect(searchBox(host).value).toBe("");
    expect(changes).toBe(0);
  });
});
