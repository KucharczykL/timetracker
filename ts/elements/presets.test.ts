// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchPresetNames, getCsrfToken, savePreset, wirePresetDelete } from "./presets.js";

const API_URL = "/api/presets/";

function clearCsrfCookie(): void {
  document.cookie = "csrftoken=; expires=Thu, 01 Jan 1970 00:00:00 GMT";
}

function flushPromises(): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, 0));
}

// A picker as LoadPresetDropdown renders one: the [data-preset-picker] wrapper
// hosting a search-select. The widget is deliberately NOT the real custom
// element (this suite never imports search-select.js), so refetchOptions is a
// plain stub the delete flow duck-types onto.
function mountPicker() {
  document.body.innerHTML = "";
  const root = document.createElement("div");
  const picker = document.createElement("div");
  picker.setAttribute("data-preset-picker", "");
  const widget = document.createElement("search-select") as HTMLElement & {
    refetchOptions: ReturnType<typeof vi.fn>;
  };
  widget.refetchOptions = vi.fn();
  picker.appendChild(widget);
  root.appendChild(picker);
  document.body.appendChild(root);
  const dispose = wirePresetDelete(root, API_URL);
  return { root, picker, widget, dispose };
}

function dispatchDelete(widget: HTMLElement, value = "42", label = "My preset"): void {
  widget.dispatchEvent(
    new CustomEvent("search-select:action", {
      bubbles: true,
      detail: { name: "preset", action: "delete", option: { value, label, data: {} } },
    }),
  );
}

