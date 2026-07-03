// @vitest-environment jsdom
import { describe, it, expect } from "vitest";
import { FILTER_TREE_CHANGE_EVENT } from "./filter-group.js"; // also registers the custom element
import type { FilterGroupElement } from "./filter-group.js";

// A node path: group-child indices plus the "child" sentinel for descending into a
// relation's child group (RELATION_CHILD, #193).
type Path = (number | string)[];

// One relation-descent field on the game model, pointing at the session model. Gives
// the base `mount()` a model with a relation so the `+ relation` affordance shows.
const SESSION_RELATION = {
  name: "session_filter",
  label: "Sessions",
  kind: "relation",
  nullable: false,
  choices: [],
  modifiers: [],
  relations: [{ field: "session_filter", filter: "SessionFilter", model: "Session" }],
  search_url: "",
  is_m2m: false,
};

// The minimal multi-model `models` prop for the structural (chrome) tests: game has a
// relation into session; session is present (empty) so the descent resolves.
const MODELS_BASE = {
  game: { fields: [SESSION_RELATION], columns: [] },
  session: { fields: [], columns: [] },
};

function mount(): FilterGroupElement {
  document.body.replaceChildren();
  const host = document.createElement("filter-group") as FilterGroupElement;
  host.setAttribute("model", "game");
  host.setAttribute("models", JSON.stringify(MODELS_BASE));
  document.body.appendChild(host); // connectedCallback → initial render
  return host;
}

// Single-quote the data-path attribute value: JSON.stringify uses double quotes
// internally (e.g. the "child" sentinel), so a single-quoted CSS value stays valid.
function button(host: HTMLElement, action: string, path: Path): HTMLButtonElement | null {
  return host.querySelector<HTMLButtonElement>(
    `button[data-action="${action}"][data-path='${JSON.stringify(path)}']`,
  );
}

function clickAction(host: HTMLElement, action: string, path: Path): void {
  const target = button(host, action, path);
  if (!target) throw new Error(`no ${action} button at ${JSON.stringify(path)}`);
  target.click();
}

function slots(host: HTMLElement): HTMLElement[] {
  return [...host.querySelectorAll<HTMLElement>("[data-node-slot]")];
}

describe("<filter-group> action-button template cloning", () => {
  it("clones the server-rendered action button, keeping wiring attributes", () => {
    document.body.replaceChildren();
    const host = document.createElement("filter-group") as FilterGroupElement;
    host.setAttribute("model", "game");
    host.setAttribute("models", JSON.stringify(MODELS_BASE));
    const template = document.createElement("template");
    template.setAttribute("data-action-button-template", "");
    template.innerHTML = '<button type="button" class="from-server"></button>';
    host.appendChild(template);
    document.body.appendChild(host);

    const addCondition = button(host, "add-condition", []);
    expect(addCondition).not.toBeNull();
    expect(addCondition?.className).toBe("from-server");
    expect(addCondition?.textContent).toBe("+ condition");
    expect(addCondition?.type).toBe("button");
    // disabled/title still applied on the clone (root has no up/down, use wrap
    // on a nested child instead: add a group, whose child controls render)
    clickAction(host, "add-group", []);
    const up = button(host, "up", [1]);
    expect(up?.className).toBe("from-server");
    expect(up?.disabled).toBe(false);
    expect(up?.title).toBe("Move up");
  });

  it("falls back to a classless bare button without a template", () => {
    const host = mount();
    const addCondition = button(host, "add-condition", []);
    expect(addCondition).not.toBeNull();
    expect(addCondition?.className).toBe("");
  });
});

describe("<filter-group> chip and relation-select template cloning", () => {
  function mountWithControlTemplates(): FilterGroupElement {
    document.body.replaceChildren();
    const host = document.createElement("filter-group") as FilterGroupElement;
    host.setAttribute("model", "game");
    host.setAttribute("models", JSON.stringify(MODELS_BASE));
    for (const state of ["connective-and", "connective-or", "negate-on", "negate-off"]) {
      const template = document.createElement("template");
      template.setAttribute("data-chip-template", state);
      template.innerHTML = `<button type="button" class="chip-${state}"></button>`;
      host.appendChild(template);
    }
    const selectTemplate = document.createElement("template");
    selectTemplate.setAttribute("data-relation-select-template", "");
    selectTemplate.innerHTML = '<select class="select-from-server"></select>';
    host.appendChild(selectTemplate);
    document.body.appendChild(host);
    return host;
  }

  it("clones the state-matching chip template, keeping wiring attributes", () => {
    const host = mountWithControlTemplates();
    const connective = button(host, "toggle-connective", []);
    expect(connective?.className).toBe("chip-connective-and");
    expect(connective?.textContent).toBe("AND");
    const negate = button(host, "toggle-negate", []);
    expect(negate?.className).toBe("chip-negate-off");
    expect(negate?.getAttribute("aria-pressed")).toBe("false");

    clickAction(host, "toggle-connective", []);
    expect(button(host, "toggle-connective", [])?.className).toBe("chip-connective-or");
    clickAction(host, "toggle-negate", []);
    const negated = button(host, "toggle-negate", []);
    expect(negated?.className).toBe("chip-negate-on");
    expect(negated?.getAttribute("aria-pressed")).toBe("true");
  });

  it("clones the relation-select template for both relation-row selects", () => {
    const host = mountWithControlTemplates();
    clickAction(host, "add-relation", []);
    const match = host.querySelector<HTMLSelectElement>("[data-relation-match]");
    const field = host.querySelector<HTMLSelectElement>("[data-relation-field]");
    expect(match?.className).toBe("select-from-server");
    expect(field?.className).toBe("select-from-server");
    // Options are still the client's data: the quantifier choices arrive on the clone.
    expect(match?.options.length).toBeGreaterThan(0);
  });

  it("falls back to classless bare chips and selects without templates", () => {
    const host = mount();
    expect(button(host, "toggle-connective", [])?.className).toBe("");
    expect(button(host, "toggle-negate", [])?.className).toBe("");
    clickAction(host, "add-relation", []);
    expect(host.querySelector<HTMLSelectElement>("[data-relation-match]")?.className).toBe("");
  });
});

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

// ── Relation-descent block (component 5, #193) ──
// game → session relation + a session `name` field, with field-picker + widget
// templates for both models (namespaced by data-model) so the child group can be
// driven live in jsdom.
function mountRelation(): FilterGroupElement {
  document.body.replaceChildren();
  const host = document.createElement("filter-group") as FilterGroupElement;
  host.setAttribute("model", "game");
  host.setAttribute(
    "models",
    JSON.stringify({
      game: { fields: [SESSION_RELATION], columns: [] },
      session: { fields: [NAME_META], columns: [] },
    }),
  );
  host.innerHTML = `
    <template data-model="game" data-field-picker-template>
      <div data-field-picker><search-select name="field-picker"><input data-search-select-search /></search-select></div>
    </template>
    <template data-model="session" data-field-picker-template>
      <div data-field-picker><search-select name="field-picker"><input data-search-select-search /></search-select></div>
    </template>
    <template data-model="session" data-field="name">
      <div class="flex-col">
        <select data-string-modifier-select>
          <option value="EQUALS" selected>is</option>
          <option value="INCLUDES">includes</option>
        </select>
        <input type="text" />
      </div>
    </template>`;
  document.body.appendChild(host);
  return host;
}

