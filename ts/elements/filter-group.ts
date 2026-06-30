/**
 * <filter-group> — the recursive group shell of the nested filter builder
 * (issue #189, phase 2c of #168).
 *
 * Holds the whole `FilterNode` tree in JS (the single source of truth the
 * serializer consumes) and re-renders the DOM from it on every edit. This shell
 * owns only *structure*: group cards, alternating depth coloring, the soft depth
 * cap, the footer add-buttons, and the buttons-only restructuring affordances
 * (remove / duplicate / wrap / unwrap / ↑ / ↓). The connective+negate UI (comp 2),
 * leaf widgets (comp 3/4), and relation block (comp 5) are sibling 2c components;
 * here their places are **inert slots** carrying each node's identity + payload,
 * hydrated during 2d assembly.
 *
 * Correctness (every mutation) lives in the pure `filter-tree/operations.ts`
 * module and is vitest-tested; this file is the thin DOM projection over it.
 */
import { readFilterGroupProps } from "../generated/props.js";
import { serialize } from "./filter-tree/serializer.js";
import type { Connective, FilterNode, FilterTreeChangeDetail, GroupNode } from "./filter-tree/types.js";
import {
  type NodePath,
  canAddGroup,
  canAddRelation,
  canUnwrap,
  canWrap,
  duplicateAt,
  emptyCriterion,
  emptyGroup,
  emptyRelation,
  emptyRoot,
  insertChild,
  move,
  removeAt,
  unwrapGroup,
  wrapInGroup,
} from "./filter-tree/operations.js";

// Full, static class strings only — Tailwind detects complete strings, so the
// depth palette is a fixed lookup (never `bg-depth-${n}`). ~4-shade cycle that
// repeats past depth 3, giving nested cards alternating backgrounds.
const DEPTH_BACKGROUNDS = [
  "bg-gray-50 dark:bg-gray-900/40",
  "bg-white dark:bg-gray-800/40",
  "bg-gray-100 dark:bg-gray-800/20",
  "bg-white dark:bg-gray-700/20",
];
const CARD_CLASS = "flex flex-col gap-2 rounded-lg border border-gray-200 p-2 dark:border-gray-700";
const HEADER_CLASS = "flex items-center justify-between gap-2";
const CHILDREN_CLASS = "flex flex-col gap-2 pl-3";
const FOOTER_CLASS = "flex flex-wrap gap-2";
const SLOT_ROW_CLASS = "flex items-center justify-between gap-2";
const SLOT_CLASS =
  "flex-1 rounded border border-dashed border-gray-300 px-2 py-1 text-sm text-gray-600 " +
  "dark:border-gray-600 dark:text-gray-300";
const CONNECTIVE_SLOT_CLASS =
  "rounded border border-gray-300 px-2 py-1 text-xs font-medium text-gray-700 " +
  "dark:border-gray-600 dark:text-gray-200";
const BUTTON_CLASS =
  "rounded border border-gray-200 px-2 py-1 text-xs hover:bg-gray-100 disabled:cursor-not-allowed " +
  "disabled:opacity-50 dark:border-gray-700 dark:hover:bg-gray-700";

// The closed set of restructuring actions a button can carry; producer
// (actionButton) and consumer (applyAction's switch) share it so a typo on either
// side fails tsc instead of silently no-op'ing.
type TreeAction =
  | "add-condition"
  | "add-group"
  | "add-relation"
  | "remove"
  | "duplicate"
  | "wrap"
  | "unwrap"
  | "up"
  | "down";

// The event the shell dispatches after every edit (see FilterTreeChangeDetail).
export const FILTER_TREE_CHANGE_EVENT = "filter-tree-change";

function depthBackground(depth: number): string {
  return DEPTH_BACKGROUNDS[depth % DEPTH_BACKGROUNDS.length];
}

function element<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  className?: string,
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  if (className) node.className = className;
  return node;
}

// A restructuring action button: carries the action name + the target path so a
// single delegated listener can route it. `disabled` greys it out; the cap-gated
// actions (add-group/add-relation/wrap/unwrap) are additionally re-guarded in the
// handler, so a stale click on a since-invalidated one is harmless.
function actionButton(
  action: TreeAction,
  label: string,
  path: NodePath,
  { disabled = false, title = "" } = {},
): HTMLButtonElement {
  const button = element("button", BUTTON_CLASS);
  button.type = "button";
  button.textContent = label;
  button.dataset.action = action;
  button.dataset.path = JSON.stringify(path);
  if (disabled) button.disabled = true;
  if (title) button.title = title;
  return button;
}

function slotLabel(node: FilterNode): string {
  if (node.kind === "criterion") return node.field ? `condition · ${node.field}` : "condition · (unset)";
  if (node.kind === "relation") return node.field ? `relation · ${node.field}` : "relation · (unset)";
  return "comparison";
}

export class FilterGroupElement extends HTMLElement {
  private tree: GroupNode = emptyRoot();
  private model = "";
  private wired = false;

  connectedCallback(): void {
    this.model = readFilterGroupProps(this).model;
    if (!this.wired) {
      this.addEventListener("click", this.onClick);
      this.wired = true;
    }
    this.render();
  }

  /** The current node tree — for 2d serialize/count. Do not mutate it: the shell's
   *  immutability invariant (and the change-event dispatch) relies on edits going
   *  through the pure ops, so the type is `Readonly` to flag in-place writes. */
  getTree(): Readonly<GroupNode> {
    return this.tree;
  }

  /** Convenience: the canonical OperatorFilter JSON for the current tree. */
  serialize(): Record<string, unknown> {
    return serialize(this.tree);
  }

