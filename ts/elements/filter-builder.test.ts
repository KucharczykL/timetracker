// @vitest-environment jsdom
import { describe, expect, it, vi } from "vitest";
import "./filter-group.js";
import "./filter-builder.js";
import { applyUrl } from "./filter-builder.js";
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
});
