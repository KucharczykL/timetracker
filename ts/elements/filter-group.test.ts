// @vitest-environment jsdom
import { describe, it, expect } from "vitest";
import "./filter-group.js"; // side-effect: customElements.define("filter-group", …)
import type { FilterGroupElement } from "./filter-group.js";

function mount(): FilterGroupElement {
  document.body.replaceChildren();
  const host = document.createElement("filter-group") as FilterGroupElement;
  host.setAttribute("model", "game");
  document.body.appendChild(host); // connectedCallback → initial render
  return host;
}

function button(host: HTMLElement, action: string, path: number[]): HTMLButtonElement | null {
  return host.querySelector<HTMLButtonElement>(
    `button[data-action="${action}"][data-path="${JSON.stringify(path)}"]`,
  );
}

function clickAction(host: HTMLElement, action: string, path: number[]): void {
  const target = button(host, action, path);
  if (!target) throw new Error(`no ${action} button at ${JSON.stringify(path)}`);
  target.click();
}

function slots(host: HTMLElement): HTMLElement[] {
  return [...host.querySelectorAll<HTMLElement>("[data-node-slot]")];
}

describe("<filter-group> initial render", () => {
  it("renders a root AND group with one criterion slot and a footer", () => {
    const host = mount();
    const root = host.querySelector('[data-kind="group"][data-path="[]"]');
    expect(root).not.toBeNull();
    expect(button(host, "toggle-connective", [])?.textContent).toBe("AND");
    expect(slots(host)).toHaveLength(1);
    expect(slots(host)[0].dataset.nodeKind).toBe("criterion");
    expect(button(host, "add-condition", [])).not.toBeNull();
    expect(button(host, "add-group", [])).not.toBeNull();
    expect(button(host, "add-relation", [])).not.toBeNull();
  });

  it("gives the root no remove/wrap controls", () => {
    const host = mount();
    expect(button(host, "remove", [])).toBeNull();
    expect(button(host, "wrap", [])).toBeNull();
  });
});

describe("<filter-group> footer add buttons", () => {
  it("+ condition appends a criterion slot", () => {
    const host = mount();
    clickAction(host, "add-condition", []);
    expect(slots(host)).toHaveLength(2);
  });

  it("+ group nests a group card", () => {
    const host = mount();
    clickAction(host, "add-group", []);
    expect(host.querySelector('[data-kind="group"][data-path="[1]"]')).not.toBeNull();
  });

  it("+ relation adds a relation slot", () => {
    const host = mount();
    clickAction(host, "add-relation", []);
    const relationSlot = slots(host).find((slot) => slot.dataset.nodeKind === "relation");
    expect(relationSlot).toBeDefined();
  });
});

describe("<filter-group> restructuring", () => {
  it("remove deletes the addressed node", () => {
    const host = mount();
    clickAction(host, "add-condition", []); // two criteria now
    clickAction(host, "remove", [0]);
    expect(slots(host)).toHaveLength(1);
  });

  it("↑/↓ reorder siblings and disable at the ends", () => {
    const host = mount();
    clickAction(host, "add-group", []); // [0]=criterion, [1]=group
    // first child's up is disabled; last child's down is disabled
    expect(button(host, "up", [0])?.disabled).toBe(true);
    expect(button(host, "down", [1])?.disabled).toBe(true);
    clickAction(host, "down", [0]); // criterion moves after the group
    const kinds = [...host.querySelector('[data-path="[]"]')!.children]
      .find((child) => child.className.includes("pl-3"))!;
    expect(kinds.children[0].matches('[data-kind="group"]')).toBe(true);
  });

  it("wrap nests a node in a new group; unwrap dissolves it", () => {
    const host = mount();
    clickAction(host, "wrap", [0]); // the seed criterion → wrapped in a group
    const wrapper = host.querySelector('[data-kind="group"][data-path="[0]"]');
    expect(wrapper).not.toBeNull();
    expect(slots(host)).toHaveLength(1); // still one criterion, now nested
    clickAction(host, "unwrap", [0]); // dissolve back
    expect(host.querySelector('[data-kind="group"][data-path="[0]"]')).toBeNull();
    expect(slots(host)).toHaveLength(1);
  });
});