function stubToast(): ReturnType<typeof vi.fn> {
  const toastStub = vi.fn();
  (window as unknown as Record<string, unknown>).toast = toastStub;
  return toastStub;
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

describe("wirePresetDelete", () => {
  function stubDeleteFetch(status = 204): ReturnType<typeof vi.fn> {
    document.cookie = "csrftoken=testtoken";
    vi.stubGlobal("confirm", vi.fn(() => true));
    const fetchStub = vi.fn(() => Promise.resolve(new Response(null, { status })));
    vi.stubGlobal("fetch", fetchStub);
    return fetchStub;
  }

  it("confirms, DELETEs base+id with X-CSRFToken, and refetches the widget", async () => {
    const fetchStub = stubDeleteFetch();
    const toastStub = stubToast();
    const { widget } = mountPicker();

    dispatchDelete(widget);
    await flushPromises();

    expect(fetchStub).toHaveBeenCalledOnce();
    const [url, options] = fetchStub.mock.calls[0] as unknown as [
      string,
      RequestInit & { headers: Record<string, string> },
    ];
    expect(url).toBe("/api/presets/42");
    expect(options.method).toBe("DELETE");
    expect(options.headers["X-CSRFToken"]).toBe("testtoken");
    expect(widget.refetchOptions).toHaveBeenCalledOnce();
    expect(toastStub).not.toHaveBeenCalled();
  });

  it("does not fetch when the confirm is declined", () => {
    const fetchStub = stubDeleteFetch();
    vi.stubGlobal("confirm", vi.fn(() => false));
    const { widget } = mountPicker();

    dispatchDelete(widget);

    expect(fetchStub).not.toHaveBeenCalled();
  });

  it("names the preset in the confirm prompt", () => {
    stubDeleteFetch();
    const confirmStub = vi.fn(() => false);
    vi.stubGlobal("confirm", confirmStub);
    const { widget } = mountPicker();

    dispatchDelete(widget, "7", "Backlog");

    expect(confirmStub).toHaveBeenCalledWith('Delete preset "Backlog"?');
  });

  it("toasts on a rejection but still refetches (stale 404 self-corrects)", async () => {
    stubDeleteFetch(404);
    const toastStub = stubToast();
    const { widget } = mountPicker();

    dispatchDelete(widget);
    await flushPromises();

    expect(toastStub).toHaveBeenCalledWith("Failed to delete preset.", "error");
    expect(widget.refetchOptions).toHaveBeenCalledOnce();
  });

  it("ignores actions from outside a [data-preset-picker] wrapper", () => {
    const fetchStub = stubDeleteFetch();
    document.body.innerHTML = "";
    const root = document.createElement("div");
    const stray = document.createElement("search-select");
    root.appendChild(stray);
    document.body.appendChild(root);
    wirePresetDelete(root, API_URL);

    dispatchDelete(stray);

    expect(fetchStub).not.toHaveBeenCalled();
  });

  it("ignores non-delete actions", () => {
    const fetchStub = stubDeleteFetch();
    const { widget } = mountPicker();

    widget.dispatchEvent(
      new CustomEvent("search-select:action", {
        bubbles: true,
        detail: { name: "preset", action: "include", option: { value: "1", label: "x", data: {} } },
      }),
    );

    expect(fetchStub).not.toHaveBeenCalled();
  });

  it("dispose stops listening — a re-wire never stacks a second confirm", () => {
    const fetchStub = stubDeleteFetch();
    const confirmStub = vi.fn(() => true);
    vi.stubGlobal("confirm", confirmStub);
    const { root, widget, dispose } = mountPicker();

    // Simulate a disconnect/reconnect cycle: dispose the old wiring first.
    dispose();
    wirePresetDelete(root, API_URL);
    dispatchDelete(widget);

    expect(confirmStub).toHaveBeenCalledOnce();
    expect(fetchStub).toHaveBeenCalledOnce();
  });
});

describe("savePreset", () => {
  it("POSTs a JSON body with Content-Type and X-CSRFToken and toasts 'saved' on 201", async () => {
    document.cookie = "csrftoken=testtoken";
    const fetchStub = vi.fn(() => Promise.resolve(new Response(null, { status: 201 })));
    vi.stubGlobal("fetch", fetchStub);
    const toastStub = stubToast();

    const filter = { search: { value: "mario", modifier: "INCLUDES" } };
    const response = await savePreset(API_URL, { name: "My preset", mode: "games", filter });

    expect(response?.ok).toBe(true);
    const [url, options] = fetchStub.mock.calls[0] as unknown as [
      string,
      RequestInit & { headers: Record<string, string>; body: string },
    ];
    expect(url).toBe(API_URL);
    expect(options.method).toBe("POST");
    expect(options.headers["Content-Type"]).toBe("application/json");
    expect(options.headers["X-CSRFToken"]).toBe("testtoken");
    expect(JSON.parse(options.body)).toEqual({ name: "My preset", mode: "games", filter });
    expect(toastStub).toHaveBeenCalledWith('Filter preset "My preset" saved.', "success");
  });

  it("forwards the sort in the POST body when present", async () => {
    const fetchStub = vi.fn(() => Promise.resolve(new Response(null, { status: 201 })));
    vi.stubGlobal("fetch", fetchStub);
    stubToast();

    const filter = { search: { value: "mario", modifier: "INCLUDES" } };
    await savePreset(API_URL, { name: "P", mode: "games", filter, sort: "-playtime,name" });

    const [, options] = fetchStub.mock.calls[0] as unknown as [
      string,
      RequestInit & { body: string },
    ];
    expect(JSON.parse(options.body)).toEqual({
      name: "P",
      mode: "games",
      filter,
      sort: "-playtime,name",
    });
  });

  it("toasts 'updated' on a 200 overwrite", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response(null, { status: 200 }))));
    const toastStub = stubToast();

    await savePreset(API_URL, { name: "Backlog", mode: "games", filter: {} });

    expect(toastStub).toHaveBeenCalledWith('Filter preset "Backlog" updated.', "success");
  });

  it("toasts the server's detail on a rejection", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve(
          new Response(JSON.stringify({ detail: "Unknown preset mode 'bogus'." }), {
            status: 400,
          }),
        ),
      ),
    );
    const toastStub = stubToast();

    const response = await savePreset(API_URL, { name: "X", mode: "bogus", filter: {} });

    expect(response?.ok).toBe(false);
    expect(toastStub).toHaveBeenCalledWith("Unknown preset mode 'bogus'.", "error");
  });

  it("resolves null and toasts on a transport failure", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new Error("network down"))));
    const toastStub = stubToast();
    vi.spyOn(console, "error").mockImplementation(() => {});

    const response = await savePreset(API_URL, { name: "My preset", mode: "games", filter: {} });

    expect(response).toBeNull();
    expect(toastStub).toHaveBeenCalledWith("Failed to save preset.", "error");
  });
});

describe("fetchPresetNames", () => {
  it("fetches unbounded (limit=0) for the mode and returns trimmed labels", async () => {
    const fetchStub = vi.fn(() =>
      Promise.resolve(
        new Response(
          JSON.stringify([
            { value: 1, label: " Backlog ", data: { filter: "{}" } },
            { value: 2, label: "Finished", data: { filter: "{}" } },
          ]),
        ),
      ),
    );
    vi.stubGlobal("fetch", fetchStub);

    const names = await fetchPresetNames(API_URL, "sessions");

    const requested = new URL(
      (fetchStub.mock.calls[0] as unknown as [string])[0],
      "http://localhost",
    );
    expect(requested.pathname).toBe(API_URL);
    expect(requested.searchParams.get("mode")).toBe("sessions");
    expect(requested.searchParams.get("limit")).toBe("0"); // never truncate — #212
    expect(names).toEqual(new Set(["Backlog", "Finished"]));
  });

  it("degrades to an empty set on failure", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new Error("network down"))));
    vi.spyOn(console, "error").mockImplementation(() => {});

    expect(await fetchPresetNames(API_URL, "games")).toEqual(new Set());
  });
});
