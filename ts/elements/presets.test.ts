// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { getCsrfToken, savePreset, setupPresetDropdown } from "./presets.js";

const LIST_URL = "/tracker/filter/presets/list";

function clearCsrfCookie(): void {
  document.cookie = "csrftoken=; expires=Thu, 01 Jan 1970 00:00:00 GMT";
}

function flushPromises(): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, 0));
}

interface MountOptions {
  listUrl?: string;
  onPick?: (filter: Record<string, unknown>) => void;
  onListRendered?: () => void;
}

function mount(options: MountOptions = {}) {
  document.body.innerHTML = "";
  const root = document.createElement("div");
  const dropdown = document.createElement("div");
  dropdown.setAttribute("data-preset-dropdown", "");
  root.appendChild(dropdown);
  document.body.appendChild(root);
  const controller = setupPresetDropdown({
    root,
    dropdownSelector: "[data-preset-dropdown]",
    listUrl: options.listUrl ?? LIST_URL,
    mode: "games",
    onPick: options.onPick,
    onListRendered: options.onListRendered,
  });
  return { root, dropdown, controller };
}

// A preset row shaped like the list_presets fragment: the delete <span> is
// nested INSIDE the preset <a href>.
function injectPresetRow(dropdown: HTMLElement, filter: Record<string, unknown>): void {
  dropdown.innerHTML = `
    <ul>
      <li>
        <a href="/tracker/game/list?filter=${encodeURIComponent(JSON.stringify(filter))}">
          My preset
          <span data-delete-preset="" href="/tracker/filter/presets/delete/42">x</span>
        </a>
      </li>
    </ul>`;
}

function stubListFetch(html = "<ul><li>fresh</li></ul>"): ReturnType<typeof vi.fn> {
  const fetchStub = vi.fn(() => Promise.resolve(new Response(html)));
  vi.stubGlobal("fetch", fetchStub);
  return fetchStub;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  clearCsrfCookie();
});

describe("getCsrfToken", () => {
  it("reads and URL-decodes the csrftoken cookie", () => {
    document.cookie = "csrftoken=abc%3D123";
    expect(getCsrfToken()).toBe("abc=123");
  });

  it("falls back to the hidden csrfmiddlewaretoken input", () => {
    clearCsrfCookie();
    document.body.innerHTML = '<input name="csrfmiddlewaretoken" value="hidden-token">';
    expect(getCsrfToken()).toBe("hidden-token");
  });
});

describe("refresh", () => {
  it("appends mode only when the list URL does not already carry one", async () => {
    const fetchStub = stubListFetch();
    const { controller } = mount();
    await controller.refresh();
    const requested = new URL(fetchStub.mock.calls[0][0] as string);
    expect(requested.pathname).toBe(LIST_URL);
    expect(requested.searchParams.get("mode")).toBe("games");

    fetchStub.mockClear();
    const { controller: second } = mount({ listUrl: `${LIST_URL}?mode=devices` });
    await second.refresh();
    const kept = new URL(fetchStub.mock.calls[0][0] as string);
    expect(kept.searchParams.get("mode")).toBe("devices");
  });

  it("renders the fragment and calls onListRendered", async () => {
    stubListFetch("<ul><li>row</li></ul>");
    const onListRendered = vi.fn();
    const { dropdown, controller } = mount({ onListRendered });
    await controller.refresh();
    expect(dropdown.innerHTML).toBe("<ul><li>row</li></ul>");
    expect(onListRendered).toHaveBeenCalledOnce();
  });

  it("no-ops on an empty list URL", async () => {
    const fetchStub = stubListFetch();
    const { controller } = mount({ listUrl: "" });
    await controller.refresh();
    expect(fetchStub).not.toHaveBeenCalled();
  });

  it("renders a placeholder on failure without rejecting", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new Error("network down"))));
    vi.spyOn(console, "error").mockImplementation(() => {});
    const { dropdown, controller } = mount();
    await expect(controller.refresh()).resolves.toBeUndefined();
    expect(dropdown.innerHTML).toContain("Presets unavailable");
  });
});