describe("<filter-group> depth cap", () => {
  it("disables + group / + relation at the soft cap (depth 5)", () => {
    const host = mount();
    // Nest groups down the [1,1,1,1,1] spine; each new group seeds a criterion at *,0.
    const paths = [[], [1], [1, 1], [1, 1, 1], [1, 1, 1, 1]];
    for (const path of paths) clickAction(host, "add-group", path);
    const deepest = [1, 1, 1, 1, 1];
    expect(host.querySelector(`[data-kind="group"][data-path="${JSON.stringify(deepest)}"]`)).not.toBeNull();
    expect(button(host, "add-group", deepest)?.disabled).toBe(true);
    expect(button(host, "add-relation", deepest)?.disabled).toBe(true);
    expect(button(host, "add-condition", deepest)?.disabled).toBeFalsy();
    // the deepest group's own Wrap is disabled too — wrapping it would breach the cap
    expect(button(host, "wrap", deepest)?.disabled).toBe(true);
  });
});

describe("<filter-group> change event", () => {
  it("dispatches filter-tree-change carrying the new tree on each edit", () => {
    const host = mount();
    const events: GroupNodeLike[] = [];
    host.addEventListener("filter-tree-change", (event) => {
      events.push((event as CustomEvent).detail.tree);
    });
    clickAction(host, "add-condition", []);
    expect(events).toHaveLength(1);
    expect(events[0].children).toHaveLength(2);
    expect(host.serialize()).toBeTypeOf("object");
  });
});

describe("<filter-group> relation slot (inert, comp 5)", () => {
  it("relation slots carry data-path and data-node-kind", () => {
    const host = mount();
    clickAction(host, "add-relation", []); // [0]=criterion, [1]=relation
    const relationSlot = slots(host).find((slot) => slot.dataset.nodeKind === "relation")!;
    expect(relationSlot.dataset.path).toBe(JSON.stringify([1]));
  });
});

describe("<filter-group> connective + negate (component 2, #190)", () => {
  it("connective chip flips the group connective AND<->OR", () => {
    const host = mount();
    expect(button(host, "toggle-connective", [])?.textContent).toBe("AND");
    clickAction(host, "toggle-connective", []);
    expect(button(host, "toggle-connective", [])?.textContent).toBe("OR");
    expect(Object.keys(host.serialize())[0]).toBe("OR");
    clickAction(host, "toggle-connective", []);
    expect(button(host, "toggle-connective", [])?.textContent).toBe("AND");
  });

  it("color-codes the connective chip by value (teal AND / orange OR)", () => {
    const host = mount();
    expect(button(host, "toggle-connective", [])?.className).toContain("teal");
    clickAction(host, "toggle-connective", []);
    const orChip = button(host, "toggle-connective", []);
    expect(orChip?.className).toContain("orange");
    expect(orChip?.className).not.toContain("teal");
  });

  it("negate chip on a group wraps it in {NOT:[…]} and flips aria-pressed", () => {
    const host = mount();
    const before = button(host, "toggle-negate", []);
    expect(before?.getAttribute("aria-pressed")).toBe("false");
    clickAction(host, "toggle-negate", []);
    expect(button(host, "toggle-negate", [])?.getAttribute("aria-pressed")).toBe("true");
    expect(Object.keys(host.serialize())[0]).toBe("NOT");
    // toggling off restores the un-negated shape (UI re-render round-trips)
    clickAction(host, "toggle-negate", []);
    expect(button(host, "toggle-negate", [])?.getAttribute("aria-pressed")).toBe("false");
    expect(Object.keys(host.serialize())[0]).toBe("AND");
  });

  it("negate chip on a leaf negates only that leaf", () => {
    const host = mount(); // root AND with one seed criterion at [0]
    expect(button(host, "toggle-negate", [0])?.getAttribute("aria-pressed")).toBe("false");
    clickAction(host, "toggle-negate", [0]);
    expect(button(host, "toggle-negate", [0])?.getAttribute("aria-pressed")).toBe("true");
    // root stays a plain AND group; the negation is on the leaf inside it
    const serialized = host.serialize() as { AND: Record<string, unknown>[] };
    expect(Object.keys(serialized)[0]).toBe("AND");
    expect(Object.keys(serialized.AND[0])[0]).toBe("NOT");
  });

  it("dispatches filter-tree-change on connective and negate edits", () => {
    const host = mount();
    let count = 0;
    host.addEventListener("filter-tree-change", () => (count += 1));
    clickAction(host, "toggle-connective", []);
    clickAction(host, "toggle-negate", []);
    expect(count).toBe(2);
  });
});

