/**
 * <filter-group> — the recursive group shell of the nested filter builder
 * (issue #189, phase 2c of #168).
 *
 * Holds the whole `FilterNode` tree in JS (the single source of truth the
 * serializer consumes) and re-renders the DOM from it on every edit. This shell
 * owns the *structure* — group cards, alternating depth coloring, the soft depth
 * cap, the footer add-buttons, and the buttons-only restructuring affordances
 * (remove / duplicate / wrap / unwrap / ↑ / ↓) — plus the connective + NOT chips
 * (comp 2, #190), which are stateless projections of each node's
 * connective/negate flag wired through the same data-action delegation. The leaf
 * widgets (comp 3/4) and relation block (comp 5) are sibling 2c components; here
 * their places are **inert slots** carrying each node's identity + payload,
 * hydrated during 2d assembly.
 *
 * Correctness (every mutation) lives in the pure `filter-tree/operations.ts`
 * module and is vitest-tested; this file is the thin DOM projection over it.
 */
import { readFilterGroupProps } from "../generated/props.js";
import { serialize } from "./filter-tree/serializer.js";
import type {
  Connective,
  CriterionLeaf,
  FilterFieldMeta,
  FilterNode,
  FilterTreeChangeDetail,
  GroupNode,
} from "./filter-tree/types.js";
import {
  type NodePath,
  canAddGroup,
  canAddRelation,
  canUnwrap,
  canWrap,
  criterionForField,
  duplicateAt,
  emptyCriterion,
  emptyGroup,
  emptyRelation,
  emptyRoot,
  insertChild,
  isCriterionComplete,
  move,
  parseFieldMeta,
  pruneIncomplete,
  removeAt,
  setLeafField,
  toggleConnective,
  toggleNegate,
  unwrapGroup,
  wrapInGroup,
} from "./filter-tree/operations.js";
import { readLeafWidget, setupModifierToggles } from "./filter-widgets.js";
import type { SearchSelectChangeDetail } from "./search-select.js";

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
// Shown in place of the header when the root group is empty: an empty filter
// serializes to {} (matches everything), so say so rather than render a NOT/AND
// chip on a group with nothing to negate or join (issue #236).
const EMPTY_STATE_CLASS = "px-2 py-1 text-sm text-gray-500 dark:text-gray-400";
const EMPTY_STATE_TEXT = "No conditions. This will match all items.";
const SLOT_ROW_CLASS = "flex items-center gap-2 flex-wrap";
const FIELD_CELL_CLASS = "min-w-[12rem]";
const VALUE_CELL_CLASS = "flex-1 min-w-[12rem]";
// Placeholder shown in the value cell until a field is chosen.
const VALUE_PLACEHOLDER_CLASS =
  "flex-1 min-w-[12rem] rounded border border-dashed border-gray-300 px-2 py-1 text-sm " +
  "text-gray-500 dark:border-gray-600 dark:text-gray-400";
// Faded look + "Incomplete" badge for a leaf missing its value (excluded from the
// count/Apply query). Applied to the whole row.
const INCOMPLETE_ROW_CLASS = "opacity-60";
const BADGE_CLASS =
  "rounded-full border border-amber-300 bg-amber-50 px-2 py-0.5 text-xs font-medium " +
  "text-amber-700 dark:border-amber-500/50 dark:bg-amber-500/10 dark:text-amber-300";
// Connective + NOT chips (component 2, issue #190). Pill shape (rounded-full) +
// saturated fill sets this cluster apart from the square, gray restructuring
// buttons so it never reads as "just another button". The connective is
// color-coded by value with a NON-semantic cool/warm pair — AND = teal, OR =
// orange — kept out of the action palette (blue/red/green/gray) so it reads as
// "logic type", not status. The NOT-on look uses an amber FILL + RING so a lit
// NOT chip stays distinct from an adjacent OR chip (fill-only) — they never read
// as one blob.
const CHIP_BASE = "rounded-full border px-2.5 py-0.5 text-xs font-semibold hover:cursor-pointer";
const CONNECTIVE_AND_CLASS =
  "border-teal-300 bg-teal-100 text-teal-800 " +
  "dark:border-teal-500/60 dark:bg-teal-500/20 dark:text-teal-200";
const CONNECTIVE_OR_CLASS =
  "border-orange-300 bg-orange-100 text-orange-800 " +
  "dark:border-orange-500/60 dark:bg-orange-500/20 dark:text-orange-200";
const NEGATE_OFF_CLASS =
  "border-gray-200 text-gray-500 hover:bg-gray-100 " +
  "dark:border-gray-700 dark:text-gray-400 dark:hover:bg-gray-700";
