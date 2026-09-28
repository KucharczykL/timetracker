// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import "./preset-panel.js";
import {
  PRESET_LOAD_EVENT,
  PRESET_SAVE_EVENT,
  PresetSaveAnswer,
  PresetSaveRequest,
  PresetState,
} from "./presets.js";

const API_URL = "/api/presets/";
const PRESET_UUID = "018f5e66-e800-7000-8000-000000000001";
const HOST_STATE: PresetState = {
  filter: { status: { modifier: "INCLUDES", value: ["p"] } },
  sort: "-playtime",
  perPage: "100",
};

interface WidgetStub extends HTMLElement {
  refetchOptions: ReturnType<typeof vi.fn>;
  clearSelection: ReturnType<typeof vi.fn>;
}

// The panel as PresetPanel renders it, inside a <drop-down> stand-in and a
// host that answers the save with `answer`. The widget is a stub: this suite
// never imports search-select.js.
function mount(
  answer: PresetSaveAnswer | null = { kind: "state", state: HOST_STATE },
  answersLoad = true,
) {
  document.body.innerHTML = `
    <form id="host">
      <drop-down>
        <preset-panel preset-api-url="${API_URL}" mode="games" data-preset-picker>
          <search-select name="preset"></search-select>
        </preset-panel>
      </drop-down>
    </form>`;
  const host = document.getElementById("host") as HTMLFormElement;
  if (answer) {
    host.addEventListener(PRESET_SAVE_EVENT, (event) => {
      (event as CustomEvent<PresetSaveRequest>).detail.answerWith(answer);
    });
  }
  if (answersLoad) host.addEventListener(PRESET_LOAD_EVENT, (event) => event.preventDefault());
  // An un-upgraded stand-in; the test gives it the one method used.
  const dropDown = host.querySelector("drop-down") as unknown as HTMLElement & {
    close: ReturnType<typeof vi.fn>;
  };
  dropDown.close = vi.fn();
  const widget = host.querySelector("search-select") as WidgetStub;
  widget.refetchOptions = vi.fn();
  widget.clearSelection = vi.fn();
  return { host, dropDown, widget };
}

// The widget's create row, as a search-select with create-event emits it.
function create(widget: HTMLElement, name: string, replaces = false): void {
  widget.dispatchEvent(
    new CustomEvent("search-select:create", { bubbles: true, detail: { name, replaces } }),
  );
}

function pick(widget: HTMLElement, data: Record<string, string>): void {
  widget.dispatchEvent(
    new CustomEvent("search-select:change", {
      bubbles: true,
      detail: { last: { value: PRESET_UUID, label: "Finished", data } },
    }),
  );
}

function stubFetch(response: () => Response): ReturnType<typeof vi.fn> {
  const fetchStub = vi.fn(() => Promise.resolve(response()));
  vi.stubGlobal("fetch", fetchStub);
  return fetchStub;
}

function postedBody(fetchStub: ReturnType<typeof vi.fn>): Record<string, unknown> {
  const [, options] = fetchStub.mock.calls[0] as unknown as [string, RequestInit];
  return JSON.parse(String(options.body)) as Record<string, unknown>;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  document.cookie = "csrftoken=; expires=Thu, 01 Jan 1970 00:00:00 GMT";
});