describe("<filter-group> empty groups (#236)", () => {
  it("auto-collapses a nested group when its last child is removed", () => {
    const host = mount();
    clickAction(host, "add-group", []); // [0]=seed criterion, [1]=group with [1,0]=criterion
    expect(host.querySelector('[data-kind="group"][data-path="[1]"]')).not.toBeNull();
    clickAction(host, "remove", [1, 0]); // empties the nested group → it is removed
    expect(host.querySelector('[data-kind="group"][data-path="[1]"]')).toBeNull();
    expect(slots(host)).toHaveLength(1); // only the root's seed criterion remains
  });

  it("renders a 'matches all' empty state with no NOT/connective chip when root is cleared", () => {
    const host = mount();
    clickAction(host, "remove", [0]); // remove the root's only seed criterion
    expect(button(host, "toggle-negate", [])).toBeNull();
    expect(button(host, "toggle-connective", [])).toBeNull();
    expect(host.textContent).toContain("No conditions. This will match all items.");
    // the add affordances stay so the user can rebuild
    expect(button(host, "add-condition", [])).not.toBeNull();
    expect(button(host, "add-group", [])).not.toBeNull();
    // an empty filter serializes to {} (matches everything)
    expect(host.serialize()).toEqual({});
  });

  it("a cascade removal collapses the group in the DOM and fires one change event", () => {
    const host = mount();
    clickAction(host, "add-group", []); // [1]=group seeded with [1,0]=criterion
    let count = 0;
    host.addEventListener("filter-tree-change", () => (count += 1));
    clickAction(host, "remove", [1, 0]); // empties the nested group → collapses it
    expect(count).toBe(1);
    expect(host.querySelector('[data-kind="group"][data-path="[1]"]')).toBeNull();
  });

  it("rebuilds from the empty state and restores the header chips", () => {
    const host = mount();
    clickAction(host, "remove", [0]);
    clickAction(host, "add-condition", []);
    expect(button(host, "toggle-negate", [])).not.toBeNull();
    expect(button(host, "toggle-connective", [])?.textContent).toBe("AND");
    expect(slots(host)).toHaveLength(1);
  });
});

describe("<filter-group> duplicate + event fidelity", () => {
  it("duplicate adds a sibling copy", () => {
    const host = mount();
    clickAction(host, "duplicate", [0]);
    expect(slots(host)).toHaveLength(2);
  });

  it("dispatches exactly one change event per effective edit (no spurious)", () => {
    const host = mount();
    let count = 0;
    host.addEventListener("filter-tree-change", () => (count += 1));
    clickAction(host, "add-condition", []);
    clickAction(host, "add-group", []);
    clickAction(host, "remove", [0]);
    expect(count).toBe(3);
  });
});

type GroupNodeLike = { children: unknown[] };

// ── Live criterion leaf row (#192) ──
// The real templates come from the server (FilterGroup Python); here we synthesize
// a minimal field-picker + one string field widget so the row wiring can be driven
// in jsdom. The string widget mirrors StringFilter's data hooks readStringWidget reads.
const NAME_META = {
  name: "name",
  label: "Name",
  kind: "string",
  nullable: false,
  choices: [],
  modifiers: ["EQUALS", "INCLUDES"],
  relations: [],
};