const NEGATE_ON_CLASS =
  "border-amber-400 bg-amber-100 text-amber-900 ring-1 ring-amber-400 " +
  "dark:border-amber-500/70 dark:bg-amber-500/25 dark:text-amber-100 dark:ring-amber-500/70";
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
  | "down"
  | "toggle-connective"
  | "toggle-negate";

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

// A leaf's two stateful cells, cached by node id so a structural re-render reuses
// (re-appends) them — the live value widget's DOM state survives edits elsewhere.
interface LeafCells {
  field: string; // the field the value cell was built for ("" = none yet)
  fieldCell: HTMLElement;
  valueCell: HTMLElement;
}

interface SearchSelectLike extends HTMLElement {
  setSelected(value: string, label?: string): void;
}

export class FilterGroupElement extends HTMLElement {
  private tree: GroupNode = emptyRoot();
  private model = "";
  private wired = false;
  // field name -> its FieldMeta (kind, label, modifiers …), from the `fields` prop.
  private fields = new Map<string, FilterFieldMeta>();
  // The <template> whose content is the field-picker combobox, cloned per leaf.
  private fieldPickerTemplate: HTMLTemplateElement | null = null;
  // field name -> its blank value-widget <template>, cloned into a leaf on field-pick.
  private widgetTemplates = new Map<string, HTMLTemplateElement>();
  // node id -> its cached cells (see LeafCells). Pruned to live nodes each render.
  private rowCache = new Map<string, LeafCells>();
  // Monotonic suffix so cloned widget/picker element ids stay unique per leaf.
  private cloneSequence = 0;

  connectedCallback(): void {
    const props = readFilterGroupProps(this);
    this.model = props.model;
    if (!this.wired) {
      this.captureTemplates();
      this.parseFields(props.fields);
      this.addEventListener("click", this.onClick);
      // Value edits (typing, radios, set pills, date bounds, field pick) bubble
      // here; one delegated listener updates completeness / handles field changes.
      this.addEventListener("input", this.onValueEvent);
      this.addEventListener("change", this.onValueEvent);
      this.addEventListener("search-select:change", this.onValueEvent);
      this.addEventListener("date-range:change", this.onValueEvent);
      // Reuse the flat bar's modifier-select enable/disable behavior for the cloned
      // string/number widgets (presence hides value; BETWEEN reveals value2).
      setupModifierToggles(this);
      this.wired = true;
    }
    this.render();
  }

  // Detach the server-rendered <template>s (field picker + one per field) before
  // the first render() replaces our children, keeping references to clone from.
  private captureTemplates(): void {
    this.fieldPickerTemplate = this.querySelector<HTMLTemplateElement>(
      "template[data-field-picker-template]",
    );
    this.querySelectorAll<HTMLTemplateElement>("template[data-field]").forEach((template) => {
      const field = template.getAttribute("data-field");
      if (field) this.widgetTemplates.set(field, template);
    });
  }

  private parseFields(raw: string): void {
    if (!raw) return;
    try {
      const list = JSON.parse(raw) as FilterFieldMeta[];
      for (const meta of list) this.fields.set(meta.name, meta);
    } catch {
      console.warn("filter-group: malformed fields prop");
    }
  }

  /** The current node tree — for 2d serialize/count. Do not mutate it: every edit
   *  must go through the pure ops (the change-event dispatch depends on it). The
   *  `Readonly` is shallow — it flags top-level rebinds only; deep mutation of
   *  `children` or a nested node stays on the honor system. */
  getTree(): Readonly<GroupNode> {
    return this.tree;
  }

  /** The canonical OperatorFilter JSON for the current tree structure (leaf values
   *  are read live from the widgets — see serializeForQuery). */
  serialize(): Record<string, unknown> {
    return serialize(this.tree);
  }

  /** The JSON to actually query with: each criterion leaf's value is read from its
   *  live widget, then incomplete leaves are pruned (excluded from the count/Apply
   *  query). Used by the builder page (comp 10). */
  serializeForQuery(): Record<string, unknown> {
    return serialize(pruneIncomplete(this.fillCriteria(this.tree)));
  }

  // Clone the tree with every criterion leaf's `criterion` filled from its live
  // value widget (empty {} when the field/widget yields nothing → pruned as
  // incomplete). Structure/ids are preserved.
  private fillCriteria(node: GroupNode): GroupNode {
    return { ...node, children: node.children.map((child) => this.fillNode(child)) };
  }

