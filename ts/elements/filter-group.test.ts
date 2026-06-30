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
    expect(host.querySelector('[data-slot="connective"]')?.textContent).toBe("AND");
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

describe("<filter-group> inert-slot contract (2d hydration)", () => {
  it("leaf/relation slots carry data-path and a round-trippable data-payload", () => {
    const host = mount();
    clickAction(host, "add-relation", []); // [0]=criterion, [1]=relation
    const relationSlot = slots(host).find((slot) => slot.dataset.nodeKind === "relation")!;
    expect(relationSlot.dataset.path).toBe(JSON.stringify([1]));
    expect(JSON.parse(relationSlot.dataset.payload!)).toMatchObject({
      kind: "relation",
      field: "",
      match: "ANY",
      negate: false,
    });
    const criterionSlot = slots(host).find((slot) => slot.dataset.nodeKind === "criterion")!;
    expect(JSON.parse(criterionSlot.dataset.payload!)).toMatchObject({ kind: "criterion", negate: false });
  });

  it("the connective slot carries its group path for component 2", () => {
    const host = mount();
    expect(host.querySelector<HTMLElement>('[data-slot="connective"]')!.dataset.path).toBe("[]");
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
