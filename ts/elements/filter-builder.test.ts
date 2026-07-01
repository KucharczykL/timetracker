// @vitest-environment jsdom
import { describe, expect, it, vi } from "vitest";
import "./filter-group.js";
import "./filter-builder.js";
import { applyUrl } from "./filter-builder.js";
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

function mount(): { group: FilterGroupElement; builder: HTMLElement } {
  document.body.innerHTML = "";
  const builder = document.createElement("filter-builder");
  builder.setAttribute("model", "game");
  builder.setAttribute("mode", "games");
  builder.setAttribute("apply-url", "/tracker/game/list");
  builder.setAttribute("preset-list-url", "/tracker/filter/presets/list");
  builder.setAttribute("preset-save-url", "/tracker/filter/presets/save");
  const group = document.createElement("filter-group") as FilterGroupElement;
  group.setAttribute("model", "game");
  group.setAttribute("models", MODELS);
  document.body.appendChild(builder);
  document.body.appendChild(group);
  return { group, builder };
}

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

  it("Preset pick loads filter into the group without navigating", () => {
    const { group, builder } = mount();
    const navigate = vi.fn();
    (builder as unknown as { navigate: (url: string) => void }).navigate = navigate;

    // Inject a preset dropdown anchor whose href carries a ?filter= param,
    // mimicking the server's list_presets fragment. The delete span is nested
    // inside so the click-ordering logic is also exercised (delete check runs
    // first, but the click is on the anchor itself, not the delete span).
    const filter = { AND: [{ status: { modifier: "INCLUDES", value: ["f"] } }] };
    const dropdown = builder.querySelector("[data-preset-dropdown]") as HTMLElement;
    dropdown.classList.remove("hidden");
    dropdown.innerHTML = `
      <ul>
        <li>
          <a href="/tracker/game/list?filter=${encodeURIComponent(JSON.stringify(filter))}">
            Finished games
            <span data-delete-preset href="/tracker/filter/presets/delete/1">×</span>
          </a>
        </li>
      </ul>`;

    const anchor = dropdown.querySelector("a[href]") as HTMLElement;
    anchor.click();

    expect(group.serialize()).toEqual(filter);
    expect(navigate).not.toHaveBeenCalled();
  });

  it("Delete sends X-CSRFToken header and does not load the preset", () => {
    const { builder } = mount();

    // Set the CSRF cookie so getCsrfToken() returns a known value.
    document.cookie = "csrftoken=testtoken";

    // Stub window.fetchWithHtmxTriggers and window.confirm.
    const fetchStub = vi.fn(() => Promise.resolve());
    (window as unknown as Record<string, unknown>).fetchWithHtmxTriggers = fetchStub;
    const confirmStub = vi.fn(() => true);
    vi.stubGlobal("confirm", confirmStub);

    // Inject a preset anchor containing a nested [data-delete-preset] span.
    const dropdown = builder.querySelector("[data-preset-dropdown]") as HTMLElement;
    dropdown.classList.remove("hidden");
    dropdown.innerHTML = `
      <ul>
        <li>
          <a href="/tracker/game/list?filter=%7B%7D">
            My preset
            <span data-delete-preset="" href="/tracker/filter/presets/delete/42">×</span>
          </a>
        </li>
      </ul>`;

    const deleteSpan = dropdown.querySelector("[data-delete-preset]") as HTMLElement;
    deleteSpan.click();

    expect(confirmStub).toHaveBeenCalled();
    expect(fetchStub).toHaveBeenCalledOnce();
    const [_url, options] = fetchStub.mock.calls[0] as unknown as [string, RequestInit & { headers: Record<string, string> }];
    expect(options.method).toBe("DELETE");
    expect(options.headers["X-CSRFToken"]).toBe("testtoken");

    vi.unstubAllGlobals();
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

  it("Save preset POSTs with X-CSRFToken", async () => {
    const { builder } = mount();

    // Set the CSRF cookie so getCsrfToken() returns a known value.
    document.cookie = "csrftoken=testtoken";

    // Stub window.fetchWithHtmxTriggers to capture the call.
    const fetchStub = vi.fn(() => Promise.resolve(new Response()));
    (window as unknown as Record<string, unknown>).fetchWithHtmxTriggers = fetchStub;

    // Fill in the preset name input.
    const nameInput = builder.querySelector<HTMLInputElement>("[data-preset-name]");
    if (nameInput) nameInput.value = "My preset";

    (builder.querySelector("[data-save-preset]") as HTMLElement).click();

    expect(fetchStub).toHaveBeenCalledOnce();
    const [_url, options] = fetchStub.mock.calls[0] as unknown as [string, RequestInit & { headers: Record<string, string> }];
    expect(options.method).toBe("POST");
    expect(options.headers["X-CSRFToken"]).toBe("testtoken");
  });

  it("Save preset with a blank name does not POST", () => {
    const { builder } = mount();

    // Stub fetch and toast so no real network call or error is thrown.
    const fetchStub = vi.fn(() => Promise.resolve(new Response()));
    (window as unknown as Record<string, unknown>).fetchWithHtmxTriggers = fetchStub;
    (window as unknown as Record<string, unknown>).toast = vi.fn();

    // Leave the name input empty (default value is "").
    (builder.querySelector("[data-save-preset]") as HTMLElement).click();

    expect(fetchStub).not.toHaveBeenCalled();
  });
});