  private onClick = (event: Event): void => {
    const button = (event.target as HTMLElement).closest<HTMLElement>("[data-action]");
    if (!button || button.dataset.action === undefined || button.dataset.path === undefined) return;
    const path: NodePath = JSON.parse(button.dataset.path) as number[];
    this.applyAction(button.dataset.action as TreeAction, path);
  };

  private applyAction(action: TreeAction, path: NodePath): void {
    const before = this.tree;
    switch (action) {
      case "add-condition":
        this.tree = insertChild(this.tree, path, emptyCriterion());
        break;
      case "add-group":
        if (canAddGroup(this.tree, path)) this.tree = insertChild(this.tree, path, emptyGroup());
        break;
      case "add-relation":
        if (canAddRelation(this.tree, path)) this.tree = insertChild(this.tree, path, emptyRelation());
        break;
      case "remove":
        this.tree = removeAt(this.tree, path);
        break;
      case "duplicate":
        this.tree = duplicateAt(this.tree, path);
        break;
      case "wrap":
        if (canWrap(this.tree, path)) this.tree = wrapInGroup(this.tree, path);
        break;
      case "unwrap":
        if (canUnwrap(this.tree, path)) this.tree = unwrapGroup(this.tree, path);
        break;
      case "up":
        this.tree = move(this.tree, path, -1);
        break;
      case "down":
        this.tree = move(this.tree, path, 1);
        break;
      default:
        return;
    }
    if (this.tree === before) return; // a guarded/boundary no-op changed nothing
    this.render();
    const detail: FilterTreeChangeDetail = { tree: this.tree };
    this.dispatchEvent(new CustomEvent(FILTER_TREE_CHANGE_EVENT, { bubbles: true, detail }));
  }

  private render(): void {
    this.replaceChildren(this.renderGroup(this.tree, [], 0, 1));
  }

  private renderGroup(node: GroupNode, path: NodePath, index: number, siblingCount: number): HTMLElement {
    const card = element("div", `${CARD_CLASS} ${depthBackground(path.length)}`);
    card.dataset.kind = "group";
    card.dataset.path = JSON.stringify(path);

    const header = element("div", HEADER_CLASS);
    header.appendChild(this.connectiveSlot(node.connective, path));
    if (path.length > 0) header.appendChild(this.controls(path, true, index, siblingCount));
    card.appendChild(header);

    const childrenBox = element("div", CHILDREN_CLASS);
    node.children.forEach((child, childIndex) => {
      childrenBox.appendChild(this.renderChild(child, [...path, childIndex], childIndex, node.children.length));
    });
    card.appendChild(childrenBox);

    card.appendChild(this.footer(path));
    return card;
  }

  private renderChild(child: FilterNode, path: NodePath, index: number, siblingCount: number): HTMLElement {
    if (child.kind === "group") return this.renderGroup(child, path, index, siblingCount);
    const row = element("div", SLOT_ROW_CLASS);
    const slot = element("div", SLOT_CLASS);
    slot.dataset.nodeSlot = "";
    slot.dataset.nodeKind = child.kind;
    slot.dataset.path = JSON.stringify(path);
    slot.dataset.payload = JSON.stringify(child); // identity + payload for 2d hydration
    slot.textContent = slotLabel(child);
    row.appendChild(slot);
    row.appendChild(this.controls(path, false, index, siblingCount));
    return row;
  }

  // The connective is an inert placeholder here — component 2 replaces it with a
  // real AND/OR selector + ¬ toggle, reading the same data-path.
  private connectiveSlot(connective: Connective, path: NodePath): HTMLElement {
    const slot = element("div", CONNECTIVE_SLOT_CLASS);
    slot.dataset.slot = "connective";
    slot.dataset.path = JSON.stringify(path);
    slot.textContent = connective;
    return slot;
  }

  private controls(path: NodePath, isGroup: boolean, index: number, siblingCount: number): HTMLElement {
    const bar = element("div", "flex items-center gap-1");
    bar.appendChild(actionButton("up", "↑", path, { disabled: index === 0, title: "Move up" }));
    bar.appendChild(
      actionButton("down", "↓", path, { disabled: index >= siblingCount - 1, title: "Move down" }),
    );
    bar.appendChild(
      actionButton("wrap", "Wrap", path, {
        disabled: !canWrap(this.tree, path),
        title: canWrap(this.tree, path) ? "Wrap in a group" : "Max nesting reached",
      }),
    );
    if (isGroup) {
      bar.appendChild(
        actionButton("unwrap", "Unwrap", path, {
          disabled: !canUnwrap(this.tree, path),
          title: "Dissolve this group into its parent",
        }),
      );
    }
    bar.appendChild(actionButton("duplicate", "Duplicate", path, { title: "Duplicate" }));
    bar.appendChild(actionButton("remove", "Remove", path, { title: "Remove" }));
    return bar;
  }

  private footer(path: NodePath): HTMLElement {
    const footer = element("div", FOOTER_CLASS);
    const capReached = !canAddGroup(this.tree, path);
    footer.appendChild(actionButton("add-condition", "+ condition", path));
    footer.appendChild(
      actionButton("add-group", "+ group", path, {
        disabled: capReached,
        title: capReached ? "Max nesting reached" : "Add a nested group",
      }),
    );
    footer.appendChild(
      actionButton("add-relation", "+ relation", path, {
        disabled: !canAddRelation(this.tree, path),
        title: capReached ? "Max nesting reached" : "Add a relation descent",
      }),
    );
    return footer;
  }
}

customElements.define("filter-group", FilterGroupElement);
