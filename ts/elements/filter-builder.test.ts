// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import "./filter-group.js";
import "./filter-builder.js";
import { applyUrl } from "./filter-url.js";
import { FILTER_TREE_CHANGE_EVENT } from "./filter-group.js";
import type { FilterGroupElement } from "./filter-group.js";

const MODELS = JSON.stringify({
  game: {
    fields: [{ name: "status", label: "Status", kind: "set", nullable: false, choices: [],
      relations: [], modifiers: ["INCLUDES", "EXCLUDES"], search_url: "", is_m2m: false }],
    columns: [],
  },
});

describe("applyUrl", () => {
  it("returns the bare list url for an empty filter", () => {
    expect(applyUrl("/tracker/game/list", {})).toBe("/tracker/game/list");
  });
  it("appends ?filter= for a non-empty filter", () => {
    const filter = { AND: [{ status: { modifier: "EQUALS", value: "f" } }] };
    expect(applyUrl("/tracker/game/list", filter)).toBe(
      "/tracker/game/list?filter=" + encodeURIComponent(JSON.stringify(filter)),
    );
  });
});

interface PickerWidgetStub extends HTMLElement {
  refetchOptions: ReturnType<typeof vi.fn>;
  clearSelection: ReturnType<typeof vi.fn>;
}

function mount(sort = ""): {
  group: FilterGroupElement;
  builder: HTMLElement;
  widget: PickerWidgetStub;
} {
  document.body.innerHTML = "";
  const builder = document.createElement("filter-builder");
  builder.setAttribute("model", "game");
  builder.setAttribute("mode", "games");
  builder.setAttribute("apply-url", "/tracker/game/list");
  builder.setAttribute("preset-api-url", "/api/presets/");
  // Set before append so connectedCallback reads it (attrs aren't re-read).
  if (sort) builder.setAttribute("sort", sort);
  const group = document.createElement("filter-group") as FilterGroupElement;
  group.setAttribute("model", "game");
  group.setAttribute("models", MODELS);
  document.body.appendChild(builder);
  document.body.appendChild(group);
  // ensureToolbar leaves [data-preset-picker] empty; give it the widget the
  // real LoadPresetDropdown would host, with the duck-typed methods stubbed
  // (this suite deliberately never imports search-select.js).
  const picker = builder.querySelector("[data-preset-picker]") as HTMLElement & {
    close?: ReturnType<typeof vi.fn>;
  };
  picker.close = vi.fn();
  const widget = document.createElement("search-select") as PickerWidgetStub;
  widget.refetchOptions = vi.fn();
  widget.clearSelection = vi.fn();
  picker.appendChild(widget);
  return { group, builder, widget };
}