function mountLive(): FilterGroupElement {
  document.body.replaceChildren();
  const host = document.createElement("filter-group") as FilterGroupElement;
  host.setAttribute("model", "game");
  host.setAttribute("fields", JSON.stringify([NAME_META]));
  // Templates must exist before connectedCallback (captureTemplates runs there).
  host.innerHTML = `
    <template data-field-picker-template>
      <div data-field-picker><search-select name="field-picker"><input data-search-select-search /></search-select></div>
    </template>
    <template data-field="name">
      <div class="flex-col">
        <select data-string-modifier-select>
          <option value="EQUALS" selected>is</option>
          <option value="INCLUDES">includes</option>
          <option value="IS_NULL">is null</option>
        </select>
        <input type="text" />
      </div>
    </template>`;
  document.body.appendChild(host); // connectedCallback → captures templates + renders
  return host;
}

function row(host: HTMLElement, path: number[]): HTMLElement {
  return host.querySelector<HTMLElement>(
    `[data-node-slot][data-path="${JSON.stringify(path)}"]`,
  )!;
}

function pickField(host: HTMLElement, path: number[], meta: object): void {
  const picker = row(host, path).querySelector<HTMLElement>("[data-field-picker]")!;
  picker.dispatchEvent(
    new CustomEvent("search-select:change", {
      bubbles: true,
      detail: { name: "field-picker", values: [], last: { data: { meta: JSON.stringify(meta) } } },
    }),
  );
}

function typeValue(host: HTMLElement, path: number[], text: string): void {
  const input = row(host, path).querySelector<HTMLInputElement>('[data-value-cell] input[type="text"]')!;
  input.value = text;
  input.dispatchEvent(new Event("input", { bubbles: true }));
}

describe("<filter-group> live criterion leaf row (#192)", () => {
  it("picking a field swaps in that field's value widget", () => {
    const host = mountLive();
    expect(row(host, [0]).querySelector('[data-value-cell] input[type="text"]')).toBeNull();
    pickField(host, [0], NAME_META);
    expect(row(host, [0]).querySelector('[data-value-cell] input[type="text"]')).not.toBeNull();
  });

  it("serializeForQuery reads the live widget into the exact backend payload shape", () => {
    const host = mountLive();
    pickField(host, [0], NAME_META);
    typeValue(host, [0], "Hades");
    expect(host.serializeForQuery()).toEqual({
      AND: [{ name: { value: "Hades", modifier: "EQUALS" } }],
    });
  });

  it("excludes an incomplete leaf (no value) from the query + flags it", () => {
    const host = mountLive();
    pickField(host, [0], NAME_META); // field chosen, value still empty
    expect(row(host, [0]).querySelector("[data-incomplete-badge]")).not.toBeNull();
    expect(host.serializeForQuery()).toEqual({}); // pruned → matches all
    expect(host.serialize()).not.toEqual({}); // structure still carries the leaf
  });

  it("a leaf's live value survives a structural edit elsewhere (reconcile by id)", () => {
    const host = mountLive();
    pickField(host, [0], NAME_META);
    typeValue(host, [0], "Hades");
    clickAction(host, "add-condition", []); // structural re-render of the whole tree
    // The first row's widget DOM (and its typed value) is reused, not rebuilt.
    const input = row(host, [0]).querySelector<HTMLInputElement>('[data-value-cell] input[type="text"]')!;
    expect(input.value).toBe("Hades");
  });

  it("reports incompleteCount in the change event", () => {
    const host = mountLive();
    let last = -1;
    host.addEventListener("filter-tree-change", (event) => {
      last = (event as CustomEvent).detail.incompleteCount;
    });
    pickField(host, [0], NAME_META); // 1 incomplete (no value yet)
    expect(last).toBe(1);
    typeValue(host, [0], "Hades");
    expect(last).toBe(0);
  });
});

