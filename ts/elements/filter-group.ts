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
import { deserialize, group, serialize } from "./filter-tree/serializer.js";
import type {
  ComparisonLeaf,
  ComparisonPayload,
  Connective,
  CriterionLeaf,
  FilterFieldMeta,
  FilterNode,
  FilterTreeChangeDetail,
  GroupNode,
  MetadataRegistry,
  ModelMeta,
  RelationMatch,
  RelationNode,
} from "./filter-tree/types.js";
import {
  type NodePath,
  RELATION_CHILD,
  canAddGroup,
  canAddRelation,
  canUnwrap,
  canWrap,
  criterionForField,
  duplicateAt,
  emptyComparison,
  emptyCriterion,
  emptyGroup,
  emptyRelation,
  emptyRoot,
  insertChild,
  isComparisonComplete,
  isCriterionComplete,
  move,
  parseFieldMeta,
  pruneIncomplete,
  removeAt,
  setLeafField,
  setMatch,
  setRelationField,
  toggleConnective,
  toggleNegate,
  unwrapGroup,
  wrapInGroup,
} from "./filter-tree/operations.js";
import {
  type Column,
  readComparisonRow,
  refreshRow,
} from "./field-comparison-set.js";
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
// An empty relation child is meaningful, not an error: the quantifier alone is the
// test. But that intent is invisible until spelled out — an unspelled empty relation
// silently injects an EXISTS/anti-EXISTS filter the user may not have meant (#225).
// So state, in plain terms and per quantifier, what an empty child matches. Kept
// model-agnostic on purpose (no model names).
function relationEmptyText(match: RelationMatch): string {
  switch (match) {
    case "ANY":
      return "Matches items with 1 or more related items (add a condition to filter them).";
    case "NONE":
      return "Matches items with 0 related items (add a condition to filter them).";
    case "ALL":
      return "Matches all items (add a condition to filter them).";
  }
  const unreachable: never = match; // exhaustive over RelationMatch; a new member fails tsc here
  return unreachable;
}
const SLOT_ROW_CLASS = "flex items-center gap-2 flex-wrap";
const FIELD_CELL_CLASS = "min-w-[12rem]";
const VALUE_CELL_CLASS = "flex-1 min-w-[12rem]";
// Placeholder shown in the value cell until a field is chosen.
const VALUE_PLACEHOLDER_CLASS =
  "flex-1 min-w-[12rem] rounded border border-dashed border-gray-300 px-2 py-1 text-sm " +
  "text-gray-500 dark:border-gray-600 dark:text-gray-400";
// Incomplete-leaf cue (excluded from the count/Apply query): a subtle amber tint
// on the row + the "Incomplete" badge. NOT `opacity` — a faded ancestor would make
// the leaf's own field-picker dropdown 60% transparent *and* create a stacking
// context that traps its z-10 below sibling rows/footer. A bg tint is safe on both
// counts. Space-separated → toggled token-by-token (classList.toggle takes one).
const INCOMPLETE_ROW_CLASS = "bg-amber-50 dark:bg-amber-500/10 rounded";
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
// Group left-edge accent, colored by connective — reuses the chip hues (AND=teal,
// OR=orange) so the card frame echoes the connective chip. Strong 400 edge matches
// the relation descent's indigo-400 left edge; together `border-l-4` +
// `border-l-<color>` thicken and recolor the left side of CARD_CLASS's uniform gray
// box border into a colored accent.
const GROUP_AND_EDGE_CLASS = "border-l-4 border-l-teal-400 dark:border-l-teal-500/70";
const GROUP_OR_EDGE_CLASS = "border-l-4 border-l-orange-400 dark:border-l-orange-500/70";
const NEGATE_OFF_CLASS =
  "border-gray-200 text-gray-500 hover:bg-gray-100 " +
  "dark:border-gray-700 dark:text-gray-400 dark:hover:bg-gray-700";
const NEGATE_ON_CLASS =
  "border-amber-400 bg-amber-100 text-amber-900 ring-1 ring-amber-400 " +
  "dark:border-amber-500/70 dark:bg-amber-500/25 dark:text-amber-100 dark:ring-amber-500/70";
const BUTTON_CLASS =
  "rounded border border-gray-200 px-2 py-1 text-xs hover:bg-gray-100 disabled:cursor-not-allowed " +
  "disabled:opacity-50 dark:border-gray-700 dark:hover:bg-gray-700";