// A pick as the preset search-select emits it: bubbling search-select:change
// whose last.data.filter carries the preset's filter JSON.
function dispatchPick(widget: HTMLElement, filterJson: string, sort?: string): void {
  const data: Record<string, string> = { filter: filterJson };
  if (sort !== undefined) data.sort = sort;
  widget.dispatchEvent(
    new CustomEvent("search-select:change", {
      bubbles: true,
      detail: {
        name: "preset",
        values: ["1"],
        last: { value: "1", label: "Finished games", data },
      },
    }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("<filter-builder>", () => {
  it("Clear empties the group tree", () => {
    const { group, builder } = mount();
    group.loadFilter({ AND: [{ status: { modifier: "EQUALS", value: "f" } }] });
    (builder.querySelector("[data-clear]") as HTMLElement).click();
    expect(group.serialize()).toEqual({});
  });

  it("Apply navigates to applyUrl(serializeForQuery())", () => {
    const { builder } = mount();
    const navigate = vi.fn();
    (builder as unknown as { navigate: (url: string) => void }).navigate = navigate;
    (builder.querySelector("[data-apply]") as HTMLElement).click();
    expect(navigate).toHaveBeenCalledWith("/tracker/game/list");
  });

  it("Apply carries the sort threaded from the list (#77)", () => {
    const { builder } = mount("-playtime,name");
    const navigate = vi.fn();
    (builder as unknown as { navigate: (url: string) => void }).navigate = navigate;
    (builder.querySelector("[data-apply]") as HTMLElement).click();
    expect(navigate).toHaveBeenCalledWith(applyUrl("/tracker/game/list", {}, "-playtime,name"));
  });

  it("a picked preset's sort overrides the list sort on the next Apply (#77)", () => {
    const { builder, widget } = mount("-playtime");
    const navigate = vi.fn();
    (builder as unknown as { navigate: (url: string) => void }).navigate = navigate;
    dispatchPick(widget, JSON.stringify({}), "name");
    (builder.querySelector("[data-apply]") as HTMLElement).click();
    expect(navigate).toHaveBeenCalledWith(applyUrl("/tracker/game/list", {}, "name"));
  });

  it("a picked preset with no stored sort clears the list sort (#77)", () => {
    const { builder, widget } = mount("-playtime");
    const navigate = vi.fn();
    (builder as unknown as { navigate: (url: string) => void }).navigate = navigate;
    dispatchPick(widget, JSON.stringify({}), "");
    (builder.querySelector("[data-apply]") as HTMLElement).click();
    expect(navigate).toHaveBeenCalledWith("/tracker/game/list");
  });

  it("Preset pick loads the filter, clears the transient pick, and closes", () => {
    const { group, builder, widget } = mount();
    const navigate = vi.fn();
    (builder as unknown as { navigate: (url: string) => void }).navigate = navigate;
    const picker = builder.querySelector("[data-preset-picker]") as HTMLElement & {
      close: ReturnType<typeof vi.fn>;
    };

    const filter = { AND: [{ status: { modifier: "INCLUDES", value: ["f"] } }] };
    dispatchPick(widget, JSON.stringify(filter));

    expect(group.serialize()).toEqual(filter);
    expect(navigate).not.toHaveBeenCalled();
    // The pick is a command, not a value: the selection is cleared so no stale
    // row can be pinned through the next refetch, and the dialog closes.
    expect(widget.clearSelection).toHaveBeenCalledOnce();
    expect(picker.close).toHaveBeenCalledOnce();
  });

  it("a change event from outside the picker is ignored", () => {
    const { group, builder } = mount();
    const untouched = group.serialize(); // pristine tree (one blank leaf)
    const stray = document.createElement("search-select");
    builder.appendChild(stray);

    dispatchPick(stray, JSON.stringify({ AND: [{ status: { modifier: "EQUALS", value: "f" } }] }));

    expect(group.serialize()).toEqual(untouched);
  });

  it("bad preset JSON toasts and logs the 'preset load failed' crash-guard line", () => {
    const { builder, widget } = mount();
    const toastStub = vi.fn();
    (window as unknown as Record<string, unknown>).toast = toastStub;
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
    const picker = builder.querySelector("[data-preset-picker]") as HTMLElement & {
      close: ReturnType<typeof vi.fn>;
    };

    dispatchPick(widget, "{not json");

    expect(toastStub).toHaveBeenCalledWith("Preset is not a valid filter.", "error");
    // The builder e2e greps the console for this substring as its crash guard.
    expect(String(consoleError.mock.calls[0][0])).toContain("preset load failed");
    expect(picker.close).toHaveBeenCalledOnce(); // still closes — nothing hangs open
  });

  it("Delete action DELETEs base+id with X-CSRFToken and refetches, never picking", async () => {
    const { group, widget } = mount();
    const untouched = group.serialize(); // pristine tree (one blank leaf)
    document.cookie = "csrftoken=testtoken";
    const fetchStub = vi.fn(() => Promise.resolve(new Response(null, { status: 204 })));
    vi.stubGlobal("fetch", fetchStub);
    vi.stubGlobal("confirm", vi.fn(() => true));

    widget.dispatchEvent(
      new CustomEvent("search-select:action", {
        bubbles: true,
        detail: {
          name: "preset",
          action: "delete",
          option: { value: "42", label: "My preset", data: { filter: "{}" } },
        },
      }),
    );
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(fetchStub).toHaveBeenCalledOnce();
    const [url, options] = fetchStub.mock.calls[0] as unknown as [
      string,
      RequestInit & { headers: Record<string, string> },
    ];
    expect(url).toBe("/api/presets/42");
    expect(options.method).toBe("DELETE");
    expect(options.headers["X-CSRFToken"]).toBe("testtoken");
    expect(widget.refetchOptions).toHaveBeenCalledOnce();
    expect(group.serialize()).toEqual(untouched); // a delete is never a pick

    document.cookie = "csrftoken=; expires=Thu, 01 Jan 1970 00:00:00 GMT";
  });

  it("Apply disabled when an incomplete leaf coexists with a non-empty filter", () => {
    const { group, builder } = mount();
    // Stub serializeForQuery to return a non-empty filter so filterIsEmpty is false.
    group.serializeForQuery = () => ({ AND: [{ status: {} }] });
    // Dispatch a filter-tree-change event with incompleteCount: 1.
    document.dispatchEvent(
      new CustomEvent(FILTER_TREE_CHANGE_EVENT, {
        bubbles: true,
        detail: { tree: {}, incompleteCount: 1 },
      }),
    );
    const applyButton = builder.querySelector<HTMLButtonElement>("[data-apply]");
    expect(applyButton?.disabled).toBe(true);
  });

  it("Apply enabled when the pruned filter is empty even with an incomplete leaf", () => {
    const { group, builder } = mount();
    // Stub serializeForQuery to return an empty filter so filterIsEmpty is true.
    group.serializeForQuery = () => ({});
    // Dispatch a filter-tree-change event with incompleteCount: 1.
    document.dispatchEvent(
      new CustomEvent(FILTER_TREE_CHANGE_EVENT, {
        bubbles: true,
        detail: { tree: {}, incompleteCount: 1 },
      }),
    );
    const applyButton = builder.querySelector<HTMLButtonElement>("[data-apply]");
    expect(applyButton?.disabled).toBe(false);
  });

  it("Save preset POSTs a JSON body with X-CSRFToken to the preset API", () => {
    const { builder } = mount();
    document.cookie = "csrftoken=testtoken";
    const fetchStub = vi.fn(() => Promise.resolve(new Response(null, { status: 201 })));
    vi.stubGlobal("fetch", fetchStub);
    (window as unknown as Record<string, unknown>).toast = vi.fn();

    const nameInput = builder.querySelector<HTMLInputElement>("[data-preset-name]");
    if (nameInput) nameInput.value = "My preset";
    (builder.querySelector("[data-save-preset]") as HTMLElement).click();

    expect(fetchStub).toHaveBeenCalledOnce();
    const [url, options] = fetchStub.mock.calls[0] as unknown as [
      string,
      RequestInit & { headers: Record<string, string>; body: string },
    ];
    expect(url).toBe("/api/presets/");
    expect(options.method).toBe("POST");
    expect(options.headers["Content-Type"]).toBe("application/json");
    expect(options.headers["X-CSRFToken"]).toBe("testtoken");
    expect(JSON.parse(options.body).name).toBe("My preset");
    expect(JSON.parse(options.body).mode).toBe("games");

    document.cookie = "csrftoken=; expires=Thu, 01 Jan 1970 00:00:00 GMT";
  });

  it("Save preset includes the active sort in the POST body (#77)", () => {
    const { builder } = mount("-playtime,name");
    document.cookie = "csrftoken=testtoken";
    const fetchStub = vi.fn(() => Promise.resolve(new Response(null, { status: 201 })));
    vi.stubGlobal("fetch", fetchStub);
    (window as unknown as Record<string, unknown>).toast = vi.fn();

    const nameInput = builder.querySelector<HTMLInputElement>("[data-preset-name]");
    if (nameInput) nameInput.value = "Sorted";
    (builder.querySelector("[data-save-preset]") as HTMLElement).click();

    const [, options] = fetchStub.mock.calls[0] as unknown as [
      string,
      RequestInit & { body: string },
    ];
    expect(JSON.parse(options.body).sort).toBe("-playtime,name");

    document.cookie = "csrftoken=; expires=Thu, 01 Jan 1970 00:00:00 GMT";
  });

  it("Save preset with a blank name does not POST", () => {
    const { builder } = mount();
    const fetchStub = vi.fn(() => Promise.resolve(new Response()));
    vi.stubGlobal("fetch", fetchStub);
    (window as unknown as Record<string, unknown>).toast = vi.fn();

    // Leave the name input empty (default value is "").
    (builder.querySelector("[data-save-preset]") as HTMLElement).click();

    expect(fetchStub).not.toHaveBeenCalled();
  });
});