describe("delete", () => {
  function stubDeleteEnvironment(deleteResponse: unknown = new Response(null, { status: 200 })) {
    document.cookie = "csrftoken=testtoken";
    const deleteStub = vi.fn(() => Promise.resolve(deleteResponse));
    (window as unknown as Record<string, unknown>).fetchWithHtmxTriggers = deleteStub;
    const toastStub = vi.fn();
    (window as unknown as Record<string, unknown>).toast = toastStub;
    vi.stubGlobal("confirm", vi.fn(() => true));
    const listStub = stubListFetch();
    return { deleteStub, toastStub, listStub };
  }

  it("sends DELETE with X-CSRFToken and refetches the list", async () => {
    const { deleteStub, toastStub, listStub } = stubDeleteEnvironment();
    const { dropdown } = mount();
    injectPresetRow(dropdown, {});

    (dropdown.querySelector("[data-delete-preset]") as HTMLElement).click();
    await flushPromises();

    expect(deleteStub).toHaveBeenCalledOnce();
    const [url, options] = deleteStub.mock.calls[0] as unknown as [
      string,
      RequestInit & { headers: Record<string, string> },
    ];
    expect(url).toBe("/tracker/filter/presets/delete/42");
    expect(options.method).toBe("DELETE");
    expect(options.headers["X-CSRFToken"]).toBe("testtoken");
    expect(listStub).toHaveBeenCalledOnce();
    expect(toastStub).not.toHaveBeenCalled();
  });

  it("does not fetch when the confirm is declined", () => {
    const { deleteStub } = stubDeleteEnvironment();
    vi.stubGlobal("confirm", vi.fn(() => false));
    const { dropdown } = mount();
    injectPresetRow(dropdown, {});

    (dropdown.querySelector("[data-delete-preset]") as HTMLElement).click();

    expect(deleteStub).not.toHaveBeenCalled();
  });

  it("toasts on a server rejection (no Django message fires for those)", async () => {
    const { toastStub, listStub } = stubDeleteEnvironment(new Response(null, { status: 404 }));
    const { dropdown } = mount();
    injectPresetRow(dropdown, {});

    (dropdown.querySelector("[data-delete-preset]") as HTMLElement).click();
    await flushPromises();

    expect(toastStub).toHaveBeenCalledWith("Failed to delete preset.", "error");
    expect(listStub).toHaveBeenCalledOnce(); // still refetched — self-correcting
  });

  it("wins over the pick branch for a delete span nested inside the anchor", async () => {
    const { deleteStub } = stubDeleteEnvironment();
    const onPick = vi.fn();
    const { dropdown } = mount({ onPick });
    injectPresetRow(dropdown, {});

    (dropdown.querySelector("[data-delete-preset]") as HTMLElement).click();
    await flushPromises();

    expect(deleteStub).toHaveBeenCalledOnce();
    expect(onPick).not.toHaveBeenCalled();
  });

  it("does not stack listeners when setup runs twice on the same root", () => {
    const { deleteStub } = stubDeleteEnvironment();
    const confirmStub = vi.fn(() => true);
    vi.stubGlobal("confirm", confirmStub);
    const { root, dropdown } = mount();
    setupPresetDropdown({
      root,
      dropdownSelector: "[data-preset-dropdown]",
      listUrl: LIST_URL,
      mode: "games",
    });
    injectPresetRow(dropdown, {});

    (dropdown.querySelector("[data-delete-preset]") as HTMLElement).click();

    expect(confirmStub).toHaveBeenCalledOnce();
    expect(deleteStub).toHaveBeenCalledOnce();
  });
});

describe("pick", () => {
  it("parses the anchor's ?filter= JSON into onPick and prevents navigation", () => {
    const onPick = vi.fn();
    const { dropdown } = mount({ onPick });
    const filter = { AND: [{ status: { modifier: "EQUALS", value: "f" } }] };
    injectPresetRow(dropdown, filter);

    const anchor = dropdown.querySelector("a[href]") as HTMLAnchorElement;
    const event = new MouseEvent("click", { bubbles: true, cancelable: true });
    anchor.dispatchEvent(event);

    expect(onPick).toHaveBeenCalledWith(filter);
    expect(event.defaultPrevented).toBe(true);
  });

  it("leaves anchors alone when no onPick is given (native navigation)", () => {
    const { dropdown } = mount();
    injectPresetRow(dropdown, {});

    const anchor = dropdown.querySelector("a[href]") as HTMLAnchorElement;
    const event = new MouseEvent("click", { bubbles: true, cancelable: true });
    anchor.dispatchEvent(event);

    expect(event.defaultPrevented).toBe(false);
  });

  it("toasts and logs 'preset load failed' when onPick throws", () => {
    const toastStub = vi.fn();
    (window as unknown as Record<string, unknown>).toast = toastStub;
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
    const onPick = vi.fn(() => {
      throw new Error("bad filter shape");
    });
    const { dropdown } = mount({ onPick });
    injectPresetRow(dropdown, {});

    (dropdown.querySelector("a[href]") as HTMLElement).click();

    expect(toastStub).toHaveBeenCalledWith("Preset is not a valid filter.", "error");
    // The builder e2e greps the console for this substring as its crash guard.
    expect(String(consoleError.mock.calls[0][0])).toContain("preset load failed");
  });
});

describe("savePreset", () => {
  it("POSTs an urlencoded body with Content-Type and X-CSRFToken", async () => {
    document.cookie = "csrftoken=testtoken";
    const fetchStub = vi.fn(() => Promise.resolve(new Response(null, { status: 201 })));
    (window as unknown as Record<string, unknown>).fetchWithHtmxTriggers = fetchStub;

    const filter = { search: { value: "mario", modifier: "INCLUDES" } };
    const response = await savePreset("/tracker/filter/presets/save", {
      name: "My preset",
      mode: "games",
      filter,
    });

    expect(response?.ok).toBe(true);
    const [url, options] = fetchStub.mock.calls[0] as unknown as [
      string,
      RequestInit & { headers: Record<string, string>; body: string },
    ];
    expect(url).toBe("/tracker/filter/presets/save");
    expect(options.method).toBe("POST");
    expect(options.headers["Content-Type"]).toBe("application/x-www-form-urlencoded");
    expect(options.headers["X-CSRFToken"]).toBe("testtoken");
    const body = new URLSearchParams(options.body);
    expect(body.get("name")).toBe("My preset");
    expect(body.get("mode")).toBe("games");
    expect(body.get("filter")).toBe(JSON.stringify(filter));
  });

  it("resolves null and toasts on a transport failure", async () => {
    const fetchStub = vi.fn(() => Promise.reject(new Error("network down")));
    (window as unknown as Record<string, unknown>).fetchWithHtmxTriggers = fetchStub;
    const toastStub = vi.fn();
    (window as unknown as Record<string, unknown>).toast = toastStub;
    vi.spyOn(console, "error").mockImplementation(() => {});

    const response = await savePreset("/tracker/filter/presets/save", {
      name: "My preset",
      mode: "games",
      filter: {},
    });

    expect(response).toBeNull();
    expect(toastStub).toHaveBeenCalledWith("Failed to save preset.", "error");
  });
});