// ── Live field-comparison leaf row (#246) ──
// Two number columns of the same group so a comparison is buildable. The synthetic
// row template mirrors _field_comparison_row's data hooks (data-fc-left/op/right +
// the by-day granularity toggle) so the reused refreshRow/readComparisonRow drive it.
const COLUMNS = [
  { value: "year_released", label: "Year", group: "number", operators: ["EQUALS", "LESS_THAN"] },
  { value: "original_year_released", label: "Orig", group: "number", operators: ["EQUALS", "LESS_THAN"] },
  { value: "created_at", label: "Created", group: "datetime", operators: ["EQUALS", "LESS_THAN"] },
  { value: "updated_at", label: "Updated", group: "datetime", operators: ["EQUALS", "LESS_THAN"] },
];

function mountComparison(): FilterGroupElement {
  document.body.replaceChildren();
  const host = document.createElement("filter-group") as FilterGroupElement;
  host.setAttribute("model", "game");
  host.setAttribute("fields", JSON.stringify([]));
  host.setAttribute("columns", JSON.stringify(COLUMNS));
  host.innerHTML = `
    <template data-fc-row-template>
      <div data-fc-row>
        <select data-fc-left>
          <option value="">column…</option>
          <option value="year_released">Year</option>
          <option value="original_year_released">Orig</option>
          <option value="created_at">Created</option>
          <option value="updated_at">Updated</option>
        </select>
        <select data-fc-op data-selected></select>
        <select data-fc-right data-selected></select>
        <label data-fc-granularity-wrap hidden><input type="checkbox" data-fc-granularity /></label>
        <button data-fc-remove>✕</button>
      </div>
    </template>`;
  document.body.appendChild(host);
  return host;
}

function setSelect(host: HTMLElement, path: number[], hook: string, value: string): void {
  const select = row(host, path).querySelector<HTMLSelectElement>(`[data-value-cell] [${hook}]`)!;
  select.value = value;
  select.dispatchEvent(new Event("change", { bubbles: true }));
}

