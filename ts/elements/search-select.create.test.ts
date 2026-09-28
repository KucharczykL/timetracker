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
      json: () => Promise.resolve({ value: "new-key", label: "New Game Plus" }),
    } as Response);
  });
  window.fetchWithEvents = createMock as unknown as typeof window.fetchWithEvents;
  return { searchMock, createMock };
}

function mount(attributes: Record<string, string> = {}): SearchSelectLike {
  document.body.replaceChildren();
  const host = document.createElement("search-select") as SearchSelectLike;
  host.setAttribute("name", "playthrough");
  host.setAttribute("search-url", "/api/playthrough/search");
  host.setAttribute("prefetch", "20");
  host.setAttribute("create", "post");
  host.setAttribute("create-url", "/api/playthrough/");

  Object.entries(attributes).forEach(([key, value]) => host.setAttribute(key, value));
  host.innerHTML = `
    <div data-search-select-pills></div>
    <input data-search-select-search />
    <div data-search-select-options hidden>
      <div data-search-select-no-results class="hidden">No results</div>
      <div data-search-select-create hidden role="option" aria-selected="false">
        <span data-label></span>
      </div>
    </div>
    <template data-search-select-template="row"><div
      data-search-select-option role="option" aria-selected="false"
    ><span data-label></span></div></template>
  `;
  //: The token comes from the hosting form, as it does on a page.
  const form = document.createElement("form");
  form.innerHTML = '<input type="hidden" name="csrfmiddlewaretoken" value="token" />';
  form.appendChild(host);
  document.body.appendChild(form);
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
    const host = mount({ create: "" });

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
    expect((options?.headers as Record<string, string>)["X-CSRFToken"]).toBe("token");
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
    window.fetchWithEvents =
      createMock as unknown as typeof window.fetchWithEvents;
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
    window.fetchWithEvents =
      refused as unknown as typeof window.fetchWithEvents;
    const host = mount();
    await type(host, "New Game Plus");

    pressEnter(host);

    await vi.waitFor(() => expect(refused).toHaveBeenCalled());
    expect(searchBox(host).value).toBe("New Game Plus");
    expect(
      host.querySelector('[data-search-select-pills] input[type="hidden"]')
    ).toBeNull();
  });

  it("reports a POST that never lands", async () => {
    stubEndpoints([]);
    window.fetchWithEvents = (() =>
      Promise.reject(new Error("offline"))) as unknown as typeof window.fetchWithEvents;
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
    const host = mount();

    await type(host, "New Game Plus");
    pressEnter(host);
    await vi.waitFor(() =>
      expect(createRow(host).hasAttribute("aria-disabled")).toBe(false)
    );

    expect(
      consoleError.mock.calls.some(call =>
        String(call[0]).includes("search-select[create]")
      )
    ).toBe(true);
  });

  it("reports an answer that queues no sentence of its own", async () => {
    stubEndpoints([]);
    //: A schema refusal, which no middleware turns into a toast.
    window.fetchWithEvents = (() =>
      Promise.resolve({
        ok: false,
        status: 422,
        headers: new Headers(),
        json: () => Promise.resolve({ detail: "Field required" }),
      } as Response)) as unknown as typeof window.fetchWithEvents;
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
    const host = mount();

    await type(host, "New Game Plus");
    pressEnter(host);
    await vi.waitFor(() =>
      expect(createRow(host).hasAttribute("aria-disabled")).toBe(false)
    );

    expect(
      consoleError.mock.calls.some(call => String(call[0]).includes("422"))
    ).toBe(true);
  });

  it("reports nothing when the refusal queued its own sentence", async () => {
    stubEndpoints([]);
    window.fetchWithEvents = (() =>
      Promise.resolve({
        ok: false,
        status: 422,
        headers: new Headers({ "X-Events": "{}" }),
        json: () => Promise.resolve({ detail: "That name is taken." }),
      } as Response)) as unknown as typeof window.fetchWithEvents;
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
    consoleError.mockClear();
    const host = mount();

    await type(host, "New Game Plus");
    pressEnter(host);
    await vi.waitFor(() =>
      expect(createRow(host).hasAttribute("aria-disabled")).toBe(false)
    );

    expect(
      consoleError.mock.calls.some(call =>
        String(call[0]).includes("search-select[create]")
      )
    ).toBe(false);
  });

  it("opens a panel holding only the create row", async () => {
    stubEndpoints([]);
    const host = mount();
    const panel = host.querySelector<HTMLElement>("[data-search-select-options]")!;

    await type(host, "New Game Plus");

    expect(panel.hidden).toBe(false);
  });
});

