// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import "./filter-group.js";
import { INCOMPLETE_SAVE_REFUSAL } from "./filter-builder.js";
import { applyUrl } from "./filter-url.js";
import { FILTER_TREE_CHANGE_EVENT } from "./filter-group.js";
import type { FilterGroupElement } from "./filter-group.js";
import {
  PRESET_LOAD_EVENT,
  PRESET_SAVE_EVENT,
  PresetSaveRequest,
  PresetState,
} from "./presets.js";

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

function mount(sort = "", perPage = ""): {
  group: FilterGroupElement;
  builder: HTMLElement;
  panel: HTMLElement;
} {
  document.body.innerHTML = "";
  const builder = document.createElement("filter-builder");
  builder.setAttribute("model", "game");
  builder.setAttribute("mode", "games");
  builder.setAttribute("apply-url", "/tracker/game/list");
  builder.setAttribute("preset-api-url", "/api/presets/");
  // Set before append so connectedCallback reads it (attrs aren't re-read).
  if (sort) builder.setAttribute("sort", sort);
  if (perPage) builder.setAttribute("per-page", perPage);
  const group = document.createElement("filter-group") as FilterGroupElement;
  group.setAttribute("model", "game");
  group.setAttribute("models", MODELS);
  document.body.appendChild(builder);
  document.body.appendChild(group);
  // A stand-in for <preset-panel>: this suite speaks its event contract only.
  const panel = document.createElement("div");
  builder.appendChild(panel);
  return { group, builder, panel };
}

function load(panel: HTMLElement, preset: PresetState): void {
  panel.dispatchEvent(new CustomEvent(PRESET_LOAD_EVENT, { bubbles: true, detail: preset }));
}

function requestSave(panel: HTMLElement): PresetSaveRequest {
  const request: PresetSaveRequest = { state: null, refusal: null };
  panel.dispatchEvent(new CustomEvent(PRESET_SAVE_EVENT, { bubbles: true, detail: request }));
  return request;
}

function stubNavigate(builder: HTMLElement): ReturnType<typeof vi.fn> {
  const navigate = vi.fn();
  (builder as unknown as { navigate: (url: string) => void }).navigate = navigate;
  return navigate;
}

function markIncomplete(): void {
  document.dispatchEvent(
    new CustomEvent(FILTER_TREE_CHANGE_EVENT, {
      bubbles: true,
      detail: { tree: {}, incompleteCount: 1 },
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
    const navigate = stubNavigate(builder);
    (builder.querySelector("[data-apply]") as HTMLElement).click();
    expect(navigate).toHaveBeenCalledWith("/tracker/game/list");
  });

  it("Apply carries the sort threaded from the list (#77)", () => {
    const { builder } = mount("-playtime,name");
    const navigate = stubNavigate(builder);
    (builder.querySelector("[data-apply]") as HTMLElement).click();
    expect(navigate).toHaveBeenCalledWith(applyUrl("/tracker/game/list", {}, "-playtime,name"));
  });

  it("Apply carries the per_page threaded from the list (#337)", () => {
    const { builder } = mount("", "100");
    const navigate = stubNavigate(builder);
    (builder.querySelector("[data-apply]") as HTMLElement).click();
    expect(navigate).toHaveBeenCalledWith(applyUrl("/tracker/game/list", {}, "", "100"));
  });

  it("a loaded preset goes into the tree and the page stays", () => {
    const { group, builder, panel } = mount();
    const navigate = stubNavigate(builder);
    const filter = { AND: [{ status: { modifier: "INCLUDES", value: ["f"] } }] };
    load(panel, { filter, sort: "", perPage: "" });
    expect(group.serialize()).toEqual(filter);
    expect(navigate).not.toHaveBeenCalled();
  });

  it("a loaded preset's sort and per_page replace the list's on the next Apply", () => {
    const { builder, panel } = mount("-playtime", "100");
    const navigate = stubNavigate(builder);
    load(panel, { filter: {}, sort: "name", perPage: "50" });
    (builder.querySelector("[data-apply]") as HTMLElement).click();
    expect(navigate).toHaveBeenCalledWith(applyUrl("/tracker/game/list", {}, "name", "50"));
  });

  it("a loaded preset with no sort or per_page clears the list's", () => {
    const { builder, panel } = mount("-playtime", "100");
    const navigate = stubNavigate(builder);
    load(panel, { filter: {}, sort: "", perPage: "" });
    (builder.querySelector("[data-apply]") as HTMLElement).click();
    expect(navigate).toHaveBeenCalledWith("/tracker/game/list");
  });

  it("a save states the live filter Apply queries, not the stored tree", () => {
    const { group, panel } = mount("-playtime", "100");
    const live = { AND: [{ status: { modifier: "INCLUDES", value: ["p"] } }] };
    group.serialize = () => ({ AND: [{ status: {} }] });
    group.serializeForQuery = () => live;
    expect(requestSave(panel)).toEqual({
      state: { filter: live, sort: "-playtime", perPage: "100" },
      refusal: null,
    });
  });

  it("a save is refused while a criterion is incomplete", () => {
    const { group, panel } = mount();
    group.serializeForQuery = () => ({ AND: [{ status: {} }] });
    markIncomplete();
    expect(requestSave(panel)).toEqual({ state: null, refusal: INCOMPLETE_SAVE_REFUSAL });
  });

  it("a save of an all-blank tree states the empty filter", () => {
    const { group, panel } = mount();
    group.serializeForQuery = () => ({});
    markIncomplete();
    expect(requestSave(panel).state?.filter).toEqual({});
  });

  it("Apply disabled when an incomplete leaf coexists with a non-empty filter", () => {
    const { group, builder } = mount();
    group.serializeForQuery = () => ({ AND: [{ status: {} }] });
    markIncomplete();
    const applyButton = builder.querySelector<HTMLButtonElement>("[data-apply]");
    expect(applyButton?.disabled).toBe(true);
  });

  it("Apply enabled when the pruned filter is empty even with an incomplete leaf", () => {
    const { group, builder } = mount();
    group.serializeForQuery = () => ({});
    markIncomplete();
    const applyButton = builder.querySelector<HTMLButtonElement>("[data-apply]");
    expect(applyButton?.disabled).toBe(false);
  });
});
