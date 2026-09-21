// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import "./search-select.js";

Element.prototype.scrollIntoView = () => {};

interface SearchSelectLike extends HTMLElement {
  setSelected(value: string, label?: string): void;
}

const CREATE_ROW = "[data-search-select-create]";

type Row = { value: string; label: string; data: Record<string, string> };

/** The search route's answer, and a create route that echoes a new key. */
function stubEndpoints(rows: Row[]) {
  const searchMock = vi.fn(() =>
    Promise.resolve({ ok: true, json: () => Promise.resolve(rows) } as Response)
  );
  vi.stubGlobal("fetch", searchMock);
  const createMock = vi.fn((url: RequestInfo | URL, options?: RequestInit) => {
    void url;
    void options;
    return Promise.resolve({
      ok: true,
      json: () => Promise.resolve({ id: "new-key", label: "New Game Plus" }),
    } as Response);
  });
  window.fetchWithHtmxTriggers = createMock as unknown as typeof window.fetchWithHtmxTriggers;
  return { searchMock, createMock };
}

function mount(attributes: Record<string, string> = {}): SearchSelectLike {
  document.body.replaceChildren();
  const host = document.createElement("search-select") as SearchSelectLike;
  host.setAttribute("name", "playthrough");
  host.setAttribute("search-url", "/api/playthrough/search");
  host.setAttribute("prefetch", "20");
  host.setAttribute("create-url", "/api/playthrough/");
  host.setAttribute("csrf", "token");
  Object.entries(attributes).forEach(([key, value]) => host.setAttribute(key, value));
  host.innerHTML = `
    <div data-search-select-pills></div>
    <input data-search-select-search />
    <div data-search-select-options>
      <div data-search-select-no-results class="hidden">No results</div>
      <div data-search-select-create hidden role="option" aria-selected="false">
        <span data-label></span>
      </div>
    </div>
    <template data-search-select-template="row"><div
      data-search-select-option role="option" aria-selected="false"
    ><span data-label></span></div></template>
  `;
  document.body.appendChild(host);
  return host;
}

function searchBox(host: HTMLElement): HTMLInputElement {
  return host.querySelector<HTMLInputElement>("[data-search-select-search]")!;
}

async function type(host: HTMLElement, text: string): Promise<void> {
  const box = searchBox(host);
  box.focus();
  box.value = text;
  box.dispatchEvent(new Event("input", { bubbles: true }));
  await vi.waitFor(() => expect(box.value).toBe(text));
  //: The row waits for the answer, so let the fetch settle.
  await new Promise(resolve => setTimeout(resolve, 150));
}

function createRow(host: HTMLElement): HTMLElement {
  return host.querySelector<HTMLElement>(CREATE_ROW)!;
}

function pressEnter(host: HTMLElement): void {
  searchBox(host).dispatchEvent(
    new KeyboardEvent("keydown", { key: "Enter", bubbles: true })
  );
}