// Relation-descent accent block (component 5, #193): a left-accented indigo card set
// apart from the gray group chrome so the Game→Session model switch reads explicitly.
// Header carries the `↳ [quantifier] of [relation] where` row.
const RELATION_CARD_CLASS =
  "flex flex-col gap-2 rounded-lg border border-l-4 border-indigo-200 border-l-indigo-400 " +
  "bg-indigo-50/50 p-2 dark:border-indigo-500/40 dark:border-l-indigo-500/70 dark:bg-indigo-500/10";
const RELATION_HEADER_CLASS = "flex items-center gap-2 flex-wrap";
const RELATION_ARROW_CLASS = "text-indigo-500 dark:text-indigo-300 font-semibold";
const RELATION_LABEL_CLASS = "text-sm text-gray-600 dark:text-gray-300";
// No horizontal padding: @tailwindcss/forms styles bare <select> with
// appearance:none, a right-anchored chevron, and the right padding (~2.5rem) that
// clears it. A px-*/pr-* utility can't beat the plugin rule for the right side;
// px-* only overrides it symmetrically, shrinking it so the label ("any") ends up
// under the chevron (the old px-2 did this). Set only vertical padding here.
const RELATION_SELECT_CLASS =
  "rounded border border-gray-300 bg-white py-1 text-sm dark:border-gray-600 dark:bg-gray-800 " +
  "disabled:opacity-50 disabled:cursor-not-allowed";

// The closed set of restructuring actions a button can carry; producer
// (actionButton) and consumer (applyAction's switch) share it so a typo on either
// side fails tsc instead of silently no-op'ing.
type TreeAction =
  | "add-condition"
  | "add-comparison"
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