function relationSelect(host: HTMLElement, path: Path, hook: string): HTMLSelectElement {
  return host.querySelector<HTMLSelectElement>(
    `[data-node-slot][data-path='${JSON.stringify(path)}'] [${hook}]`,
  )!;
}

function pickRelation(host: HTMLElement, path: Path, field: string): void {
  const select = relationSelect(host, path, "data-relation-field");
  select.value = field;
  select.dispatchEvent(new Event("change", { bubbles: true }));
}

function setRelationMatch(host: HTMLElement, path: Path, value: string): void {
  const select = relationSelect(host, path, "data-relation-match");
  select.value = value;
  select.dispatchEvent(new Event("change", { bubbles: true }));
}

function relationChildText(host: HTMLElement, path: Path): string {
  return (
    host.querySelector(`[data-kind="group"][data-path='${JSON.stringify(path)}']`)?.textContent ?? ""
  );
}

describe("<filter-group> relation descent (component 5, #193)", () => {
  it("+ relation adds a live accent block with quantifier + relation pickers", () => {
    const host = mountRelation();
    clickAction(host, "add-relation", []); // [0]=seed criterion, [1]=relation
    const card = slots(host).find((slot) => slot.dataset.nodeKind === "relation")!;
    expect(card.dataset.path).toBe(JSON.stringify([1]));
    expect(card.querySelector("[data-relation-match]")).not.toBeNull();
    expect(card.querySelector("[data-relation-field]")).not.toBeNull();
    // Unset field → incomplete until a relation is chosen.
    expect(card.querySelector("[data-incomplete-badge]")).not.toBeNull();
  });

  it("the quantifier picker lists ANY/NONE/ALL and defaults to ANY", () => {
    const host = mountRelation();
    clickAction(host, "add-relation", []);
    const match = relationSelect(host, [1], "data-relation-match");
    expect([...match.options].map((option) => option.value)).toEqual(["ANY", "NONE", "ALL"]);
    expect(match.value).toBe("ANY");
  });

  it("picking a relation opens a child group built from the target model", () => {
    const host = mountRelation();
    clickAction(host, "add-relation", []);
    pickRelation(host, [1], "session_filter");
    // The child group is addressable at [1,"child"] and offers its own footer.
    expect(host.querySelector(`[data-kind="group"][data-path='${JSON.stringify([1, "child"])}']`)).not.toBeNull();
    expect(button(host, "add-condition", [1, "child"])).not.toBeNull();
    // No longer incomplete once a relation is chosen (empty child = presence test).
    const card = slots(host).find((slot) => slot.dataset.nodeKind === "relation")!;
    expect(card.querySelector("[data-incomplete-badge]")).toBeNull();
  });

  it("serializeForQuery emits {relation:{match, …child}} with a live child leaf", () => {
    const host = mountRelation();
    clickAction(host, "add-relation", []);
    pickRelation(host, [1], "session_filter");
    relationSelect(host, [1], "data-relation-match").value = "ALL";
    relationSelect(host, [1], "data-relation-match").dispatchEvent(new Event("change", { bubbles: true }));
    clickAction(host, "add-condition", [1, "child"]); // child criterion at [1,"child",0]
    pickField(host, [1, "child", 0], NAME_META); // session's `name` field
    typeValue(host, [1, "child", 0], "Hades");
    expect(host.serializeForQuery()).toEqual({
      AND: [
        {
          session_filter: {
            match: "ALL",
            AND: [{ name: { value: "Hades", modifier: "EQUALS" } }],
          },
        },
      ],
    });
  });

  it("an unset relation is pruned from the query (never serializes to {\"\":…})", () => {
    const host = mountRelation();
    clickAction(host, "add-relation", []); // field still unset
    expect(host.serializeForQuery()).toEqual({}); // seed criterion + unset relation both pruned
  });

  it("NOT on the relation wraps the whole descent, keeping the live child leaf", () => {
    const host = mountRelation();
    clickAction(host, "add-relation", []);
    pickRelation(host, [1], "session_filter");
    clickAction(host, "toggle-negate", [1]); // negate the relation node
    clickAction(host, "add-condition", [1, "child"]);
    pickField(host, [1, "child", 0], NAME_META);
    typeValue(host, [1, "child", 0], "Hades");
    expect(host.serializeForQuery()).toEqual({
      AND: [
        { NOT: [{ session_filter: { AND: [{ name: { value: "Hades", modifier: "EQUALS" } }] } }] },
      ],
    });
  });

  it("counts a field-set/value-empty child leaf as incomplete under the target model", () => {
    const host = mountRelation();
    let last = -1;
    host.addEventListener("filter-tree-change", (event) => {
      last = (event as CustomEvent).detail.incompleteCount;
    });
    clickAction(host, "add-relation", []);
    clickAction(host, "remove", [0]); // drop the seed criterion so only the relation counts
    // The unset relation itself counts as incomplete (it would serialize to
    // `{"": …}`) — pinned here because no other test attributes a count to it.
    expect(last).toBe(1);
    pickRelation(host, [0], "session_filter"); // relation complete (field set)
    expect(last).toBe(0);
    clickAction(host, "add-condition", [0, "child"]);
    pickField(host, [0, "child", 0], NAME_META); // session `name` chosen, value still empty
    expect(last).toBe(1); // the child leaf is incomplete, resolved against the session bundle
    typeValue(host, [0, "child", 0], "Hades");
    expect(last).toBe(0);
  });

  it("does not offer + relation for a model with no relations", () => {
    const host = mountRelation();
    clickAction(host, "add-relation", []);
    pickRelation(host, [1], "session_filter");
    // session has no relation fields here → its child group shows no + relation.
    expect(button(host, "add-relation", [1, "child"])).toBeNull();
  });

  // #225: an empty relation child is an appliable presence test, but its intent must
  // be spelled out per quantifier so it is never applied silently.
  it("spells out the empty-child presence test, phrased for the active quantifier", () => {
    const host = mountRelation();
    clickAction(host, "add-relation", []);
    pickRelation(host, [1], "session_filter");
    // ANY (default): 1 or more.
    expect(relationChildText(host, [1, "child"])).toContain("1 or more related items");
    // NONE: 0.
    setRelationMatch(host, [1], "NONE");
    expect(relationChildText(host, [1, "child"])).toContain("0 related items");
    // ALL empty: matches all.
    setRelationMatch(host, [1], "ALL");
    expect(relationChildText(host, [1, "child"])).toContain("Matches all items");
    // Back to ANY restores the "1 or more" copy (the switch recomputes each render).
    setRelationMatch(host, [1], "ANY");
    expect(relationChildText(host, [1, "child"])).toContain("1 or more related items");
  });

  it("drops the empty-child presence-test copy once a real condition is added", () => {
    const host = mountRelation();
    clickAction(host, "add-relation", []);
    pickRelation(host, [1], "session_filter");
    expect(relationChildText(host, [1, "child"])).toContain("related items");
    clickAction(host, "add-condition", [1, "child"]);
    expect(relationChildText(host, [1, "child"])).not.toContain("related items");
  });

  // #225: the empty child the copy describes must actually survive to the query as a
  // presence test — a field-set relation is never pruned even with no sub-conditions.
  it("serializes a field-set empty relation child as a presence test (not pruned)", () => {
    const host = mountRelation();
    clickAction(host, "add-relation", []);
    pickRelation(host, [1], "session_filter"); // field set, child left empty
    // ANY is the default (omitted from the payload): a bare presence test.
    expect(host.serializeForQuery()).toEqual({ AND: [{ session_filter: {} }] });
    // The quantifier still rides along on an empty child.
    setRelationMatch(host, [1], "NONE");
    expect(host.serializeForQuery()).toEqual({ AND: [{ session_filter: { match: "NONE" } }] });
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

  // Color-by-value (teal AND / orange OR) is asserted via state-template
  // selection in the "chip and relation-select template cloning" suite —
  // the classes themselves are server-owned now (#273).

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
  host.setAttribute("models", JSON.stringify({ game: { fields: [NAME_META], columns: [] } }));
  // Templates must exist before connectedCallback (captureTemplates runs there),
  // tagged data-model so the multi-model builder buckets them (#193).
  host.innerHTML = `
    <template data-model="game" data-field-picker-template>
      <div data-field-picker><search-select name="field-picker"><input data-search-select-search /></search-select></div>
    </template>
    <template data-model="game" data-field="name">
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

function row(host: HTMLElement, path: Path): HTMLElement {
  return host.querySelector<HTMLElement>(
    `[data-node-slot][data-path='${JSON.stringify(path)}']`,
  )!;
}

function pickField(host: HTMLElement, path: Path, meta: object): void {
  const picker = row(host, path).querySelector<HTMLElement>("[data-field-picker]")!;
  picker.dispatchEvent(
    new CustomEvent("search-select:change", {
      bubbles: true,
      detail: { name: "field-picker", values: [], last: { data: { meta: JSON.stringify(meta) } } },
    }),
  );
}

function typeValue(host: HTMLElement, path: Path, text: string): void {
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
  host.setAttribute("models", JSON.stringify({ game: { fields: [], columns: COLUMNS } }));
  host.innerHTML = `
    <template data-model="game" data-fc-row-template>
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

function setSelect(host: HTMLElement, path: Path, hook: string, value: string): void {
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

// ── Initial dispatch on connect (#196) ──
describe("<filter-group> initial filter-tree-change on connect (prefill sync)", () => {
  it("dispatches filter-tree-change on connectedCallback when a filter prop is present", () => {
    document.body.innerHTML = "";
    const events: CustomEvent[] = [];
    const prefillFilter = JSON.stringify({ AND: [{ status: { modifier: "INCLUDES", value: "f" } }] });
    // Attach the listener BEFORE appending the element — the group is the last sibling
    // in a real page, so all sibling listeners are already attached when it connects.
    document.addEventListener(FILTER_TREE_CHANGE_EVENT, (event) => {
      events.push(event as CustomEvent);
    });
    const group = document.createElement("filter-group") as FilterGroupElement;
    group.setAttribute("model", "game");
    group.setAttribute("models", MODELS);
    group.setAttribute("filter", prefillFilter);
    document.body.appendChild(group); // connectedCallback fires here
    expect(events.length).toBeGreaterThanOrEqual(1);
    // The dispatched event must carry the seeded (non-empty) tree
    const detail = events[0].detail as { tree: { children: unknown[] } };
    expect(detail.tree.children.length).toBeGreaterThan(0);
  });
});

// ── comp-10 additions: prefill + loadFilter/clear/getFilledTree (#196) ──
// Minimal two-model registry: game.status (a set field with choices) +
// game.sessions (relation -> session). Field shape mirrors the real FieldMeta
// (ts/generated/filter-metadata.ts): kind ∈ string|number|date|bool|set|relation|
// field-comparison; choices are {value,label} OBJECTS (NOT tuples); modifiers,
// search_url, is_m2m are present. relations[].model is the target Django model
// name ("Session"), lower-cased into the registry by buildRegistry.
const STATUS_FIELD = {
  name: "status", label: "Status", kind: "set", nullable: false,
  choices: [{ value: "f", label: "Finished" }], relations: [],
  modifiers: ["INCLUDES", "EXCLUDES"], search_url: "", is_m2m: false,
};
const SESSIONS_FIELD = {
  name: "sessions", label: "Sessions", kind: "relation", nullable: false,
  choices: [], relations: [{ field: "sessions", label: "Sessions", model: "Session" }],
  modifiers: [], search_url: "", is_m2m: false,
};
const MODELS = JSON.stringify({
  game: { fields: [STATUS_FIELD, SESSIONS_FIELD], columns: [] },
  session: { fields: [], columns: [] },
});

function mountGroup(filter = ""): FilterGroupElement {
  document.body.innerHTML = "";
  const group = document.createElement("filter-group") as FilterGroupElement;
  group.setAttribute("model", "game");
  group.setAttribute("models", MODELS);
  if (filter) group.setAttribute("filter", filter);
  document.body.appendChild(group);
  return group;
}

describe("filter-group comp-10 additions", () => {
  it("seeds the tree from the filter prop on connect", () => {
    const group = mountGroup(JSON.stringify({ AND: [{ status: { modifier: "EQUALS", value: "f" } }] }));
    expect(group.serialize()).toEqual({ AND: [{ status: { modifier: "EQUALS", value: "f" } }] });
  });

  it("loadFilter replaces the tree and clear empties it", () => {
    const group = mountGroup();
    group.loadFilter({ AND: [{ status: { modifier: "EQUALS", value: "f" } }] });
    expect(group.serialize()).toEqual({ AND: [{ status: { modifier: "EQUALS", value: "f" } }] });
    group.clear();
    expect(group.serialize()).toEqual({});
  });

  it("imports a negated-empty root without throwing (serializes to {})", () => {
    const group = mountGroup(JSON.stringify({ NOT: [{ AND: [] }] }));
    // A negated empty root is "matches all": serialize drops the empty group.
    expect(group.serialize()).toEqual({});
    expect(() => group.getFilledTree()).not.toThrow();
  });

  it("getFilledTree keeps incomplete leaves (unpruned)", () => {
    const group = mountGroup();
    group.loadFilter({ AND: [{ status: { modifier: "EQUALS", value: "f" } }] });
    const filled = group.getFilledTree();
    expect(filled.kind).toBe("group");
    expect(filled.children.length).toBe(1);
  });
});

// ── Regression: loadFilter with a set field must not throw (#196 fix) ──
// Before the fix, leafCells() called showFieldSelection() on a freshly-cloned
// <search-select> that was still DETACHED (not yet upgraded → connectedCallback
// had not run → setSelected did not exist). The ?. guard in showFieldSelection
// silences null, NOT a missing method, so "searchSelect?.setSelected is not a
// function" was thrown, propagating through loadFilter to onPresetPicked which
// swallowed it and showed "Preset is not a valid filter."
//
// The fix moves showFieldSelection into reflectFieldSelections(), called AFTER
// replaceChildren() so every cloned <search-select> is live and upgraded.
function mountWithFieldPickerTemplate(): FilterGroupElement {
  document.body.innerHTML = "";
  const group = document.createElement("filter-group") as FilterGroupElement;
  group.setAttribute("model", "game");
  group.setAttribute("models", MODELS);
  // Supply a field-picker template that contains a real <search-select> — this is
  // what FilterFieldPicker (common/components/filters.py) emits. When leafCells()
  // clones it during the detached renderGroup() pass the element is NOT upgraded.
  group.innerHTML = `
    <template data-model="game" data-field-picker-template>
      <div data-field-picker>
        <search-select name="field-picker">
          <input data-search-select-search />
        </search-select>
      </div>
    </template>
    <template data-model="game" data-field="status">
      <div>
        <select data-modifier-select>
          <option value="INCLUDES" selected>includes</option>
          <option value="EXCLUDES">excludes</option>
        </select>
      </div>
    </template>`;
  document.body.appendChild(group);
  return group;
}

describe("loadFilter with a set field — regression for #196 crash", () => {
  it("does NOT throw when loadFilter introduces a criterion with a set field", () => {
    // Before the fix this threw "searchSelect?.setSelected is not a function"
    // because the cloned <search-select> was not yet upgraded when leafCells()
    // called showFieldSelection() during the detached renderGroup() pass.
    const group = mountWithFieldPickerTemplate();
    expect(() =>
      group.loadFilter({
        AND: [{ status: { modifier: "INCLUDES", value: [{ id: "f", label: "Finished" }] } }],
      }),
    ).not.toThrow();
  });

  it("after loadFilter the criterion leaf shows the set field selected in the picker", () => {
    const group = mountWithFieldPickerTemplate();
    group.loadFilter({
      AND: [{ status: { modifier: "INCLUDES", value: [{ id: "f", label: "Finished" }] } }],
    });
    // The leaf row at [0] must show the status field — the field-picker's
    // <search-select> should have setSelected("status", "Status") called on it.
    // Since jsdom does not fully upgrade custom elements (no shadow DOM), we verify
    // indirectly: the leaf's cached cells have cells.field === "status", meaning the
    // tree was applied and the value cell was built for the right field.
    const leafRow = group.querySelector<HTMLElement>('[data-node-slot][data-node-kind="criterion"]');
    expect(leafRow).not.toBeNull();
    // The value cell should be present and hold the status widget (not the placeholder).
    const valueCell = leafRow!.querySelector("[data-value-cell]");
    expect(valueCell).not.toBeNull();
    // The placeholder text "Choose a field…" must be gone — the field is set.
    expect(valueCell!.textContent).not.toContain("Choose a field");
  });

  it("loadFilter via filter prop on connect also does not throw", () => {
    document.body.innerHTML = "";
    const group = document.createElement("filter-group") as FilterGroupElement;
    group.setAttribute("model", "game");
    group.setAttribute("models", MODELS);
    group.setAttribute(
      "filter",
      JSON.stringify({
        AND: [{ status: { modifier: "INCLUDES", value: [{ id: "f", label: "Finished" }] } }],
      }),
    );
    group.innerHTML = `
      <template data-model="game" data-field-picker-template>
        <div data-field-picker>
          <search-select name="field-picker"><input data-search-select-search /></search-select>
        </div>
      </template>
      <template data-model="game" data-field="status">
        <div><select data-modifier-select><option value="INCLUDES" selected>includes</option></select></div>
      </template>`;
    // connectedCallback calls deserialize + render — must not throw.
    expect(() => document.body.appendChild(group)).not.toThrow();
  });
});

// ── Prefill hydration of leaf value widgets (#263) ──
// Loading a filter (preset / ?filter= import) must write each leaf's stored
// criterion INTO its cloned value widget, because serializeForQuery() reads the
// live widgets — before #263 a prefilled filter round-tripped as {} (match all).
// One model with a field of every widget kind, each widget template mirroring the
// data hooks of its Python builder (StringFilter / NumberFilter / DateRangeField /
// _bool_control / FilterSelect), plus comparison columns for the comparison leaf.
const HYDRATION_FIELDS = [
  {
    name: "name", label: "Name", kind: "string", nullable: true, choices: [],
    modifiers: ["EQUALS", "INCLUDES", "IS_NULL"], relations: [], search_url: "", is_m2m: false,
  },
  {
    name: "year", label: "Year", kind: "number", nullable: true, choices: [],
    modifiers: ["EQUALS", "GREATER_THAN", "BETWEEN", "IS_NULL"], relations: [], search_url: "", is_m2m: false,
  },
  {
    name: "released", label: "Released", kind: "date", nullable: false, choices: [],
    modifiers: [], relations: [], search_url: "", is_m2m: false,
  },
  {
    name: "mastered", label: "Mastered", kind: "bool", nullable: false, choices: [],
    modifiers: ["EQUALS"], relations: [], search_url: "", is_m2m: false,
  },
  {
    name: "status", label: "Status", kind: "set", nullable: true,
    choices: [{ value: "f", label: "Finished" }, { value: "u", label: "Unplayed" }],
    modifiers: ["INCLUDES", "EXCLUDES"], relations: [], search_url: "", is_m2m: false,
  },
];
// Relation chain for prefill: game → session → playevent, so a nested-relation
// filter (the stats "View all" URL shape — purchase → game → playevent in
// production, transposed onto the harness models) is expressible here.
const PLAYEVENT_RELATION = {
  name: "playevent_filter",
  label: "PlayEvents",
  kind: "relation",
  nullable: false,
  choices: [],
  modifiers: [],
  relations: [{ field: "playevent_filter", filter: "PlayEventFilter", model: "PlayEvent" }],
  search_url: "",
  is_m2m: false,
};
const ENDED_META = {
  name: "ended", label: "Ended", kind: "date", nullable: false, choices: [],
  modifiers: [], relations: [], search_url: "", is_m2m: false,
};
const SESSION_NAME_META = {
  name: "name", label: "Name", kind: "string", nullable: false, choices: [],
  modifiers: ["EQUALS", "INCLUDES"], relations: [], search_url: "", is_m2m: false,
};
const HYDRATION_MODELS = JSON.stringify({
  game: { fields: [...HYDRATION_FIELDS, SESSION_RELATION], columns: COLUMNS },
  session: { fields: [SESSION_NAME_META, PLAYEVENT_RELATION], columns: [] },
  playevent: { fields: [ENDED_META], columns: [] },
});
// The per-kind widget templates. Segment inputs carry the dual hidden-input
// attributes (data-date-range-hidden + data-range-min/max) exactly like
// DateRangeField; the set widget carries the pill/option/modifier-row markup and
// the pill <template>s FilterSelect always ships.
const HYDRATION_TEMPLATES = `
  <template data-model="game" data-field-picker-template>
    <div data-field-picker><search-select name="field-picker"><input data-search-select-search /></search-select></div>
  </template>
  <template data-model="game" data-field="name">
    <div class="flex-col">
      <select data-string-modifier-select>
        <option value="EQUALS" selected>is</option>
        <option value="INCLUDES">includes</option>
        <option value="IS_NULL">is empty</option>
      </select>
      <input type="text" />
    </div>
  </template>
  <template data-model="game" data-field="year">
    <div class="flex-col">
      <select data-number-modifier-select>
        <option value="EQUALS" selected>=</option>
        <option value="GREATER_THAN">&gt;</option>
        <option value="BETWEEN">between</option>
        <option value="IS_NULL">is empty</option>
      </select>
      <div>
        <input type="number" />
        <input type="number" data-number-value2 class="hidden" />
      </div>
    </div>
  </template>
  <template data-model="game" data-field="released">
    <div>
      <input type="hidden" data-date-range-hidden="min" data-range-min />
      <input type="hidden" data-date-range-hidden="max" data-range-max />
      <input data-date-side="min" data-date-part="day" maxlength="2" placeholder="dd" />
      <input data-date-side="min" data-date-part="month" maxlength="2" placeholder="mm" />
      <input data-date-side="min" data-date-part="year" maxlength="4" placeholder="yyyy" />
      <input data-date-side="max" data-date-part="day" maxlength="2" placeholder="dd" />
      <input data-date-side="max" data-date-part="month" maxlength="2" placeholder="mm" />
      <input data-date-side="max" data-date-part="year" maxlength="4" placeholder="yyyy" />
    </div>
  </template>
  <template data-model="game" data-field="mastered">
    <div>
      <label><input type="radio" name="mastered" value="true" />True</label>
      <label><input type="radio" name="mastered" value="false" />False</label>
    </div>
  </template>
  <template data-model="game" data-field="status">
    <search-select filter-mode="true">
      <div data-search-select-pills></div>
      <input data-search-select-search />
      <div>
        <div data-search-select-modifier-option="NOT_NULL" data-label="(Any)">(Any)</div>
        <div data-search-select-modifier-option="IS_NULL" data-label="(None)">(None)</div>
        <div data-search-select-option data-value="f" data-label="Finished"><span data-search-select-label>Finished</span></div>
        <div data-search-select-option data-value="u" data-label="Unplayed"><span data-search-select-label>Unplayed</span></div>
      </div>
      <template data-search-select-template="pill-include"><span data-pill data-value="" data-label="" data-search-select-type="include">✓ <span data-search-select-label></span><button data-pill-remove>×</button></span></template>
      <template data-search-select-template="pill-exclude"><span data-pill data-value="" data-label="" data-search-select-type="exclude">✗ <span data-search-select-label></span><button data-pill-remove>×</button></span></template>
      <template data-search-select-template="pill-modifier"><span data-pill data-search-select-modifier=""><span data-search-select-label></span><button data-pill-remove>×</button></span></template>
    </search-select>
  </template>
  <template data-model="game" data-fc-row-template>
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
  </template>
  <template data-model="session" data-field-picker-template>
    <div data-field-picker><search-select name="field-picker"><input data-search-select-search /></search-select></div>
  </template>
  <template data-model="session" data-field="name">
    <div class="flex-col">
      <select data-string-modifier-select>
        <option value="EQUALS" selected>is</option>
        <option value="INCLUDES">includes</option>
      </select>
      <input type="text" />
    </div>
  </template>
  <template data-model="playevent" data-field-picker-template>
    <div data-field-picker><search-select name="field-picker"><input data-search-select-search /></search-select></div>
  </template>
  <template data-model="playevent" data-field="ended">
    <div>
      <input type="hidden" data-date-range-hidden="min" data-range-min />
      <input type="hidden" data-date-range-hidden="max" data-range-max />
      <input data-date-side="min" data-date-part="day" maxlength="2" placeholder="dd" />
      <input data-date-side="min" data-date-part="month" maxlength="2" placeholder="mm" />
      <input data-date-side="min" data-date-part="year" maxlength="4" placeholder="yyyy" />
      <input data-date-side="max" data-date-part="day" maxlength="2" placeholder="dd" />
      <input data-date-side="max" data-date-part="month" maxlength="2" placeholder="mm" />
      <input data-date-side="max" data-date-part="year" maxlength="4" placeholder="yyyy" />
    </div>
  </template>`;

function mountHydration(filter = ""): FilterGroupElement {
  document.body.innerHTML = "";
  const host = document.createElement("filter-group") as FilterGroupElement;
  host.setAttribute("model", "game");
  host.setAttribute("models", HYDRATION_MODELS);
  if (filter) host.setAttribute("filter", filter);
  host.innerHTML = HYDRATION_TEMPLATES;
  document.body.appendChild(host);
  return host;
}

// Mount + loadFilter (the preset path) in one step. The ?filter=-prop path is
// covered separately — both funnel into deserialize() + render().
function loadHydration(filter: Record<string, unknown>): FilterGroupElement {
  const host = mountHydration();
  host.loadFilter(filter);
  return host;
}

function valueCell(host: HTMLElement, path: Path): HTMLElement {
  return row(host, path).querySelector<HTMLElement>("[data-value-cell]")!;
}

describe("<filter-group> prefill hydrates leaf value widgets (#263)", () => {
  it("string: writes modifier + value and round-trips serializeForQuery", () => {
    const filter = { AND: [{ name: { value: "Hades", modifier: "INCLUDES" } }] };
    const host = loadHydration(filter);
    const cell = valueCell(host, [0]);
    expect(cell.querySelector<HTMLSelectElement>("[data-string-modifier-select]")!.value).toBe("INCLUDES");
    expect(cell.querySelector<HTMLInputElement>('input[type="text"]')!.value).toBe("Hades");
    expect(host.serializeForQuery()).toEqual(filter);
  });

  it("string presence (IS_NULL): disables the text input and round-trips {modifier} only", () => {
    const filter = { AND: [{ name: { modifier: "IS_NULL" } }] };
    const host = loadHydration(filter);
    const input = valueCell(host, [0]).querySelector<HTMLInputElement>('input[type="text"]')!;
    expect(input.disabled).toBe(true);
    expect(input.value).toBe("");
    expect(host.serializeForQuery()).toEqual(filter);
  });

  it("number GREATER_THAN: writes the value and round-trips", () => {
    const filter = { AND: [{ year: { value: 1990, modifier: "GREATER_THAN" } }] };
    const host = loadHydration(filter);
    const cell = valueCell(host, [0]);
    expect(cell.querySelector<HTMLInputElement>('input[type="number"]:not([data-number-value2])')!.value).toBe("1990");
    expect(host.serializeForQuery()).toEqual(filter);
  });

  it("number BETWEEN: reveals value2, writes both bounds, and round-trips", () => {
    const filter = { AND: [{ year: { value: 2000, value2: 2010, modifier: "BETWEEN" } }] };
    const host = loadHydration(filter);
    const cell = valueCell(host, [0]);
    const value2 = cell.querySelector<HTMLInputElement>("[data-number-value2]")!;
    expect(value2.classList.contains("hidden")).toBe(false); // BETWEEN reveals value2
    expect(value2.value).toBe("2010");
    expect(host.serializeForQuery()).toEqual(filter);
  });

  it("date BETWEEN: writes hidden bounds + visible segments and round-trips", () => {
    const filter = { AND: [{ released: { value: "2020-01-05", value2: "2021-12-31", modifier: "BETWEEN" } }] };
    const host = loadHydration(filter);
    const cell = valueCell(host, [0]);
    expect(cell.querySelector<HTMLInputElement>("[data-range-min]")!.value).toBe("2020-01-05");
    expect(cell.querySelector<HTMLInputElement>("[data-range-max]")!.value).toBe("2021-12-31");
    // Segments display the split ISO pieces (what initField adopts at connect).
    expect(cell.querySelector<HTMLInputElement>('[data-date-side="min"][data-date-part="year"]')!.value).toBe("2020");
    expect(cell.querySelector<HTMLInputElement>('[data-date-side="min"][data-date-part="day"]')!.value).toBe("05");
    expect(cell.querySelector<HTMLInputElement>('[data-date-side="max"][data-date-part="month"]')!.value).toBe("12");
    expect(host.serializeForQuery()).toEqual(filter);
  });

  it("date LESS_THAN: the single bound fills the max side (min stays empty) and round-trips", () => {
    const filter = { AND: [{ released: { value: "2021-06-30", modifier: "LESS_THAN" } }] };
    const host = loadHydration(filter);
    const cell = valueCell(host, [0]);
    expect(cell.querySelector<HTMLInputElement>("[data-range-min]")!.value).toBe("");
    expect(cell.querySelector<HTMLInputElement>("[data-range-max]")!.value).toBe("2021-06-30");
    expect(host.serializeForQuery()).toEqual(filter);
  });

  it("date EQUALS: hydrates as the exactly-equivalent same-day range", () => {
    // DateCriterion EQUALS(d) and BETWEEN(d, d) compile to the same rows
    // (criteria.py — every datetime field filters via a __date lookup), so the
    // min/max widget represents EQUALS as d..d and serializes BETWEEN.
    const host = loadHydration({ AND: [{ released: { value: "2020-01-05", modifier: "EQUALS" } }] });
    const cell = valueCell(host, [0]);
    expect(cell.querySelector<HTMLInputElement>("[data-range-min]")!.value).toBe("2020-01-05");
    expect(cell.querySelector<HTMLInputElement>("[data-range-max]")!.value).toBe("2020-01-05");
    expect(host.serializeForQuery()).toEqual({
      AND: [{ released: { value: "2020-01-05", value2: "2020-01-05", modifier: "BETWEEN" } }],
    });
  });

  it("date NOT_BETWEEN: hydrates blank (pruned) instead of rewriting to the complement range", () => {
    // NOT_BETWEEN is two open rays — no faithful min/max form. Writing the
    // bounds would read back as BETWEEN (the exact complement), so the widget
    // stays blank and the leaf prunes, like before hydration existed.
    const host = loadHydration({
      AND: [{ released: { value: "2020-01-01", value2: "2020-12-31", modifier: "NOT_BETWEEN" } }],
    });
    const cell = valueCell(host, [0]);
    expect(cell.querySelector<HTMLInputElement>("[data-range-min]")!.value).toBe("");
    expect(cell.querySelector<HTMLInputElement>("[data-range-max]")!.value).toBe("");
    expect(host.serializeForQuery()).toEqual({});
  });

  it("bool: checks the matching radio and round-trips", () => {
    const filter = { AND: [{ mastered: { value: true, modifier: "EQUALS" } }] };
    const host = loadHydration(filter);
    const cell = valueCell(host, [0]);
    expect(cell.querySelector<HTMLInputElement>('input[type="radio"][value="true"]')!.checked).toBe(true);
    expect(cell.querySelector<HTMLInputElement>('input[type="radio"][value="false"]')!.checked).toBe(false);
    expect(host.serializeForQuery()).toEqual(filter);
  });

  it("set: renders include + exclude pills and round-trips", () => {
    const filter = {
      AND: [{
        status: {
          value: [{ id: "f", label: "Finished" }],
          excludes: [{ id: "u", label: "Unplayed" }],
          modifier: "INCLUDES",
        },
      }],
    };
    const host = loadHydration(filter);
    const pills = valueCell(host, [0]).querySelectorAll<HTMLElement>("[data-pill]");
    expect([...pills].map((pill) => pill.getAttribute("data-search-select-type"))).toEqual([
      "include",
      "exclude",
    ]);
    expect(pills[0].getAttribute("data-value")).toBe("f");
    expect(pills[0].textContent).toContain("Finished");
    expect(host.serializeForQuery()).toEqual(filter);
  });

  it("set EXCLUDES: values hydrate as exclude pills, never inverted into includes", () => {
    // {modifier: EXCLUDES, value: [X]} compiles to exactly ~Q(field__in=[X]) —
    // identical to INCLUDES + excludes (criteria.py _value_q/to_q) — so the
    // widget's exclude channel is the faithful representation.
    const host = loadHydration({ AND: [{ status: { modifier: "EXCLUDES", value: ["f"] } }] });
    const pill = valueCell(host, [0]).querySelector<HTMLElement>("[data-pill]")!;
    expect(pill.getAttribute("data-search-select-type")).toBe("exclude");
    expect(pill.getAttribute("data-label")).toBe("Finished");
    expect(host.serializeForQuery()).toEqual({
      AND: [{
        status: { value: [], excludes: [{ id: "f", label: "Finished" }], modifier: "INCLUDES" },
      }],
    });
  });

  it("set: a control character in a URL-authored id neither throws nor aborts the render", () => {
    // A raw newline in a CSS string is a parse error; the option-row label
    // lookup must escape it (CSS.escape), not crash the whole builder page.
    const host = loadHydration({ AND: [{ status: { modifier: "INCLUDES", value: ["f\nx"] } }] });
    const pill = valueCell(host, [0]).querySelector<HTMLElement>("[data-pill]")!;
    expect(pill.getAttribute("data-value")).toBe("f\nx");
    expect(host.serializeForQuery()).toEqual({
      AND: [{
        status: { value: [{ id: "f\nx", label: "f\nx" }], excludes: [], modifier: "INCLUDES" },
      }],
    });
  });

  it("set presence modifier: renders the sticky modifier pill and round-trips {modifier} only", () => {
    const filter = { AND: [{ status: { modifier: "NOT_NULL" } }] };
    const host = loadHydration(filter);
    const pill = valueCell(host, [0]).querySelector<HTMLElement>("[data-pill][data-search-select-modifier]")!;
    expect(pill.getAttribute("data-search-select-modifier")).toBe("NOT_NULL");
    expect(pill.textContent).toContain("(Any)");
    expect(host.serializeForQuery()).toEqual(filter);
  });

  it("set with bare string ids (URL-authored JSON) enriches labels from the option rows", () => {
    // The e2e prefill fixture shape: {"status": {"modifier": "INCLUDES", "value": ["f"]}}
    const host = loadHydration({ AND: [{ status: { modifier: "INCLUDES", value: ["f"] } }] });
    const pill = valueCell(host, [0]).querySelector<HTMLElement>("[data-pill]")!;
    expect(pill.getAttribute("data-label")).toBe("Finished");
    expect(host.serializeForQuery()).toEqual({
      AND: [{
        status: { value: [{ id: "f", label: "Finished" }], excludes: [], modifier: "INCLUDES" },
      }],
    });
  });

  it("comparison: restores left/operator/right and round-trips", () => {
    const filter = {
      AND: [{
        field_comparisons: [
          { left: "year_released", right: "original_year_released", modifier: "LESS_THAN" },
        ],
      }],
    };
    const host = loadHydration(filter);
    const cell = valueCell(host, [0]);
    expect(cell.querySelector<HTMLSelectElement>("[data-fc-left]")!.value).toBe("year_released");
    expect(cell.querySelector<HTMLSelectElement>("[data-fc-op]")!.value).toBe("LESS_THAN");
    expect(cell.querySelector<HTMLSelectElement>("[data-fc-right]")!.value).toBe("original_year_released");
    expect(host.serializeForQuery()).toEqual(filter);
  });

  it("comparison with granularity: restores the by-day toggle and round-trips", () => {
    const filter = {
      AND: [{
        field_comparisons: [
          { left: "created_at", right: "updated_at", modifier: "LESS_THAN", granularity: "date" },
        ],
      }],
    };
    const host = loadHydration(filter);
    const byDay = valueCell(host, [0]).querySelector<HTMLInputElement>("[data-fc-granularity]")!;
    expect(byDay.checked).toBe(true);
    expect(host.serializeForQuery()).toEqual(filter);
  });

  it("hydrates via the ?filter= prop on connect too (the builder-page path)", () => {
    const filter = { AND: [{ name: { value: "Hades", modifier: "EQUALS" } }] };
    const host = mountHydration(JSON.stringify(filter));
    expect(valueCell(host, [0]).querySelector<HTMLInputElement>('input[type="text"]')!.value).toBe("Hades");
    expect(host.serializeForQuery()).toEqual(filter);
  });

  it("a user edit after hydration wins and survives a structural re-render", () => {
    const host = loadHydration({ AND: [{ name: { value: "Hades", modifier: "EQUALS" } }] });
    typeValue(host, [0], "Celeste");
    clickAction(host, "add-condition", []); // structural re-render reuses the cached cell
    expect(row(host, [0]).querySelector<HTMLInputElement>('[data-value-cell] input[type="text"]')!.value).toBe("Celeste");
    // The new empty leaf is pruned; the edited value — not the hydrated one — serializes.
    expect(host.serializeForQuery()).toEqual({ AND: [{ name: { value: "Celeste", modifier: "EQUALS" } }] });
  });

  it("re-picking a different field yields a blank widget (no stale hydration)", () => {
    const host = loadHydration({ AND: [{ name: { value: "Hades", modifier: "EQUALS" } }] });
    pickField(host, [0], HYDRATION_FIELDS[1]); // name → year
    const numberInput = valueCell(host, [0]).querySelector<HTMLInputElement>('input[type="number"]:not([data-number-value2])')!;
    expect(numberInput.value).toBe("");
    expect(host.serializeForQuery()).toEqual({}); // incomplete leaf → pruned
  });

  it("string: an untrimmed stored value hydrates trimmed, matching the read side", () => {
    const host = loadHydration({ AND: [{ name: { value: " Hades ", modifier: "EQUALS" } }] });
    expect(valueCell(host, [0]).querySelector<HTMLInputElement>('input[type="text"]')!.value).toBe("Hades");
    expect(host.serializeForQuery()).toEqual({ AND: [{ name: { value: "Hades", modifier: "EQUALS" } }] });
  });

  it("duplicate copies the leaf's CURRENT value, not the stale prefill snapshot", () => {
    const host = loadHydration({ AND: [{ name: { value: "Hades", modifier: "EQUALS" } }] });
    typeValue(host, [0], "Celeste"); // live edit — the stored tree still says "Hades"
    clickAction(host, "duplicate", [0]);
    expect(host.serializeForQuery()).toEqual({
      AND: [
        { name: { value: "Celeste", modifier: "EQUALS" } },
        { name: { value: "Celeste", modifier: "EQUALS" } },
      ],
    });
  });

  it("duplicate after clearing a prefilled value stays blank (deleted values never resurrect)", () => {
    const host = loadHydration({ AND: [{ name: { value: "Hades", modifier: "EQUALS" } }] });
    typeValue(host, [0], ""); // the user deletes the prefilled value
    clickAction(host, "duplicate", [0]);
    const inputs = [...host.querySelectorAll<HTMLInputElement>('[data-value-cell] input[type="text"]')];
    expect(inputs.map((input) => input.value)).toEqual(["", ""]);
    expect(host.serializeForQuery()).toEqual({}); // both leaves incomplete → pruned
  });
});

// ── Prefill of relation subtrees ──
// A prefilled filter whose top-level key is a relation (the stats "View all" →
// Advanced filter URL shape) must deserialize into a RelationNode with its nested
// child group intact — not a criterion leaf that swallows the subtree and renders
// one "Incomplete" row. Regression: buildRegistry() used to put relation-kind
// fields in the registry's `fields` set, and deserialize resolves criterion-first.
describe("<filter-group> prefill hydrates relation subtrees", () => {
  it("single relation: renders the relation row + hydrated child criterion", () => {
    const filter = {
      AND: [{ session_filter: { AND: [{ name: { value: "Hades", modifier: "EQUALS" } }] } }],
    };
    const host = loadHydration(filter);
    const card = row(host, [0]);
    expect(card.dataset.nodeKind).toBe("relation");
    expect(relationSelect(host, [0], "data-relation-field").value).toBe("session_filter");
    expect(card.querySelector("[data-incomplete-badge]")).toBeNull();
    const input = valueCell(host, [0, "child", 0]).querySelector<HTMLInputElement>('input[type="text"]')!;
    expect(input.value).toBe("Hades");
    expect(host.getIncompleteCount()).toBe(0);
    expect(host.serializeForQuery()).toEqual(filter);
  });

  it("nested relation (stats View-all URL shape): full subtree hydrates and round-trips", () => {
    // Mirrors ?filter={"game_filter":{"playevent_filter":{"ended":{…BETWEEN…}}}}
    // from the bug report, expressed in the harness's game→session→playevent chain.
    const host = loadHydration({
      session_filter: {
        playevent_filter: {
          ended: { value: "2026-01-01", modifier: "BETWEEN", value2: "2026-12-31" },
        },
      },
    });
    const outer = row(host, [0]);
    expect(outer.dataset.nodeKind).toBe("relation");
    expect(relationSelect(host, [0], "data-relation-field").value).toBe("session_filter");
    expect(outer.querySelector("[data-incomplete-badge]")).toBeNull();
    const inner = row(host, [0, "child", 0]);
    expect(inner.dataset.nodeKind).toBe("relation");
    expect(relationSelect(host, [0, "child", 0], "data-relation-field").value).toBe("playevent_filter");
    const dateCell = valueCell(host, [0, "child", 0, "child", 0]);
    expect(dateCell.querySelector<HTMLInputElement>("[data-range-min]")!.value).toBe("2026-01-01");
    expect(dateCell.querySelector<HTMLInputElement>("[data-range-max]")!.value).toBe("2026-12-31");
    expect(host.getIncompleteCount()).toBe(0);
    // The canonical form: groups keep their connective wrapper, default ANY match omitted.
    expect(host.serializeForQuery()).toEqual({
      AND: [{
        session_filter: {
          AND: [{
            playevent_filter: {
              AND: [{ ended: { value: "2026-01-01", modifier: "BETWEEN", value2: "2026-12-31" } }],
            },
          }],
        },
      }],
    });
  });

  it("a relation field with no target stays a fail-visible criterion, never a relations entry", () => {
    // Malformed metadata (server-side unreachable: field_metadata hard-fails on
    // a target-less relation). Pins buildRegistry's else-branch: the name lands
    // in the criterion set → an Incomplete row that prunes, NOT a bogus
    // relations entry whose undefined target would throw UNKNOWN_MODEL and
    // fail the whole prefill open to an empty match-all builder.
    document.body.innerHTML = "";
    const host = document.createElement("filter-group") as FilterGroupElement;
    host.setAttribute("model", "game");
    host.setAttribute(
      "models",
      JSON.stringify({
        game: {
          fields: [{
            name: "broken_filter", label: "Broken", kind: "relation", nullable: false,
            choices: [], modifiers: [], relations: [], search_url: "", is_m2m: false,
          }],
          columns: [],
        },
      }),
    );
    host.setAttribute(
      "filter",
      JSON.stringify({ broken_filter: { name: { value: "x", modifier: "EQUALS" } } }),
    );
    document.body.appendChild(host);
    const card = row(host, [0]);
    expect(card.dataset.nodeKind).toBe("criterion");
    expect(card.querySelector("[data-incomplete-badge]")).not.toBeNull();
    expect(host.serializeForQuery()).toEqual({}); // incomplete → pruned
  });
});

// ── Aggregate scope (#151) ──
// game has one aggregate field (session_count, scope over session) plus a plain
// string field to prove non-scopable fields never offer "+ scope"; session brings
// its own picker + one string widget so the scope group's rows can be driven live.
const SESSION_COUNT_META = {
  name: "session_count",
  label: "Session Count",
  kind: "number",
  nullable: false,
  choices: [],
  modifiers: ["EQUALS", "GREATER_THAN"],
  relations: [],
  search_url: "",
  is_m2m: false,
  scope_model: "session",
};

const SCOPE_NOTE_META = { ...NAME_META, name: "note", label: "Note" };

function mountScope(): FilterGroupElement {
  document.body.replaceChildren();
  const host = document.createElement("filter-group") as FilterGroupElement;
  host.setAttribute("model", "game");
  host.setAttribute(
    "models",
    JSON.stringify({
      game: { fields: [SESSION_COUNT_META, NAME_META], columns: [] },
      session: { fields: [SCOPE_NOTE_META], columns: [] },
    }),
  );
  host.innerHTML = `
    <template data-model="game" data-field-picker-template>
      <div data-field-picker><search-select name="field-picker"><input data-search-select-search /></search-select></div>
    </template>
    <template data-model="session" data-field-picker-template>
      <div data-field-picker><search-select name="field-picker"><input data-search-select-search /></search-select></div>
    </template>
    <template data-model="game" data-field="session_count">
      <div class="flex-col">
        <select data-number-modifier-select>
          <option value="EQUALS" selected>=</option>
          <option value="GREATER_THAN">&gt;</option>
        </select>
        <div>
          <input type="number" />
          <input type="number" data-number-value2 class="hidden" />
        </div>
      </div>
    </template>
    <template data-model="game" data-field="name">
      <div class="flex-col">
        <select data-string-modifier-select><option value="EQUALS" selected>is</option></select>
        <input type="text" />
      </div>
    </template>
    <template data-model="session" data-field="note">
      <div class="flex-col">
        <select data-string-modifier-select><option value="EQUALS" selected>is</option></select>
        <input type="text" />
      </div>
    </template>`;
  document.body.appendChild(host);
  return host;
}

function typeNumber(host: HTMLElement, path: Path, value: string): void {
  const input = row(host, path).querySelector<HTMLInputElement>(
    '[data-value-cell] input[type="number"]:not([data-number-value2])',
  )!;
  input.value = value;
  input.dispatchEvent(new Event("input", { bubbles: true }));
}

describe("<filter-group> aggregate scope (#151)", () => {
  it("offers + scope only on a scopable (aggregate) field", () => {
    const host = mountScope();
    expect(button(host, "add-scope", [0])).toBeNull(); // no field picked yet
    pickField(host, [0], NAME_META);
    expect(button(host, "add-scope", [0])).toBeNull(); // plain string field
    pickField(host, [0], SESSION_COUNT_META);
    expect(button(host, "add-scope", [0])).not.toBeNull();
  });

  it("+ scope opens a scope group over the scope model, with a seeded row", () => {
    const host = mountScope();
    pickField(host, [0], SESSION_COUNT_META);
    clickAction(host, "add-scope", [0]);
    const scopeGroup = host.querySelector(
      `[data-kind="group"][data-path='${JSON.stringify([0, "scope"])}']`,
    );
    expect(scopeGroup).not.toBeNull();
    // Seeded with one empty criterion row, addressed through SCOPE_CHILD.
    expect(row(host, [0, "scope", 0])).not.toBeNull();
    // The affordance flips: + scope is replaced by − scope on the leaf row.
    expect(button(host, "add-scope", [0])).toBeNull();
    expect(button(host, "remove-scope", [0])).not.toBeNull();
  });

  it("scope rows resolve field pickers/widgets against the scope model", () => {
    const host = mountScope();
    pickField(host, [0], SESSION_COUNT_META);
    typeNumber(host, [0], "5");
    clickAction(host, "add-scope", [0]);
    pickField(host, [0, "scope", 0], SCOPE_NOTE_META);
    typeValue(host, [0, "scope", 0], "docked");
    expect(host.serializeForQuery()).toEqual({
      AND: [
        {
          session_count: {
            value: 5,
            modifier: "EQUALS",
            scope: { AND: [{ note: { value: "docked", modifier: "EQUALS" } }] },
          },
        },
      ],
    });
  });

  it("an empty scope serializes away (unscoped) but keeps its UI", () => {
    const host = mountScope();
    pickField(host, [0], SESSION_COUNT_META);
    typeNumber(host, [0], "3");
    clickAction(host, "add-scope", [0]); // seeded row left unfilled → pruned
    expect(host.serializeForQuery()).toEqual({
      AND: [{ session_count: { value: 3, modifier: "EQUALS" } }],
    });
    expect(
      host.querySelector(`[data-kind="group"][data-path='${JSON.stringify([0, "scope"])}']`),
    ).not.toBeNull();
  });

  it("− scope drops the scope subtree from tree and query", () => {
    const host = mountScope();
    pickField(host, [0], SESSION_COUNT_META);
    typeNumber(host, [0], "5");
    clickAction(host, "add-scope", [0]);
    pickField(host, [0, "scope", 0], SCOPE_NOTE_META);
    typeValue(host, [0, "scope", 0], "docked");
    clickAction(host, "remove-scope", [0]);
    expect(
      host.querySelector(`[data-kind="group"][data-path='${JSON.stringify([0, "scope"])}']`),
    ).toBeNull();
    expect(host.serializeForQuery()).toEqual({
      AND: [{ session_count: { value: 5, modifier: "EQUALS" } }],
    });
  });

  it("counts an unfilled scope row as incomplete under the scope model", () => {
    const host = mountScope();
    let last = -1;
    host.addEventListener("filter-tree-change", (event) => {
      last = (event as CustomEvent).detail.incompleteCount;
    });
    pickField(host, [0], SESSION_COUNT_META);
    typeNumber(host, [0], "5");
    expect(last).toBe(0);
    clickAction(host, "add-scope", [0]); // seeded empty scope row
    expect(last).toBe(1);
    pickField(host, [0, "scope", 0], SCOPE_NOTE_META);
    typeValue(host, [0, "scope", 0], "docked");
    expect(last).toBe(0);
  });

  it("prefill hydrates a scoped aggregate into the scope UI and round-trips", () => {
    const host = mountScope();
    host.loadFilter({
      session_count: {
        value: 5,
        modifier: "GREATER_THAN",
        scope: { note: { value: "docked", modifier: "EQUALS" } },
      },
    });
    // The scope group renders with its hydrated row.
    expect(row(host, [0, "scope", 0])).not.toBeNull();
    expect(
      row(host, [0, "scope", 0]).querySelector<HTMLInputElement>('[data-value-cell] input[type="text"]')!
        .value,
    ).toBe("docked");
    expect(host.serializeForQuery()).toEqual({
      AND: [
        {
          session_count: {
            value: 5,
            modifier: "GREATER_THAN",
            scope: { AND: [{ note: { value: "docked", modifier: "EQUALS" } }] },
          },
        },
      ],
    });
  });
});