  private fillNode(node: FilterNode): FilterNode {
    if (node.kind === "group") return this.fillCriteria(node);
    if (node.kind === "criterion") return { ...node, criterion: this.readLeaf(node) ?? {} };
    return node; // relation/comparison unchanged (out of this slice)
  }

  // Read a criterion leaf's live value widget into a payload, or null when it has
  // no usable value (empty field, empty widget). Keyed off the cached value cell.
  private readLeaf(node: CriterionLeaf): Record<string, unknown> | null {
    const meta = this.fields.get(node.field);
    const cells = this.rowCache.get(node.id);
    if (!meta || !cells) return null;
    return readLeafWidget(cells.valueCell, meta.kind);
  }

  private leafComplete(node: CriterionLeaf): boolean {
    return isCriterionComplete({ ...node, criterion: this.readLeaf(node) ?? {} });
  }

  private incompleteCount(node: GroupNode = this.tree): number {
    let count = 0;
    for (const child of node.children) {
      if (child.kind === "group") count += this.incompleteCount(child);
      else if (child.kind === "criterion" && !this.leafComplete(child)) count += 1;
    }
    return count;
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
      case "toggle-connective":
        this.tree = toggleConnective(this.tree, path);
        break;
      case "toggle-negate":
        this.tree = toggleNegate(this.tree, path);
        break;
      default: {
        // Exhaustiveness guard: every TreeAction is handled above, so `action`
        // narrows to `never` here. Adding a member without a case fails tsc. The
        // runtime `return` still guards the `as TreeAction` cast of dataset.action.
        const unhandled: never = action;
        return unhandled;
      }
    }
    if (this.tree === before) return; // a guarded/boundary no-op changed nothing
    this.render();
    this.dispatchChange();
  }

  private dispatchChange(): void {
    const detail: FilterTreeChangeDetail = {
      tree: this.tree,
      incompleteCount: this.incompleteCount(),
    };
    this.dispatchEvent(new CustomEvent(FILTER_TREE_CHANGE_EVENT, { bubbles: true, detail }));
  }

  private render(): void {
    this.replaceChildren(this.renderGroup(this.tree, [], 0, 1));
    this.pruneRowCache();
  }

  // Drop cached cells for nodes no longer in the tree (their DOM was discarded by
  // the replaceChildren above); live nodes keep their reused cells.
  private pruneRowCache(): void {
    const live = new Set<string>();
    const walk = (node: FilterNode): void => {
      if (node.kind === "group") node.children.forEach(walk);
      else live.add(node.id);
    };
    walk(this.tree);
    for (const id of [...this.rowCache.keys()]) {
      if (!live.has(id)) this.rowCache.delete(id);
    }
  }

  private renderGroup(node: GroupNode, path: NodePath, index: number, siblingCount: number): HTMLElement {
    const card = element("div", `${CARD_CLASS} ${depthBackground(path.length)}`);
    card.dataset.kind = "group";
    card.dataset.path = JSON.stringify(path);

    // Only the root may be empty (non-root groups auto-collapse on their last
    // child's removal). A header-less "matches all" state keeps an empty group
    // off the NOT/connective chips it has nothing to apply to (issue #236).
    if (path.length === 0 && node.children.length === 0) {
      const emptyState = element("div", EMPTY_STATE_CLASS);
      emptyState.textContent = EMPTY_STATE_TEXT;
      card.appendChild(emptyState);
      card.appendChild(this.footer(path));
      return card;
    }

    const header = element("div", HEADER_CLASS);
    // NOT is the leftmost control on every node (groups and leaves) so negation
    // always reads in the same place; the connective follows it on groups.
    const connectiveCluster = element("div", "flex items-center gap-1");
    connectiveCluster.appendChild(this.negateChip(node, path));
    connectiveCluster.appendChild(this.connectiveChip(node.connective, path));
    header.appendChild(connectiveCluster);
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
    if (child.kind === "criterion") return this.renderCriterionRow(child, path, index, siblingCount);
    return this.renderInertSlot(child, path, index, siblingCount);
  }

  // Relation/comparison leaves stay inert slots (their widgets are sibling 2c
  // components, out of this slice); the criterion row is live below.
  private renderInertSlot(
    child: FilterNode,
    path: NodePath,
    index: number,
    siblingCount: number,
  ): HTMLElement {
    const row = element("div", SLOT_ROW_CLASS);
    const slot = element("div", VALUE_PLACEHOLDER_CLASS);
    slot.dataset.nodeSlot = "";
    slot.dataset.nodeKind = child.kind;
    slot.dataset.path = JSON.stringify(path);
    slot.textContent = slotLabel(child);
    row.appendChild(this.negateChip(child, path));
    row.appendChild(slot);
    row.appendChild(this.controls(path, false, index, siblingCount));
    return row;
  }

  // The live criterion leaf row: [NOT] [field combobox] [value widget] [badge?]
  // [controls]. The two stateful cells are reused across renders via rowCache so a
  // structural edit never wipes an in-progress widget.
  private renderCriterionRow(
    node: CriterionLeaf,
    path: NodePath,
    index: number,
    siblingCount: number,
  ): HTMLElement {
    const cells = this.leafCells(node);
    const row = element("div", SLOT_ROW_CLASS);
    row.dataset.nodeSlot = "";
    row.dataset.nodeKind = "criterion";
    row.dataset.path = JSON.stringify(path);
    row.appendChild(this.negateChip(node, path));
    row.appendChild(cells.fieldCell);
    row.appendChild(cells.valueCell);
    row.appendChild(this.controls(path, false, index, siblingCount));
    // Controls are the row's last child; the badge (if any) is inserted before them.
    this.applyIncompleteState(row, Boolean(node.field) && !this.leafComplete(node));
    return row;
  }

  // Build or reuse a leaf's field + value cells, rebuilding the value cell only when
  // the field changed (or first set). Cached by node id.
  private leafCells(node: CriterionLeaf): LeafCells {
    let cells = this.rowCache.get(node.id);
    if (!cells) {
      cells = { field: "", fieldCell: this.buildFieldCell(), valueCell: this.buildValueCell("") };
      this.rowCache.set(node.id, cells);
    }
    if (cells.field !== node.field) {
      cells.valueCell = this.buildValueCell(node.field);
      cells.field = node.field;
      if (node.field) this.showFieldSelection(cells.fieldCell, node.field);
    }
    return cells;
  }

  // Clone the field-picker combobox into a cell, with a unique id per leaf so
  // multiple pickers on the page never collide.
  private buildFieldCell(): HTMLElement {
    const cell = element("div", FIELD_CELL_CLASS);
    cell.dataset.fieldCell = "";
    const content = this.fieldPickerTemplate?.content.firstElementChild;
    if (content) {
      const clone = content.cloneNode(true) as HTMLElement;
      this.uniquify(clone);
      cell.appendChild(clone);
    }
    return cell;
  }

  // Reflect an already-chosen field in the cloned combobox (import/rebuild). The
  // search-select's setSelected is silent, so it won't re-fire a field-pick.
  private showFieldSelection(fieldCell: HTMLElement, field: string): void {
    const searchSelect = fieldCell.querySelector<SearchSelectLike>("search-select");
    const label = this.fields.get(field)?.label ?? field;
    searchSelect?.setSelected(field, label);
  }

  // Build a value cell for `field`: a clone of the field's blank widget template,
  // or a placeholder prompt when no field is chosen yet.
  private buildValueCell(field: string): HTMLElement {
    if (!field) {
      const placeholder = element("div", VALUE_PLACEHOLDER_CLASS);
      placeholder.dataset.valueCell = "";
      placeholder.textContent = "Choose a field…";
      return placeholder;
    }
    const cell = element("div", VALUE_CELL_CLASS);
    cell.dataset.valueCell = "";
    const template = this.widgetTemplates.get(field);
    const content = template?.content.firstElementChild;
    if (content) {
      const clone = content.cloneNode(true) as HTMLElement;
      this.uniquify(clone);
      cell.appendChild(clone);
    }
    return cell;
  }

  // Suffix every id/for/name in a cloned subtree so repeated clones stay valid HTML
  // and label associations point at their own controls (the widgets query their own
  // descendants, so functionality never depended on these being unique).
  private uniquify(root: HTMLElement): void {
    const suffix = `g${(this.cloneSequence += 1)}`;
    const rewrite = (element: Element, attribute: string): void => {
      const value = element.getAttribute(attribute);
      if (value) element.setAttribute(attribute, `${value}-${suffix}`);
    };
    root.querySelectorAll<HTMLElement>("[id],[for],[name]").forEach((element) => {
      rewrite(element, "id");
      rewrite(element, "for");
      rewrite(element, "name");
    });
  }

  // A value-cell edit (or a field pick) bubbled up. Route field picks to setLeafField
  // (re-render swaps the value widget); plain value edits just refresh completeness
  // (the widget DOM is the source of truth, read at serialize time).
  private onValueEvent = (event: Event): void => {
    const target = event.target as HTMLElement;
    const fieldPicker = target.closest<HTMLElement>("[data-field-picker]");
    if (fieldPicker && event.type === "search-select:change") {
      this.handleFieldPick(fieldPicker, event as CustomEvent<SearchSelectChangeDetail>);
      return;
    }
    if (target.closest("[data-value-cell]")) this.refreshCompleteness(target);
  };

  private handleFieldPick(fieldPicker: HTMLElement, event: CustomEvent<SearchSelectChangeDetail>): void {
    const row = fieldPicker.closest<HTMLElement>("[data-node-slot]");
    if (!row?.dataset.path) return;
    const meta = parseFieldMeta(event.detail.last?.data?.meta ?? "");
    if (!meta) return;
    const path = JSON.parse(row.dataset.path) as number[];
    this.tree = setLeafField(this.tree, path, meta);
    this.render();
    this.dispatchChange();
  }

  // Toggle the row's incomplete badge/fade in place (no re-render → the widget the
  // user is editing keeps focus) and report the new incomplete count.
  private refreshCompleteness(target: HTMLElement): void {
    const row = target.closest<HTMLElement>('[data-node-slot][data-node-kind="criterion"]');
    if (row?.dataset.path) {
      const node = this.nodeAtPath(JSON.parse(row.dataset.path) as number[]);
      if (node?.kind === "criterion") this.applyIncompleteState(row, !this.leafComplete(node));
    }
    this.dispatchChange();
  }

  private applyIncompleteState(row: HTMLElement, incomplete: boolean): void {
    row.classList.toggle(INCOMPLETE_ROW_CLASS, incomplete);
    let badge = row.querySelector<HTMLElement>("[data-incomplete-badge]");
    if (incomplete && !badge) {
      badge = element("span", BADGE_CLASS);
      badge.dataset.incompleteBadge = "";
      badge.textContent = "Incomplete";
      row.insertBefore(badge, row.lastElementChild);
    } else if (!incomplete && badge) {
      badge.remove();
    }
  }

  private nodeAtPath(path: NodePath): FilterNode | null {
    let node: FilterNode = this.tree;
    for (const index of path) {
      if (node.kind !== "group") return null;
      const child: FilterNode | undefined = node.children[index];
      if (!child) return null;
      node = child;
    }
    return node;
  }

  // A chip-style toggle button: a restructuring action (so it rides the existing
  // data-action delegation + applyAction) wearing its own chip classes instead of
  // BUTTON_CLASS. `pressed` reflects an on/off state via aria-pressed.
  private chip(
    action: TreeAction,
    label: string,
    path: NodePath,
    className: string,
    { title = "", pressed }: { title?: string; pressed?: boolean } = {},
  ): HTMLButtonElement {
    const button = element("button", `${CHIP_BASE} ${className}`);
    button.type = "button";
    button.textContent = label;
    button.dataset.action = action;
    button.dataset.path = JSON.stringify(path);
    if (title) button.title = title;
    if (pressed !== undefined) button.setAttribute("aria-pressed", String(pressed));
    return button;
  }

  // The connective chip: label is the value itself; clicking flips AND<->OR. Color
  // carries the value (no lit/pressed state — the label already shows it).
  private connectiveChip(connective: Connective, path: NodePath): HTMLButtonElement {
    const colorClass = connective === "AND" ? CONNECTIVE_AND_CLASS : CONNECTIVE_OR_CLASS;
    return this.chip("toggle-connective", connective, path, colorClass, {
      title: "Toggle AND/OR for this group",
    });
  }

  // The NOT negate chip (groups and leaves): constant label, lit when the node's
  // negate flag is set. Clicking toggles it.
  private negateChip(node: FilterNode, path: NodePath): HTMLButtonElement {
    return this.chip("toggle-negate", "NOT", path, node.negate ? NEGATE_ON_CLASS : NEGATE_OFF_CLASS, {
      title: node.negate ? "Remove negation" : "Negate",
      pressed: node.negate,
    });
  }

  private controls(path: NodePath, isGroup: boolean, index: number, siblingCount: number): HTMLElement {
    const bar = element("div", "flex items-center gap-1");
    bar.appendChild(actionButton("up", "↑", path, { disabled: index === 0, title: "Move up" }));
    bar.appendChild(
      actionButton("down", "↓", path, { disabled: index >= siblingCount - 1, title: "Move down" }),
    );
    const wrappable = canWrap(this.tree, path);
    bar.appendChild(
      actionButton("wrap", "Wrap", path, {
        disabled: !wrappable,
        title: wrappable ? "Wrap in a group" : "Max nesting reached",
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
