// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import "./preset-panel.js";
import {
  PRESET_LOAD_EVENT,
  PRESET_SAVE_EVENT,
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
function mount(answer: Partial<PresetSaveRequest> | null = { state: HOST_STATE }) {
  document.body.innerHTML = `
    <form id="host">
      <drop-down>
        <preset-panel api-url="${API_URL}" mode="games" data-preset-picker>
          <search-select name="preset"></search-select>
          <input type="text" data-preset-name>
          <button type="button" data-save-preset>Save</button>
          <p data-preset-name-warning hidden></p>
        </preset-panel>
      </drop-down>
    </form>`;
  const host = document.getElementById("host") as HTMLFormElement;
  if (answer) {
    host.addEventListener(PRESET_SAVE_EVENT, (event) => {
      Object.assign((event as CustomEvent<PresetSaveRequest>).detail, answer);
    });
  }
  const dropDown = host.querySelector("drop-down") as HTMLElement & {
    close: ReturnType<typeof vi.fn>;
  };
  dropDown.close = vi.fn();
  const widget = host.querySelector("search-select") as WidgetStub;
  widget.refetchOptions = vi.fn();
  widget.clearSelection = vi.fn();
  return {
    host,
    dropDown,
    widget,
    nameInput: host.querySelector<HTMLInputElement>("[data-preset-name]")!,
    saveButton: host.querySelector<HTMLButtonElement>("[data-save-preset]")!,
    hint: host.querySelector<HTMLElement>("[data-preset-name-warning]")!,
  };
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

  it("Save posts the host's state with X-CSRFToken", () => {
    const { nameInput, saveButton } = mount();
    document.cookie = "csrftoken=testtoken";
    vi.stubGlobal("toast", vi.fn());
    const fetchStub = stubFetch(() => new Response(null, { status: 201 }));
    nameInput.value = " My preset ";
    saveButton.click();
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

  it("Enter in the name box saves and does not submit the host form", () => {
    const { host, nameInput } = mount();
    vi.stubGlobal("toast", vi.fn());
    const fetchStub = stubFetch(() => new Response(null, { status: 201 }));
    const submitted = vi.fn();
    host.addEventListener("submit", submitted);
    nameInput.value = "Keyed";
    const enter = new KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true });
    nameInput.dispatchEvent(enter);
    expect(enter.defaultPrevented).toBe(true);
    expect(fetchStub).toHaveBeenCalledOnce();
  });

  it("a blank name does not post", () => {
    const { saveButton } = mount();
    vi.stubGlobal("toast", vi.fn());
    const fetchStub = stubFetch(() => new Response());
    saveButton.click();
    expect(fetchStub).not.toHaveBeenCalled();
    expect(window.toast).toHaveBeenCalledWith("Preset name is required.", "error");
  });

  it("a host's refusal is shown and nothing posts", () => {
    const { nameInput, saveButton } = mount({ refusal: "Finish it first." });
    vi.stubGlobal("toast", vi.fn());
    const fetchStub = stubFetch(() => new Response());
    nameInput.value = "Half";
    saveButton.click();
    expect(fetchStub).not.toHaveBeenCalled();
    expect(window.toast).toHaveBeenCalledWith("Finish it first.", "error");
  });

  it("no host answering saves nothing", () => {
    const { nameInput, saveButton } = mount(null);
    vi.stubGlobal("toast", vi.fn());
    vi.spyOn(console, "error").mockImplementation(() => {});
    // The client-error report posts on its own; no preset post may follow.
    const fetchStub = stubFetch(() => new Response());
    nameInput.value = "Orphan";
    saveButton.click();
    const presetPosts = fetchStub.mock.calls.filter((call) => call[0] === API_URL);
    expect(presetPosts).toEqual([]);
  });

  it("a saved preset empties the name box and refetches the list", async () => {
    const { widget, nameInput, saveButton, hint } = mount();
    vi.stubGlobal("toast", vi.fn());
    stubFetch(() => new Response(null, { status: 201 }));
    nameInput.value = "Mine";
    saveButton.click();
    await vi.waitFor(() => expect(nameInput.value).toBe(""));
    expect(widget.refetchOptions).toHaveBeenCalledOnce();
    // The name is remembered, so re-typing it warns without a refetch.
    nameInput.value = "Mine";
    nameInput.dispatchEvent(new Event("input", { bubbles: true }));
    expect(hint.hidden).toBe(false);
  });

  it("a taken name relabels Save to Overwrite and shows the hint", async () => {
    const { nameInput, saveButton, hint } = mount();
    stubFetch(
      () =>
        new Response(JSON.stringify([{ value: PRESET_UUID, label: "Finished", data: {} }]), {
          status: 200,
        }),
    );
    nameInput.value = "Finished";
    nameInput.dispatchEvent(new Event("focusin", { bubbles: true }));
    await vi.waitFor(() => expect(hint.hidden).toBe(false));
    expect(hint.textContent).toContain("already exists");
    expect(saveButton.textContent).toBe("Overwrite");
    nameInput.value = "Fresh";
    nameInput.dispatchEvent(new Event("input", { bubbles: true }));
    expect(hint.hidden).toBe(true);
    expect(saveButton.textContent).toBe("Save");
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