// A comparison needs two columns of the SAME comparison group; a model admits one
// only when some group has ≥2 columns. Mirrors the server's has_comparable_group.
function hasComparableGroup(columns: Column[]): boolean {
  const groupCounts = new Map<string, number>();
  for (const column of columns) {
    groupCounts.set(column.group, (groupCounts.get(column.group) ?? 0) + 1);
  }
  return [...groupCounts.values()].some((count) => count >= 2);
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

// One relation-descent option for the relation picker (#193): the sub-filter field
// name + its human label. Derived from a model's `kind === "relation"` FieldMeta.
interface RelationOption {
  field: string;
  label: string;
}

// One model's client-side filter metadata + templates. The builder carries a bundle
// per relation-reachable model (#193) so a relation's child group renders from the
// TARGET model's fields/columns/templates, never the root's.
interface ModelBundle {
  fields: Map<string, FilterFieldMeta>;
  columns: Column[];
  hasComparableGroup: boolean;
  relations: RelationOption[];
  fieldPickerTemplate: HTMLTemplateElement | null;
  widgetTemplates: Map<string, HTMLTemplateElement>;
  comparisonRowTemplate: HTMLTemplateElement | null;
}

// The RelationMatch quantifiers, ordered for the picker. ANY is the default/first.
const RELATION_MATCHES: RelationMatch[] = ["ANY", "NONE", "ALL"];
const RELATION_MATCH_LABELS: Record<RelationMatch, string> = {
  ANY: "any",
  NONE: "none",
  ALL: "all",
};

// The shape of one model's bundle in the `models` prop JSON (mirrors ModelFieldBundle).
interface ModelFieldBundleJson {
  fields: FilterFieldMeta[];
  columns: Column[];
}

export class FilterGroupElement extends HTMLElement {
  private tree: GroupNode = emptyRoot();
  private model = "";
  private wired = false;
  // model key -> its metadata + templates bundle (#193). The root model is
  // `models.get(this.model)`; relation child groups read the target model's bundle.
  private models = new Map<string, ModelBundle>();
  // node id -> its cached cells (see LeafCells). Pruned to live nodes each render.
  private rowCache = new Map<string, LeafCells>();
  // node id -> a comparison leaf's cached row cell, reused across structural
  // re-renders so an in-progress comparison survives edits elsewhere.
  private comparisonCache = new Map<string, HTMLElement>();
  // Monotonic suffix so cloned widget/picker element ids stay unique per leaf.
  private cloneSequence = 0;

  connectedCallback(): void {
    const props = readFilterGroupProps(this);
    this.model = props.model;
    if (!this.wired) {
      this.parseModels(props.models);
      this.captureTemplates();
      // Seed from the server-rendered ?filter= before the first render, so the
      // summary/count/toolbar read the correct initial tree. Malformed → fail open.
      if (props.filter) {
        try {
          this.tree = deserialize(JSON.parse(props.filter), this.model, this.buildRegistry());
        } catch (error) {
          console.warn("filter-group: ignoring malformed filter prop", error);
        }
      }
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
    // Dispatch the initial change event so sibling consumers (<filter-summary>,
    // <filter-count>) that connected before us sync to the prefilled tree. The group
    // is the last element in the builder DOM, so every sibling's document listener is
    // already attached by the time connectedCallback runs here.
    this.dispatchChange();
  }

  // Build one ModelBundle per model in the `models` prop: its field map, comparison
  // columns (+ whether a comparison is possible), and relation-descent options
  // (derived from its `kind === "relation"` fields). Templates are attached later by
  // captureTemplates.
  private parseModels(raw: string): void {
    let bundles: Record<string, ModelFieldBundleJson> = {};
    if (raw) {
      try {
        bundles = JSON.parse(raw) as Record<string, ModelFieldBundleJson>;
      } catch {
        console.warn("filter-group: malformed models prop");
      }
    }
    for (const [key, bundle] of Object.entries(bundles)) {
      const fields = new Map<string, FilterFieldMeta>();
      const relations: RelationOption[] = [];
      for (const meta of bundle.fields) {
        fields.set(meta.name, meta);
        if (meta.kind === "relation") relations.push({ field: meta.name, label: meta.label });
      }
      this.models.set(key, {
        fields,
        columns: bundle.columns,
        // A comparison needs two columns of the SAME group, so a group with ≥2 members.
        hasComparableGroup: hasComparableGroup(bundle.columns),
        relations,
        fieldPickerTemplate: null,
        widgetTemplates: new Map(),
        comparisonRowTemplate: null,
      });
    }
  }

  // Detach the server-rendered <template>s (field picker + one per field + comparison
  // row) before the first render() replaces our children, bucketing each into its
  // model's bundle by the template's `data-model` tag (#193).
  private captureTemplates(): void {
    this.querySelectorAll<HTMLTemplateElement>("template[data-model]").forEach((template) => {
      const bundle = this.models.get(template.getAttribute("data-model") ?? "");
      if (!bundle) return;
      if (template.hasAttribute("data-field-picker-template")) {
        bundle.fieldPickerTemplate = template;
      } else if (template.hasAttribute("data-fc-row-template")) {
        bundle.comparisonRowTemplate = template;
      } else {
        const field = template.getAttribute("data-field");
        if (field) bundle.widgetTemplates.set(field, template);
      }
    });
  }

  // The bundle for a model key, or the root model's as a defensive fallback so a
  // stale/unknown key never throws mid-render. An unknown key is a server-metadata
  // gap (a relation target missing from model_field_registry / a key-casing mismatch),
  // not an expected path — warn so the otherwise-silent wrong-model render is
  // debuggable. The server contract (model_field_registry ≡ reachable_models) is
  // asserted in tests, so this branch should be unreachable in practice.
  private bundle(model: string): ModelBundle | undefined {
    const found = this.models.get(model);
    if (!found) {
      console.warn(
        `filter-group: no metadata bundle for model "${model}"; falling back to root "${this.model}"`,
      );
    }
    return found ?? this.models.get(this.model);
  }

  // The target model key a relation field descends into, resolved from `model`'s
  // metadata (RelationTarget.model is a Django model name → lower-cased key). An unset
  // field ("") is the expected pre-pick state (stay on `model`, silent); a field that
  // is set but has no relation target is a metadata gap worth warning about.
  private targetModel(model: string, field: string): string {
    const meta = this.bundle(model)?.fields.get(field);
    if (field && !meta?.relations[0]?.model) {
      console.warn(`filter-group: relation field "${field}" on model "${model}" has no target`);
    }
    return meta?.relations[0]?.model?.toLowerCase() ?? model;
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
    return serialize(pruneIncomplete(this.fillCriteria(this.tree, this.model)));
  }

  /** The filled-but-UNPRUNED tree (leaf values read live from widgets, incomplete
   *  leaves kept as `…` placeholders). The NL summary (#194) wants this; the count
   *  (#195) wants serializeForQuery(), which prunes. */
  getFilledTree(): GroupNode {
    return this.fillCriteria(this.tree, this.model);
  }

  /** Replace the whole tree from an OperatorFilter JSON blob (preset load / ?filter=
   *  import). Re-renders and fires filter-tree-change so summary + count refresh. */
  loadFilter(json: Record<string, unknown>): void {
    this.tree = deserialize(json, this.model, this.buildRegistry());
    this.render();
    this.dispatchChange();
  }

  /** Reset to an empty AND root. */
  clear(): void {
    this.tree = group("AND", []);
    this.render();
    this.dispatchChange();
  }

  /** How many criterion leaves are incomplete right now. The builder toolbar reads
   *  this on connect to set Apply's initial disabled state (no change event fires on
   *  the server-seeded tree, so it can't wait for one). */
  getIncompleteCount(): number {
    return this.incompleteCount();
  }

  // A name-set MetadataRegistry (what deserialize wants) projected from the richer
  // per-model ModelBundle map this element already parsed from the `models` prop.
  private buildRegistry(): MetadataRegistry {
    const registry: Record<string, ModelMeta> = {};
    for (const [key, bundle] of this.models) {
      const relations: Record<string, string> = {};
      for (const [name, meta] of bundle.fields) {
        const target = meta.relations[0]?.model;
        if (meta.kind === "relation" && target) relations[name] = target.toLowerCase();
      }
      registry[key] = { fields: new Set(bundle.fields.keys()), relations };
    }
    return registry;
  }

  // Clone the tree with every criterion leaf's `criterion` filled from its live
  // value widget (empty {} when the field/widget yields nothing → pruned as
  // incomplete). Structure/ids are preserved. `model` is the active model at this
  // group (switches to the target model inside each relation's child group, #193).
  private fillCriteria(node: GroupNode, model: string): GroupNode {
    return { ...node, children: node.children.map((child) => this.fillNode(child, model)) };
  }

  private fillNode(node: FilterNode, model: string): FilterNode {
    if (node.kind === "group") return this.fillCriteria(node, model);
    if (node.kind === "criterion") return { ...node, criterion: this.readLeaf(node, model) ?? {} };
    if (node.kind === "comparison") return { ...node, comparison: this.readComparison(node) ?? {} };
    // relation: its child group's leaves are live too — fill them under the target model.
    return { ...node, child: this.fillCriteria(node.child, this.targetModel(model, node.field)) };
  }

  // Read a criterion leaf's live value widget into a payload, or null when it has
  // no usable value (empty field, empty widget). Keyed off the cached value cell.
  private readLeaf(node: CriterionLeaf, model: string): Record<string, unknown> | null {
    const meta = this.bundle(model)?.fields.get(node.field);
    const cells = this.rowCache.get(node.id);
    if (!meta || !cells) return null;
    return readLeafWidget(cells.valueCell, meta.kind);
  }

  private leafComplete(node: CriterionLeaf, model: string): boolean {
    return isCriterionComplete({ ...node, criterion: this.readLeaf(node, model) ?? {} });
  }

  // Read a comparison leaf's live row into its {left, right, modifier, granularity?}
  // payload, or null when the row is incomplete. Keyed off the cached row cell.
  private readComparison(node: ComparisonLeaf): ComparisonPayload | null {
    const cell = this.comparisonCache.get(node.id);
    return cell ? readComparisonRow(cell) : null;
  }

  private comparisonComplete(node: ComparisonLeaf): boolean {
    return isComparisonComplete({ ...node, comparison: this.readComparison(node) ?? {} });
  }

  // Whether the user has picked the row's left column yet — the "touched" signal
  // that gates the Incomplete badge, mirroring how a criterion row shows no badge
  // until a field is chosen (a pristine comparison row shouldn't nag).
  private comparisonTouched(node: ComparisonLeaf): boolean {
    const left = this.comparisonCache.get(node.id)?.querySelector<HTMLSelectElement>("[data-fc-left]");
    return Boolean(left?.value);
  }

  private incompleteCount(node: GroupNode = this.tree, model: string = this.model): number {
    let count = 0;
    for (const child of node.children) {
      if (child.kind === "group") count += this.incompleteCount(child, model);
      else if (child.kind === "criterion" && !this.leafComplete(child, model)) count += 1;
      else if (child.kind === "comparison" && !this.comparisonComplete(child)) count += 1;
      else if (child.kind === "relation") {
        // A field-unset relation is incomplete (would serialize to `{"": …}`); its
        // child group's leaves count under the target model.
        if (child.field === "") count += 1;
        count += this.incompleteCount(child.child, this.targetModel(model, child.field));
      }
    }
    return count;
  }

  private onClick = (event: Event): void => {
    const button = (event.target as HTMLElement).closest<HTMLElement>("[data-action]");
    if (!button || button.dataset.action === undefined || button.dataset.path === undefined) return;
    const path = JSON.parse(button.dataset.path) as NodePath;
    this.applyAction(button.dataset.action as TreeAction, path);
  };

  private applyAction(action: TreeAction, path: NodePath): void {
    const before = this.tree;
    switch (action) {
      case "add-condition":
        this.tree = insertChild(this.tree, path, emptyCriterion());
        break;
      case "add-comparison":
        this.tree = insertChild(this.tree, path, emptyComparison());
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

  // Deliberate tradeoff (issue #233): every structural op does a full
  // `replaceChildren()` re-render, NOT true id-keyed reconciliation. The one thing
  // that must survive an edit — a leaf's in-progress value — does, because the leaf
  // cells are cached by `node.id` (`rowCache`/`comparisonCache`) and re-parented into
  // the rebuilt chrome. What a full re-render does NOT preserve is live interaction
  // state (focus, open dropdown, scroll) on the reused cell: `replaceChildren` briefly
  // detaches it, and the browser blurs a detached element. Accepted because every
  // structural edit originates from a button click, so focus is already off the leaf
  // widget when render() runs and the loss is not observable. Revisit (and build real
  // keyed reconciliation) only if an edit can ever fire while a leaf widget is focused.
  private render(): void {
    this.replaceChildren(this.renderGroup(this.tree, [], 0, 1, this.model, 0));
    this.pruneRowCache();
  }

  // Drop cached cells for nodes no longer in the tree (their DOM was discarded by
  // the replaceChildren above); live nodes keep their reused cells.
  private pruneRowCache(): void {
    const live = new Set<string>();
    const walk = (node: FilterNode): void => {
      if (node.kind === "group") node.children.forEach(walk);
      else if (node.kind === "relation") walk(node.child); // its child group's leaves stay live
      else live.add(node.id);
    };
    walk(this.tree);
    for (const id of [...this.rowCache.keys()]) {
      if (!live.has(id)) this.rowCache.delete(id);
    }
    for (const id of [...this.comparisonCache.keys()]) {
      if (!live.has(id)) this.comparisonCache.delete(id);
    }
  }

  // `model` is the active model at this group; `depth` is the true group-nesting
  // depth for coloring (path length is no longer a proxy — a relation's child group
  // is +1 depth but +2 path steps, #193). A relation's child group is rendered here
  // too but without its own restructuring controls (the relation node owns them).
  private renderGroup(
    node: GroupNode,
    path: NodePath,
    index: number,
    siblingCount: number,
    model: string,
    depth: number,
    relationEmptyLabel?: string,
  ): HTMLElement {
    const isRelationChild = path[path.length - 1] === RELATION_CHILD;
    const edgeClass = node.connective === "AND" ? GROUP_AND_EDGE_CLASS : GROUP_OR_EDGE_CLASS;
    const card = element("div", `${CARD_CLASS} ${depthBackground(depth)} ${edgeClass}`);
    card.dataset.kind = "group";
    card.dataset.path = JSON.stringify(path);

    // The root and every relation child group may sit empty — the root serializes to
    // {} (matches all), a relation's empty child is the ANY/NONE presence test. A
    // header-less state keeps an empty group off the NOT/connective chips it has
    // nothing to apply to (issue #236).
    if ((path.length === 0 || isRelationChild) && node.children.length === 0) {
      const emptyState = element("div", EMPTY_STATE_CLASS);
      // Only a relation child supplies a label (its per-quantifier presence-test copy);
      // the root empty group falls through to the generic "matches all" text.
      emptyState.textContent = relationEmptyLabel ?? EMPTY_STATE_TEXT;
      card.appendChild(emptyState);
      card.appendChild(this.footer(path, model));
      return card;
    }

    const header = element("div", HEADER_CLASS);
    // NOT is the leftmost control on every node (groups and leaves) so negation
    // always reads in the same place; the connective follows it on groups.
    const connectiveCluster = element("div", "flex items-center gap-1");
    connectiveCluster.appendChild(this.negateChip(node, path));
    connectiveCluster.appendChild(this.connectiveChip(node.connective, path));
    header.appendChild(connectiveCluster);
    // A relation child group is owned by its relation (not a list sibling), so it
    // carries no up/down/wrap/unwrap/duplicate/remove — only the relation node does.
    if (path.length > 0 && !isRelationChild) {
      header.appendChild(this.controls(path, true, index, siblingCount));
    }
    card.appendChild(header);

    const childrenBox = element("div", CHILDREN_CLASS);
    node.children.forEach((child, childIndex) => {
      childrenBox.appendChild(
        this.renderChild(child, [...path, childIndex], childIndex, node.children.length, model, depth),
      );
    });
    card.appendChild(childrenBox);

    card.appendChild(this.footer(path, model));
    return card;
  }

  private renderChild(
    child: FilterNode,
    path: NodePath,
    index: number,
    siblingCount: number,
    model: string,
    depth: number,
  ): HTMLElement {
    if (child.kind === "group") {
      return this.renderGroup(child, path, index, siblingCount, model, depth + 1);
    }
    if (child.kind === "criterion") return this.renderCriterionRow(child, path, index, siblingCount, model);
    if (child.kind === "comparison") {
      return this.renderComparisonRow(child, path, index, siblingCount, model);
    }
    return this.renderRelationRow(child, path, index, siblingCount, model, depth);
  }

  // The relation-descent accent block (component 5, #193):
  //   [NOT] ↳ [quantifier ▾] of [relation ▾] where …  [controls]
  //   └ nested child group (built from the TARGET model's fields)
  // An unset relation field marks the block incomplete (pruned from the query).
  private renderRelationRow(
    node: RelationNode,
    path: NodePath,
    index: number,
    siblingCount: number,
    model: string,
    depth: number,
  ): HTMLElement {
    const card = element("div", RELATION_CARD_CLASS);
    card.dataset.nodeSlot = "";
    card.dataset.nodeKind = "relation";
    card.dataset.path = JSON.stringify(path);
    card.dataset.model = model;

    const header = element("div", RELATION_HEADER_CLASS);
    header.appendChild(this.negateChip(node, path));
    const arrow = element("span", RELATION_ARROW_CLASS);
    arrow.textContent = "↳";
    header.appendChild(arrow);
    header.appendChild(this.relationMatchSelect(node));
    header.appendChild(this.relationLabel("of"));
    header.appendChild(this.relationFieldSelect(node, model));
    header.appendChild(this.relationLabel("where"));
    header.appendChild(this.controls(path, false, index, siblingCount));
    card.appendChild(header);

    // The child group is built from the target model; it descends one depth level.
    // Spell out what an empty child matches for the active quantifier so a presence
    // test is never applied silently (#225).
    const childModel = this.targetModel(model, node.field);
    card.appendChild(
      this.renderGroup(
        node.child,
        [...path, RELATION_CHILD],
        0,
        1,
        childModel,
        depth + 1,
        relationEmptyText(node.match),
      ),
    );
    this.applyIncompleteState(card, node.field === "");
    return card;
  }

  private relationLabel(text: string): HTMLElement {
    const span = element("span", RELATION_LABEL_CLASS);
    span.textContent = text;
    return span;
  }

  // The ANY/NONE/ALL quantifier picker; change dispatches setMatch.
  private relationMatchSelect(node: RelationNode): HTMLSelectElement {
    const select = element("select", RELATION_SELECT_CLASS);
    select.dataset.relationMatch = "";
    for (const match of RELATION_MATCHES) {
      const option = element("option");
      option.value = match;
      option.textContent = RELATION_MATCH_LABELS[match];
      option.selected = match === node.match;
      select.appendChild(option);
    }
    return select;
  }

  // The relation-field picker: the current model's relation options; change
  // dispatches setRelationField (which resets the child group on a model change).
  private relationFieldSelect(node: RelationNode, model: string): HTMLSelectElement {
    const select = element("select", RELATION_SELECT_CLASS);
    select.dataset.relationField = "";
    const placeholder = element("option");
    placeholder.value = "";
    placeholder.textContent = "a relation…";
    placeholder.disabled = true;
    placeholder.selected = node.field === "";
    select.appendChild(placeholder);
    for (const relation of this.bundle(model)?.relations ?? []) {
      const option = element("option");
      option.value = relation.field;
      option.textContent = relation.label;
      option.selected = relation.field === node.field;
      select.appendChild(option);
    }
    return select;
  }

  // The live criterion leaf row: [NOT] [field combobox] [value widget] [badge?]
  // [controls]. The two stateful cells are reused across renders via rowCache so a
  // structural edit never wipes an in-progress widget.
  private renderCriterionRow(
    node: CriterionLeaf,
    path: NodePath,
    index: number,
    siblingCount: number,
    model: string,
  ): HTMLElement {
    const cells = this.leafCells(node, model);
    const row = element("div", SLOT_ROW_CLASS);
    row.dataset.nodeSlot = "";
    row.dataset.nodeKind = "criterion";
    row.dataset.path = JSON.stringify(path);
    row.dataset.model = model;
    row.appendChild(this.negateChip(node, path));
    row.appendChild(cells.fieldCell);
    row.appendChild(cells.valueCell);
    row.appendChild(this.controls(path, false, index, siblingCount));
    // Controls are the row's last child; the badge (if any) is inserted before them.
    this.applyIncompleteState(row, Boolean(node.field) && !this.leafComplete(node, model));
    return row;
  }

  // Build or reuse a leaf's field + value cells, rebuilding the value cell only when
  // the field changed (or first set). Cached by node id. `model` picks the field
  // picker + value-widget templates from that model's bundle (#193).
  private leafCells(node: CriterionLeaf, model: string): LeafCells {
    let cells = this.rowCache.get(node.id);
    if (!cells) {
      cells = {
        field: "",
        fieldCell: this.buildFieldCell(model),
        valueCell: this.buildValueCell("", model),
      };
      this.rowCache.set(node.id, cells);
    }
    if (cells.field !== node.field) {
      cells.valueCell = this.buildValueCell(node.field, model);
      cells.field = node.field;
      if (node.field) this.showFieldSelection(cells.fieldCell, node.field, model);
    }
    return cells;
  }

  // Clone the field-picker combobox into a cell, with a unique id per leaf so
  // multiple pickers on the page never collide.
  private buildFieldCell(model: string): HTMLElement {
    const cell = element("div", FIELD_CELL_CLASS);
    cell.dataset.fieldCell = "";
    const content = this.bundle(model)?.fieldPickerTemplate?.content.firstElementChild;
    if (content) {
      const clone = content.cloneNode(true) as HTMLElement;
      this.uniquify(clone);
      cell.appendChild(clone);
    }
    return cell;
  }

  // Reflect an already-chosen field in the cloned combobox (import/rebuild). The
  // search-select's setSelected is silent, so it won't re-fire a field-pick.
  private showFieldSelection(fieldCell: HTMLElement, field: string, model: string): void {
    const searchSelect = fieldCell.querySelector<SearchSelectLike>("search-select");
    const label = this.bundle(model)?.fields.get(field)?.label ?? field;
    searchSelect?.setSelected(field, label);
  }

  // Build a value cell for `field`: a clone of the field's blank widget template,
  // or a placeholder prompt when no field is chosen yet.
  private buildValueCell(field: string, model: string): HTMLElement {
    if (!field) {
      const placeholder = element("div", VALUE_PLACEHOLDER_CLASS);
      placeholder.dataset.valueCell = "";
      placeholder.textContent = "Choose a field…";
      return placeholder;
    }
    const cell = element("div", VALUE_CELL_CLASS);
    cell.dataset.valueCell = "";
    const template = this.bundle(model)?.widgetTemplates.get(field);
    const content = template?.content.firstElementChild;
    if (content) {
      const clone = content.cloneNode(true) as HTMLElement;
      this.uniquify(clone);
      cell.appendChild(clone);
    }
    return cell;
  }

  // The live field-comparison leaf row (#246): [NOT] [left op right (by-day?)]
  // [controls]. The reused single-row widget lives in a cached cell so a structural
  // edit never wipes an in-progress comparison.
  private renderComparisonRow(
    node: ComparisonLeaf,
    path: NodePath,
    index: number,
    siblingCount: number,
    model: string,
  ): HTMLElement {
    const cell = this.comparisonCells(node, model);
    const row = element("div", SLOT_ROW_CLASS);
    row.dataset.nodeSlot = "";
    row.dataset.nodeKind = "comparison";
    row.dataset.path = JSON.stringify(path);
    row.dataset.model = model;
    row.appendChild(this.negateChip(node, path));
    row.appendChild(cell);
    row.appendChild(this.controls(path, false, index, siblingCount));
    this.applyIncompleteState(row, this.comparisonTouched(node) && !this.comparisonComplete(node));
    return row;
  }

  // Build or reuse a comparison leaf's row cell (cached by node id). Clones the
  // blank field-comparison row template, drops its ✕ (the group's controls own
  // removal), and wires the left-column change to rebuild its dependent
  // operator/right-column options via the reused refreshRow. Templates + columns
  // come from `model`'s bundle (#193).
  private comparisonCells(node: ComparisonLeaf, model: string): HTMLElement {
    let cell = this.comparisonCache.get(node.id);
    if (!cell) {
      cell = this.buildComparisonCell(model);
      this.comparisonCache.set(node.id, cell);
    }
    return cell;
  }

  private buildComparisonCell(model: string): HTMLElement {
    const cell = element("div", VALUE_CELL_CLASS);
    cell.dataset.valueCell = "";
    const bundle = this.bundle(model);
    const content = bundle?.comparisonRowTemplate?.content.firstElementChild;
    if (content && bundle) {
      const columns = bundle.columns;
      const row = content.cloneNode(true) as HTMLElement;
      row.querySelector("[data-fc-remove]")?.remove(); // the group's controls own removal
      this.uniquify(row);
      cell.appendChild(row);
      refreshRow(row, columns); // seed operator/right options from the (blank) left
      row
        .querySelector<HTMLSelectElement>("[data-fc-left]")
        ?.addEventListener("change", () => refreshRow(row, columns));
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
    // The relation picker + quantifier are native <select>s (#193); a change on
    // either rewrites the relation node and re-renders.
    if (event.type === "change" && target instanceof HTMLSelectElement) {
      if (target.dataset.relationField !== undefined) return this.handleRelationField(target);
      if (target.dataset.relationMatch !== undefined) return this.handleRelationMatch(target);
    }
    if (target.closest("[data-value-cell]")) this.refreshCompleteness(target);
  };

  private handleFieldPick(fieldPicker: HTMLElement, event: CustomEvent<SearchSelectChangeDetail>): void {
    const row = fieldPicker.closest<HTMLElement>("[data-node-slot]");
    if (!row?.dataset.path) return;
    const meta = parseFieldMeta(event.detail.last?.data?.meta ?? "");
    if (!meta) return;
    const path = JSON.parse(row.dataset.path) as NodePath;
    this.tree = setLeafField(this.tree, path, meta);
    this.render();
    this.dispatchChange();
  }

  // Pick a relation field: setRelationField resets the child group on a model change,
  // so a full re-render is needed (the child group's field pickers/widgets change).
  private handleRelationField(select: HTMLSelectElement): void {
    const path = this.pathForControl(select);
    if (!path) return;
    this.tree = setRelationField(this.tree, path, select.value);
    this.render();
    this.dispatchChange();
  }

  // Pick a relation quantifier (ANY/NONE/ALL): only the node's match changes; a
  // re-render keeps the select + downstream count/summary consistent.
  private handleRelationMatch(select: HTMLSelectElement): void {
    const path = this.pathForControl(select);
    if (!path) return;
    this.tree = setMatch(this.tree, path, select.value as RelationMatch);
    this.render();
    this.dispatchChange();
  }

  // The node path a relation control belongs to — read off its owning node slot.
  private pathForControl(control: HTMLElement): NodePath | null {
    const row = control.closest<HTMLElement>("[data-node-slot]");
    if (!row?.dataset.path) return null;
    return JSON.parse(row.dataset.path) as NodePath;
  }

  // Toggle the row's incomplete badge/fade in place (no re-render → the widget the
  // user is editing keeps focus) and report the new incomplete count.
  private refreshCompleteness(target: HTMLElement): void {
    const row = target.closest<HTMLElement>("[data-node-slot]");
    if (row?.dataset.path) {
      const node = this.nodeAtPath(JSON.parse(row.dataset.path) as NodePath);
      const model = row.dataset.model ?? this.model;
      if (node?.kind === "criterion") {
        this.applyIncompleteState(row, !this.leafComplete(node, model));
      } else if (node?.kind === "comparison") {
        this.applyIncompleteState(row, this.comparisonTouched(node) && !this.comparisonComplete(node));
      }
    }
    this.dispatchChange();
  }

  private applyIncompleteState(row: HTMLElement, incomplete: boolean): void {
    for (const token of INCOMPLETE_ROW_CLASS.split(" ")) row.classList.toggle(token, incomplete);
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
    for (const step of path) {
      if (step === RELATION_CHILD) {
        if (node.kind !== "relation") return null;
        node = node.child;
        continue;
      }
      if (node.kind !== "group") return null;
      const child: FilterNode | undefined = node.children[step];
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

  private footer(path: NodePath, model: string): HTMLElement {
    const footer = element("div", FOOTER_CLASS);
    const capReached = !canAddGroup(this.tree, path);
    footer.appendChild(actionButton("add-condition", "+ condition", path));
    footer.appendChild(
      actionButton("add-group", "+ group", path, {
        disabled: capReached,
        title: capReached ? "Max nesting reached" : "Add a nested group",
      }),
    );
    // A relation descends into the current group's model; only offer it when that
    // model actually has relations (a leaf-only model like Device has none).
    if ((this.bundle(model)?.relations.length ?? 0) > 0) {
      footer.appendChild(
        actionButton("add-relation", "+ relation", path, {
          disabled: !canAddRelation(this.tree, path),
          title: capReached ? "Max nesting reached" : "Add a relation descent",
        }),
      );
    }
    // A comparison is a leaf (no nesting), so it is never depth-gated — only shown
    // when the model admits one (a comparison group with ≥2 columns).
    if (this.bundle(model)?.hasComparableGroup) {
      footer.appendChild(
        actionButton("add-comparison", "+ comparison", path, {
          title: "Add a field-to-field comparison",
        }),
      );
    }
    return footer;
  }
}

customElements.define("filter-group", FilterGroupElement);