describe("<search-select> create row (#1080)", () => {
  beforeEach(() => document.body.replaceChildren());
  afterEach(() => vi.unstubAllGlobals());

  it("offers the row when no loaded label equals the query", async () => {
    stubEndpoints([]);
    const host = mount();

    await type(host, "New Game Plus");

    expect(createRow(host).hidden).toBe(false);
    expect(createRow(host).textContent).toContain("New Game Plus");
  });

  it("offers the row for a query a longer label holds", async () => {
    stubEndpoints([{ value: "p4", label: "PlayStation 4", data: {} }]);
    const host = mount();

    await type(host, "PlayStation");

    expect(createRow(host).hidden).toBe(false);
  });

  it("offers no row when a label equals the query, case ignored", async () => {
    stubEndpoints([{ value: "p4", label: "PlayStation 4", data: {} }]);
    const host = mount();

    await type(host, "playstation 4");

    expect(createRow(host).hidden).toBe(true);
  });

  it("offers no row for a blank query", async () => {
    stubEndpoints([]);
    const host = mount();

    await type(host, "   ");

    expect(createRow(host).hidden).toBe(true);
  });

  it("offers no row without a create URL", async () => {
    stubEndpoints([]);
    const host = mount({ "create-url": "" });

    await type(host, "New Game Plus");

    expect(createRow(host).hidden).toBe(true);
  });

  it("offers no row in filter mode", async () => {
    stubEndpoints([]);
    const host = mount({ "filter-mode": "true" });

    await type(host, "New Game Plus");

    expect(createRow(host).hidden).toBe(true);
  });

  it("replaces the no-results node", async () => {
    stubEndpoints([]);
    const host = mount();

    await type(host, "New Game Plus");

    const noResults = host.querySelector<HTMLElement>("[data-search-select-no-results]")!;
    expect(noResults.classList.contains("hidden")).toBe(true);
    expect(createRow(host).hidden).toBe(false);
  });

  it("posts the name on Enter and selects what comes back", async () => {
    const { createMock } = stubEndpoints([]);
    const host = mount();
    await type(host, "New Game Plus");

    pressEnter(host);

    await vi.waitFor(() => expect(createMock).toHaveBeenCalledTimes(1));
    const [url, options] = createMock.mock.calls[0];
    expect(String(url)).toBe("/api/playthrough/");
    expect(options?.method).toBe("POST");
    expect(JSON.parse(String(options?.body))).toEqual({ name: "New Game Plus" });
    await vi.waitFor(() =>
      expect(
        host.querySelector<HTMLInputElement>(
          '[data-search-select-pills] input[type="hidden"]'
        )?.value
      ).toBe("new-key")
    );
    expect(searchBox(host).value).toBe("New Game Plus");
  });

  it("posts the params the picker states", async () => {
    const { createMock } = stubEndpoints([]);
    const host = mount({ params: JSON.stringify({ game_id: { value: "g1" } }) });
    await type(host, "New Game Plus");

    pressEnter(host);

    await vi.waitFor(() => expect(createMock).toHaveBeenCalled());
    const [, options] = createMock.mock.calls[0];
    expect(JSON.parse(String(options?.body))).toEqual({
      name: "New Game Plus",
      game_id: "g1",
    });
  });

  it("posts nothing on a second Enter while the first is in flight", async () => {
    const createMock = vi.fn(() => new Promise<Response>(() => {}));
    vi.stubGlobal("fetch", vi.fn(() =>
      Promise.resolve({ ok: true, json: () => Promise.resolve([]) } as Response)
    ));
    window.fetchWithHtmxTriggers =
      createMock as unknown as typeof window.fetchWithHtmxTriggers;
    const host = mount();
    await type(host, "New Game Plus");

    pressEnter(host);
    pressEnter(host);

    await vi.waitFor(() => expect(createMock).toHaveBeenCalledTimes(1));
  });

  it("takes the new label rather than inserting a key the panel holds", async () => {
    const { createMock } = stubEndpoints([
      { value: "new-key", label: "Playthrough 1", data: {} },
    ]);
    const host = mount();
    await type(host, "New Game Plus");

    pressEnter(host);

    await vi.waitFor(() => expect(createMock).toHaveBeenCalled());
    await vi.waitFor(() =>
      expect(
        host
          .querySelector('[data-search-select-option][data-value="new-key"]')
          ?.getAttribute("data-label")
      ).toBe("New Game Plus")
    );
    expect(
      host.querySelectorAll('[data-search-select-option][data-value="new-key"]')
    ).toHaveLength(1);
  });

  it("keeps the query and selects nothing when the creation is refused", async () => {
    vi.stubGlobal("fetch", vi.fn(() =>
      Promise.resolve({ ok: true, json: () => Promise.resolve([]) } as Response)
    ));
    const refused = vi.fn(() =>
      Promise.resolve({ ok: false, status: 422, json: () => Promise.resolve({}) } as Response)
    );
    window.fetchWithHtmxTriggers =
      refused as unknown as typeof window.fetchWithHtmxTriggers;
    const host = mount();
    await type(host, "New Game Plus");

    pressEnter(host);

    await vi.waitFor(() => expect(refused).toHaveBeenCalled());
    expect(searchBox(host).value).toBe("New Game Plus");
    expect(
      host.querySelector('[data-search-select-pills] input[type="hidden"]')
    ).toBeNull();
  });

  it("opens a panel holding only the create row", async () => {
    stubEndpoints([]);
    const host = mount();
    const panel = host.querySelector<HTMLElement>("[data-search-select-options]")!;

    await type(host, "New Game Plus");

    expect(panel.classList.contains("hidden")).toBe(false);
  });
});