describe("<preset-panel>", () => {
  it("a pick announces the preset, clears the pick and closes", () => {
    const { host, dropDown, widget } = mount();
    const loaded = vi.fn();
    host.addEventListener(PRESET_LOAD_EVENT, (event) =>
      loaded((event as CustomEvent<PresetState>).detail),
    );
    pick(widget, { filter: '{"a": 1}', sort: "name", per_page: "50" });
    expect(loaded).toHaveBeenCalledWith({ filter: { a: 1 }, sort: "name", perPage: "50" });
    expect(widget.clearSelection).toHaveBeenCalledOnce();
    expect(dropDown.close).toHaveBeenCalledOnce();
  });

  it("a pick with no sort or per_page announces them empty", () => {
    const { host, widget } = mount();
    const loaded = vi.fn();
    host.addEventListener(PRESET_LOAD_EVENT, (event) =>
      loaded((event as CustomEvent<PresetState>).detail),
    );
    pick(widget, {});
    expect(loaded).toHaveBeenCalledWith({ filter: {}, sort: "", perPage: "" });
  });

  it("bad preset JSON toasts, logs the crash-guard line and still closes", () => {
    const { host, dropDown, widget } = mount();
    const loaded = vi.fn();
    host.addEventListener(PRESET_LOAD_EVENT, loaded);
    vi.stubGlobal("toast", vi.fn());
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
    pick(widget, { filter: "{not json" });
    expect(loaded).not.toHaveBeenCalled();
    expect(window.toast).toHaveBeenCalledWith("Preset is not a valid filter.", "error");
    expect(
      consoleError.mock.calls.some((call) => String(call[0]).includes("preset load failed")),
    ).toBe(true);
    expect(dropDown.close).toHaveBeenCalledOnce();
  });

  it("a create posts the host's state under the typed name", () => {
    const { widget } = mount();
    document.cookie = "csrftoken=testtoken";
    vi.stubGlobal("toast", vi.fn());
    const fetchStub = stubFetch(() => new Response(null, { status: 201 }));
    create(widget, "My preset");
    const [url, options] = fetchStub.mock.calls[0] as unknown as [
      string,
      RequestInit & { headers: Record<string, string> },
    ];
    expect(url).toBe(API_URL);
    expect(options.method).toBe("POST");
    expect(options.headers["X-CSRFToken"]).toBe("testtoken");
    expect(postedBody(fetchStub)).toEqual({
      name: "My preset",
      mode: "games",
      filter: HOST_STATE.filter,
      sort: "-playtime",
      per_page: "100",
    });
  });

  it("an overwrite posts the same way; the API updates the named preset", () => {
    const { widget } = mount();
    vi.stubGlobal("toast", vi.fn());
    const fetchStub = stubFetch(() => new Response(null, { status: 200 }));
    create(widget, "Finished", true);
    expect(postedBody(fetchStub).name).toBe("Finished");
  });

  it("the create event stops at the panel", () => {
    const { widget } = mount();
    vi.stubGlobal("toast", vi.fn());
    stubFetch(() => new Response(null, { status: 201 }));
    const outer = vi.fn();
    document.body.addEventListener("search-select:create", outer);
    create(widget, "Mine");
    document.body.removeEventListener("search-select:create", outer);
    expect(outer).not.toHaveBeenCalled();
  });

  it("a host's refusal is shown and nothing posts", () => {
    const { widget } = mount({ kind: "refused", sentence: "Finish it first." });
    vi.stubGlobal("toast", vi.fn());
    const fetchStub = stubFetch(() => new Response());
    create(widget, "Half");
    expect(fetchStub).not.toHaveBeenCalled();
    expect(window.toast).toHaveBeenCalledWith("Finish it first.", "error");
  });

  it("no host answering saves nothing", () => {
    const { widget } = mount(null);
    vi.stubGlobal("toast", vi.fn());
    vi.spyOn(console, "error").mockImplementation(() => {});
    // The client-error report posts on its own; no preset post may follow.
    const fetchStub = stubFetch(() => new Response());
    create(widget, "Orphan");
    const presetPosts = fetchStub.mock.calls.filter((call) => call[0] === API_URL);
    expect(presetPosts).toEqual([]);
    expect(window.toast).toHaveBeenCalledWith(expect.stringContaining("reload"), "error");
  });

  it("an unanswered load says so", () => {
    const { widget } = mount(undefined, false);
    vi.stubGlobal("toast", vi.fn());
    vi.spyOn(console, "error").mockImplementation(() => {});
    pick(widget, { filter: "{}" });
    expect(window.toast).toHaveBeenCalledWith(expect.stringContaining("reload"), "error");
  });

  it("a preset that is not an object is not a valid filter", () => {
    const { host, widget } = mount();
    const loaded = vi.fn();
    host.addEventListener(PRESET_LOAD_EVENT, loaded);
    vi.stubGlobal("toast", vi.fn());
    vi.spyOn(console, "error").mockImplementation(() => {});
    pick(widget, { filter: "null" });
    expect(loaded).not.toHaveBeenCalled();
    expect(window.toast).toHaveBeenCalledWith("Preset is not a valid filter.", "error");
  });

  it("a saved preset refetches the list, which empties the box", async () => {
    const { widget } = mount();
    vi.stubGlobal("toast", vi.fn());
    stubFetch(() => new Response(null, { status: 201 }));
    create(widget, "Mine");
    await vi.waitFor(() => expect(widget.refetchOptions).toHaveBeenCalledOnce());
  });

  it("a rejected save keeps the box and the list", async () => {
    const { widget } = mount();
    vi.stubGlobal("toast", vi.fn());
    stubFetch(() => new Response(JSON.stringify({ detail: [{ msg: "bad" }] }), { status: 422 }));
    create(widget, "Mine");
    await vi.waitFor(() =>
      expect(window.toast).toHaveBeenCalledWith("Failed to save preset.", "error"),
    );
    expect(widget.refetchOptions).not.toHaveBeenCalled();
  });

  it("the remove action confirms, removes and refetches", async () => {
    const { widget } = mount();
    vi.stubGlobal("confirm", vi.fn(() => true));
    vi.stubGlobal("toast", vi.fn());
    const fetchStub = stubFetch(
      () => new Response(JSON.stringify({ restore_url: "/preset/x/restore" }), { status: 200 }),
    );
    widget.dispatchEvent(
      new CustomEvent("search-select:action", {
        bubbles: true,
        detail: {
          name: "preset",
          action: "delete",
          option: { value: PRESET_UUID, label: "Owned", data: {} },
        },
      }),
    );
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(fetchStub).toHaveBeenCalledWith(
      `${API_URL}${PRESET_UUID}`,
      expect.objectContaining({ method: "DELETE" }),
    );
    expect(widget.refetchOptions).toHaveBeenCalledOnce();
  });
});
