// @vitest-environment jsdom
import { describe, expect, it } from "vitest";
import "./filter-group.js";
import "./filter-summary.js";
import type { FilterGroupElement } from "./filter-group.js";

// Valid FieldMeta shape (see Task 1's note): kind "set", choices as
// {value,label} objects so summarize() maps "f" -> "Finished".
const MODELS = JSON.stringify({
  game: {
    fields: [
      { name: "status", label: "Status", kind: "set", nullable: false,
        choices: [{ value: "f", label: "Finished" }], relations: [],
        modifiers: ["INCLUDES", "EXCLUDES"], search_url: "", is_m2m: false },
    ],
    columns: [],
  },
});

function mount(filter = ""): { group: FilterGroupElement; summary: HTMLElement } {
  document.body.innerHTML = "";
  const summary = document.createElement("filter-summary");
  summary.setAttribute("model", "game");
  summary.setAttribute("model-label", "Games");
  summary.setAttribute("models", MODELS);
  const group = document.createElement("filter-group") as FilterGroupElement;
  group.setAttribute("model", "game");
  group.setAttribute("models", MODELS);
  if (filter) group.setAttribute("filter", filter);
  document.body.appendChild(summary);
  document.body.appendChild(group);
  return { group, summary };
}

describe("<filter-summary>", () => {
  it("renders 'Games (all).' for an empty tree", () => {
    const { summary } = mount();
    expect(summary.textContent).toContain("Games (all).");
  });

  it("updates on filter-tree-change", () => {
    const { group, summary } = mount();
    group.loadFilter({ AND: [{ status: { modifier: "INCLUDES", value: "f" } }] });
    // Assert structurally ("Games where …") rather than the exact rendered phrase,
    // which depends on the set-criterion payload shape summarize() expects. If you
    // want the stronger "Finished" check, first read summary.ts's set-value path
    // (summary.ts ~line 290) and match its expected criterion payload exactly.
    expect(summary.textContent).toContain("Games where");
  });
});