describe("<filter-group> live field-comparison leaf (#246)", () => {
  it("shows + comparison only when the model has a comparable group", () => {
    expect(button(mountComparison(), "add-comparison", [])).not.toBeNull();
    // no columns → no comparison affordance
    const host = mount(); // model "game" but no columns attribute → hasComparableGroup false
    expect(button(host, "add-comparison", [])).toBeNull();
  });

  it("+ comparison adds a live comparison row (not an inert slot)", () => {
    const host = mountComparison();
    clickAction(host, "add-comparison", []);
    const slot = slots(host).find((s) => s.dataset.nodeKind === "comparison")!;
    expect(slot).toBeDefined();
    expect(slot.querySelector("[data-fc-row]")).not.toBeNull();
    // the row's own ✕ is dropped — the group's controls own removal
    expect(slot.querySelector("[data-fc-remove]")).toBeNull();
  });

  it("serializeForQuery emits the backend field_comparisons payload", () => {
    const host = mountComparison();
    clickAction(host, "remove", [0]); // drop the seed criterion so only the comparison remains
    clickAction(host, "add-comparison", []);
    setSelect(host, [0], "data-fc-left", "year_released"); // refreshRow fills op + right
    setSelect(host, [0], "data-fc-op", "LESS_THAN");
    setSelect(host, [0], "data-fc-right", "original_year_released");
    expect(host.serializeForQuery()).toEqual({
      AND: [{ field_comparisons: [{ left: "year_released", right: "original_year_released", modifier: "LESS_THAN" }] }],
    });
  });

  it("excludes an incomplete comparison (only left chosen) from the query + flags it", () => {
    const host = mountComparison();
    clickAction(host, "remove", [0]);
    clickAction(host, "add-comparison", []);
    setSelect(host, [0], "data-fc-left", "year_released"); // right/op still empty
    expect(row(host, [0]).querySelector("[data-incomplete-badge]")).not.toBeNull();
    expect(host.serializeForQuery()).toEqual({}); // pruned → matches all
  });

  it("reports the incomplete comparison in incompleteCount", () => {
    const host = mountComparison();
    clickAction(host, "remove", [0]);
    let last = -1;
    host.addEventListener("filter-tree-change", (event) => {
      last = (event as CustomEvent).detail.incompleteCount;
    });
    clickAction(host, "add-comparison", []); // added empty → 1 incomplete
    expect(last).toBe(1);
    setSelect(host, [0], "data-fc-left", "year_released");
    setSelect(host, [0], "data-fc-op", "LESS_THAN");
    setSelect(host, [0], "data-fc-right", "original_year_released");
    expect(last).toBe(0);
  });

  it("a comparison's live value survives a structural edit elsewhere (reconcile by id)", () => {
    const host = mountComparison();
    clickAction(host, "add-comparison", []); // [0]=criterion seed, [1]=comparison
    setSelect(host, [1], "data-fc-left", "year_released");
    setSelect(host, [1], "data-fc-op", "LESS_THAN");
    setSelect(host, [1], "data-fc-right", "original_year_released");
    clickAction(host, "add-condition", []); // structural re-render
    const left = row(host, [1]).querySelector<HTMLSelectElement>("[data-fc-left]")!;
    expect(left.value).toBe("year_released");
  });

  it("negating a comparison leaf serializes to {NOT:[{field_comparisons:…}]}", () => {
    const host = mountComparison();
    clickAction(host, "remove", [0]);
    clickAction(host, "add-comparison", []);
    setSelect(host, [0], "data-fc-left", "year_released");
    setSelect(host, [0], "data-fc-op", "LESS_THAN");
    setSelect(host, [0], "data-fc-right", "original_year_released");
    clickAction(host, "toggle-negate", [0]);
    expect(button(host, "toggle-negate", [0])?.getAttribute("aria-pressed")).toBe("true");
    expect(host.serializeForQuery()).toEqual({
      AND: [{ NOT: [{ field_comparisons: [{ left: "year_released", right: "original_year_released", modifier: "LESS_THAN" }] }] }],
    });
  });

  it("emits granularity:\"date\" only when the by-day toggle is checked and visible", () => {
    const host = mountComparison();
    clickAction(host, "remove", [0]);
    clickAction(host, "add-comparison", []);
    // A datetime left column unhides the by-day wrapper (refreshRow); check it.
    setSelect(host, [0], "data-fc-left", "created_at");
    setSelect(host, [0], "data-fc-op", "LESS_THAN");
    setSelect(host, [0], "data-fc-right", "updated_at");
    const wrap = row(host, [0]).querySelector<HTMLElement>("[data-fc-granularity-wrap]")!;
    expect(wrap.hidden).toBe(false); // datetime operand → toggle shown
    const byDay = row(host, [0]).querySelector<HTMLInputElement>("[data-fc-granularity]")!;
    byDay.checked = true;
    byDay.dispatchEvent(new Event("change", { bubbles: true }));
    expect(host.serializeForQuery()).toEqual({
      AND: [{ field_comparisons: [{ left: "created_at", right: "updated_at", modifier: "LESS_THAN", granularity: "date" }] }],
    });
  });

  it("drops granularity when the by-day wrapper is hidden (non-datetime operand)", () => {
    const host = mountComparison();
    clickAction(host, "remove", [0]);
    clickAction(host, "add-comparison", []);
    setSelect(host, [0], "data-fc-left", "year_released"); // number group → wrapper stays hidden
    setSelect(host, [0], "data-fc-op", "LESS_THAN");
    setSelect(host, [0], "data-fc-right", "original_year_released");
    // Force the checkbox on even though the wrapper is hidden — readComparisonRow
    // must still omit granularity (guards the `!byDayWrap.hidden` condition).
    const byDay = row(host, [0]).querySelector<HTMLInputElement>("[data-fc-granularity]")!;
    byDay.checked = true;
    const payload = (host.serializeForQuery() as { AND: { field_comparisons: object[] }[] }).AND[0].field_comparisons[0];
    expect(payload).not.toHaveProperty("granularity");
  });
});