describe("<search-select> create row its consumer commits", () => {
  beforeEach(() => document.body.replaceChildren());
  afterEach(() => vi.unstubAllGlobals());

  const byEvent = {
    create: "event",
    "create-verb": "Save",
    "replace-verb": "Overwrite",
  };

  function created(host: HTMLElement) {
    const heard = vi.fn();
    host.addEventListener("search-select:create", event =>
      heard((event as CustomEvent).detail)
    );
    return heard;
  }

  it("reads the consumer's verb and emits the name, posting nothing", async () => {
    const { createMock } = stubEndpoints([]);
    const host = mount(byEvent);
    const heard = created(host);

    await type(host, "Backlog");
    expect(createRow(host).textContent).toContain("Save “Backlog”");
    pressEnter(host);

    expect(heard).toHaveBeenCalledWith({ name: "Backlog", replaces: false });
    expect(createMock).not.toHaveBeenCalled();
  });

  it("reads the replace verb for a name a row holds exactly", async () => {
    stubEndpoints([{ value: "b", label: "Backlog", data: {} }]);
    const host = mount(byEvent);
    const heard = created(host);

    await type(host, "Backlog");
    expect(createRow(host).hidden).toBe(false);
    expect(createRow(host).textContent).toContain("Overwrite “Backlog”");
    createRow(host).click();

    expect(heard).toHaveBeenCalledWith({ name: "Backlog", replaces: true });
  });

  it("keeps case: a name differing in case is another name", async () => {
    stubEndpoints([{ value: "b", label: "Backlog", data: {} }]);
    const host = mount(byEvent);

    await type(host, "backlog");

    expect(createRow(host).textContent).toContain("Save “backlog”");
  });

  it("Enter picks a matching row before it saves", async () => {
    stubEndpoints([{ value: "b", label: "Backlog", data: {} }]);
    const host = mount(byEvent);
    const heard = created(host);
    const picked = vi.fn();
    host.addEventListener("search-select:change", picked);

    await type(host, "Backlog");
    pressEnter(host);

    expect(picked).toHaveBeenCalled();
    expect(heard).not.toHaveBeenCalled();
  });
});

describe("<search-select> create row that selects the typed text", () => {
  beforeEach(() => document.body.replaceChildren());
  afterEach(() => vi.unstubAllGlobals());

  const bySelect = { create: "select", "create-verb": "Use" };

  function held(host: HTMLElement): string | undefined {
    return host.querySelector<HTMLInputElement>('input[type="hidden"][name="playthrough"]')
      ?.value;
  }

  it("holds the typed text, posting nothing", async () => {
    const { createMock } = stubEndpoints([]);
    const host = mount(bySelect);

    await type(host, "  Retro  ");
    expect(createRow(host).textContent).toContain("Use “Retro”");
    pressEnter(host);

    expect(held(host)).toBe("Retro");
    expect(createMock).not.toHaveBeenCalled();
  });

  it("commits a typed draft when the form submits", async () => {
    stubEndpoints([]);
    const host = mount(bySelect);

    await type(host, "  Retro  ");
    //: jsdom builds a FormData without firing `formdata`.
    const formData = new FormData();
    host
      .closest("form")!
      .dispatchEvent(Object.assign(new Event("formdata"), { formData }));

    expect(formData.get("playthrough")).toBe("Retro");
  });

  it("replaces a held text with a new one", async () => {
    stubEndpoints([]);
    const host = mount(bySelect);
    await type(host, "Retro");
    pressEnter(host);
    const changed = vi.fn();
    host.addEventListener("search-select:change", changed);

    await type(host, "Home");
    pressEnter(host);

    expect(host.querySelectorAll('input[type="hidden"][name="playthrough"]')).toHaveLength(1);
    expect(held(host)).toBe("Home");
    expect(changed).toHaveBeenCalled();
  });

  it("offers no row for a text a row holds, case ignored", async () => {
    stubEndpoints([{ value: "Retro", label: "Retro", data: {} }]);
    const host = mount(bySelect);

    await type(host, "retro");

    expect(createRow(host).hidden).toBe(true);
  });
});

describe("<search-select> refetch", () => {
  beforeEach(() => document.body.replaceChildren());
  afterEach(() => vi.unstubAllGlobals());

  it("drops a debounced search for the old query", async () => {
    const { searchMock } = stubEndpoints([]);
    const host = mount({ create: "" }) as SearchSelectLike & {
      refetchOptions(): void;
    };
    const box = searchBox(host);
    box.focus();
    box.value = "stale";
    box.dispatchEvent(new Event("input", { bubbles: true }));
    host.refetchOptions();
    await new Promise(resolve => setTimeout(resolve, 600));

    const queries = searchMock.mock.calls.map(call =>
      new URL(String((call as unknown[])[0]), window.location.origin).searchParams.get("q")
    );
    expect(queries).not.toContain("stale");
    expect(box.value).toBe("");
  });
});

describe("<search-select> create modes", () => {
  it("refuses a post with no endpoint", () => {
    const errors: unknown[] = [];
    const listener = (event: ErrorEvent) => {
      errors.push(event.error);
      event.preventDefault();
    };
    window.addEventListener("error", listener);
    try {
      mount({ create: "post", "create-url": "" });
    } catch (error) {
      errors.push(error);
    } finally {
      window.removeEventListener("error", listener);
    }

    expect(String(errors[0])).toContain('create="post" names no create-url');
  });
});
