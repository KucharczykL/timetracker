/**
 * Pure, immutable tree operations for the nested filter builder (issue #189).
 *
 * The builder's single source of truth is a `GroupNode`-rooted `FilterNode` tree
 * (the same model the serializer consumes — `types.ts`). Every restructuring
 * affordance is a pure function here: it returns a new tree and never mutates its
 * input, so the custom element can hold `tree`, call an op, reassign, and re-render.
 * DOM lives in `filter-group.ts`; correctness lives here (and is vitest-tested).
 *
 * Addressing: a `NodePath` is a list of steps from the root. A numeric step selects
 * a `group.children` index; the `RELATION_CHILD` sentinel step descends from a
 * relation node into its one child group (issue #193). So a relation's child group
 * *is* a navigable subtree — a numeric step lands on the relation, then a
 * `RELATION_CHILD` step enters its group. Because a relation node is not itself a
 * group level, path length no longer equals group-nesting depth; `groupDepthAt`
 * walks the tree to count group levels.
 */
import {
  type ComparisonLeaf,
  type Connective,
  type CriterionLeaf,
  type CriterionPayload,
  type FilterFieldMeta,
  type FilterNode,
  type GroupNode,
  type RelationMatch,
  type RelationNode,
} from "./types.js";
import { group } from "./serializer.js";
import { nextNodeId } from "./node-id.js";
import { isPresenceModifier, isRangeModifier } from "../filter-tokens.js";

// A path step is either a positional index into a group's children, or the
// `RELATION_CHILD` sentinel meaning "descend into the relation node's child group".
// The string sentinel survives `JSON.stringify`/`JSON.parse` (paths are stored in the
// DOM as `data-path` JSON), so no custom (de)serialization is needed.
export const RELATION_CHILD = "child";
export type PathStep = number | typeof RELATION_CHILD;
export type NodePath = readonly PathStep[];

// Soft UI cap on group nesting (design spec): the root group is depth 0; a new
// group/relation child may be created up to depth 5, deeper is disabled. The
// backend hard bound is MAX_FILTER_DEPTH = 10 (types.ts) — this is only the hint.
export const SOFT_DEPTH_CAP = 5;

// ── Node factories ───────────────────────────────────────────────────────────

// An empty criterion leaf: field unchosen, payload empty. A leaf widget (comp 4)
// fills `field`/`criterion` in 2d; until then it is an inert slot in the shell.
export function emptyCriterion(): CriterionLeaf {
  return { kind: "criterion", id: nextNodeId(), field: "", criterion: {}, negate: false };
}

// ── Add-criterion field picker contract (issue #191) ─────────────────────────

// Parse a field-picker option's `data-meta` JSON into a `FilterFieldMeta`.
// Defensive: returns null on empty/malformed JSON (the consumer no-ops) since the
// Python↔TS shape is not codegen-guarded yet. Does not deep-validate the shape —
// it trusts the single server producer (common.criteria.field_metadata).
export function parseFieldMeta(raw: string): FilterFieldMeta | null {
  if (!raw) return null;
  try {
    return JSON.parse(raw) as FilterFieldMeta;
  } catch {
    return null;
  }
}

// The on-field-change reset (design spec / issue #191): a FRESH leaf for the
// picked field — modifier reset to the first valid one for the field's kind, the
// value DROPPED entirely (no silent type-coercion from the previous field). The
// leaf is structurally incomplete until a value widget (#192) fills it.
export function criterionForField(meta: FilterFieldMeta): CriterionLeaf {
  const [firstModifier] = meta.modifiers;
  const criterion = firstModifier !== undefined ? { modifier: firstModifier } : {};
  return { kind: "criterion", id: nextNodeId(), field: meta.name, criterion, negate: false };
}

// Whether a single payload slot counts as filled. A bare `""`/null/undefined or an
// empty array is empty; anything else (incl. `0`, `false`) is present.
function isValuePresent(value: unknown): boolean {
  if (value === undefined || value === null || value === "") return false;
  if (Array.isArray(value) && value.length === 0) return false;
  return true;
}

// Whether a leaf is complete enough to query/apply: it needs a field, a modifier,
// and a non-empty value — UNLESS the modifier is a presence test (IS_NULL /
// NOT_NULL), which is value-less by design. A range modifier (BETWEEN / NOT_BETWEEN)
// additionally needs the second bound `value2`: a half-filled BETWEEN serializes to a
// payload the backend rejects *wholesale* (`IntCriterion.to_q` raises FilterError when
// value2 is None, and `filter_from_json` validates eagerly — so one bad leaf drops the
// entire filter). Excluding it here keeps it out of both the count query and Apply.
export function isCriterionComplete(leaf: CriterionLeaf): boolean {
  if (!leaf.field) return false;
  const modifier = leaf.criterion["modifier"];
  if (typeof modifier !== "string" || modifier === "") return false;
  if (isPresenceModifier(modifier)) return true;
  if (!isValuePresent(leaf.criterion["value"])) return false;
  if (isRangeModifier(modifier) && !isValuePresent(leaf.criterion["value2"])) return false;
  return true;
}

// Whether a field-comparison leaf is complete enough to query/apply: it needs a left
// column, a right column, and a modifier, and the two columns must DIFFER (a column
// compared to itself is meaningless — the row widget never offers it). Mirrors
// isCriterionComplete: an incomplete comparison is excluded from the count/Apply query
// (a half-filled field_comparisons entry the backend rejects wholesale — see
// pruneIncomplete). This is the single place the serializer layer reads the payload's
// shape; `ComparisonPayload` (Partial<ComparisonRow>) makes the field access typo-safe.
export function isComparisonComplete(leaf: ComparisonLeaf): boolean {
  const { left, right, modifier } = leaf.comparison;
  if (!left || !right || !modifier) return false;
  return left !== right;
}

// An empty comparison leaf: no columns/modifier chosen. The field-comparison row
// widget (#246) fills `comparison` with {left, right, modifier, granularity?} read
// live from its row; until then it is a structurally-incomplete slot.
export function emptyComparison(): ComparisonLeaf {
  return { kind: "comparison", id: nextNodeId(), comparison: {}, negate: false };
}

// An empty relation descent: ANY over an empty child group is the "has ≥1 related
// row" presence test (design spec). Relation field + quantifier are set by comp 5.
export function emptyRelation(): RelationNode {
  return { kind: "relation", id: nextNodeId(), field: "", match: "ANY", child: group("AND", []), negate: false };
}

// A new sub-group seeded with one empty criterion so it is never vacuously empty
// in the UI. Connective defaults to AND; comp 2 lets the user switch it.
export function emptyGroup(connective: Connective = "AND"): GroupNode {
  return group(connective, [emptyCriterion()]);
}

// The initial tree: root is always an AND group pre-seeded with one empty leaf row.
export function emptyRoot(): GroupNode {
  return group("AND", [emptyCriterion()]);
}

// ── Navigation ───────────────────────────────────────────────────────────────

export function nodeAt(root: GroupNode, path: NodePath): FilterNode {
  let node: FilterNode = root;
  for (const step of path) {
    if (step === RELATION_CHILD) {
      if (node.kind !== "relation") throw new Error(`RELATION_CHILD step on a non-relation node`);
      node = node.child;
      continue;
    }
    if (node.kind !== "group") throw new Error(`Path descends into a non-group node`);
    const child: FilterNode | undefined = node.children[step];
    if (child === undefined) throw new Error(`Path index ${step} out of range`);
    node = child;
  }
  return node;
}

function groupAt(root: GroupNode, path: NodePath): GroupNode {
  const node = nodeAt(root, path);
  if (node.kind !== "group") throw new Error(`Node at path is not a group`);
  return node;
}

// ── Immutable spine rewrite ──────────────────────────────────────────────────

// Replace the node at `path` with `transform(node)`, cloning only the groups along
// the spine. The input tree is never mutated.
function replaceNodeAt(
  root: GroupNode,
  path: NodePath,
  transform: (node: FilterNode) => FilterNode,
): GroupNode {
  const result = replaceNode(root, path, transform);
  if (result.kind !== "group") throw new Error(`Root replacement must stay a group`);
  return result;
}

function replaceNode(
  node: FilterNode,
  path: NodePath,
  transform: (node: FilterNode) => FilterNode,
): FilterNode {
  if (path.length === 0) return transform(node);
  const [step, ...rest] = path;
  if (step === RELATION_CHILD) {
    if (node.kind !== "relation") throw new Error(`RELATION_CHILD step on a non-relation node`);
    return { ...node, child: replaceNode(node.child, rest, transform) as GroupNode };
  }
  if (node.kind !== "group") throw new Error(`Path descends into a non-group node`);
  const child = node.children[step];
  if (child === undefined) throw new Error(`Path index ${step} out of range`);
  const newChild = replaceNode(child, rest, transform);
  return { ...node, children: node.children.map((existing, i) => (i === step ? newChild : existing)) };
}

// Transform the `children` array of the group at `groupPath`.
function updateChildren(
  root: GroupNode,
  groupPath: NodePath,
  transform: (children: FilterNode[]) => FilterNode[],
): GroupNode {
  return replaceNodeAt(root, groupPath, (node) => {
    if (node.kind !== "group") throw new Error(`Node at path is not a group`);
    return { ...node, children: transform([...node.children]) };
  });
}

// Split a *positional* node path into its containing group + index. The last step
// must be a numeric index: only a group's positional children are removed / moved /
// duplicated / wrapped. A `RELATION_CHILD`-terminated path addresses a relation's
// child group, which is owned by its relation (never a list slot), so it is rejected.
function splitPath(path: NodePath): { parentPath: NodePath; index: number } {
  if (path.length === 0) throw new Error(`Path addresses the root, which has no parent`);
  const last = path[path.length - 1];
  if (typeof last !== "number") throw new Error(`Path does not address a positional child`);
  return { parentPath: path.slice(0, -1), index: last };
}

// ── Structural operations ────────────────────────────────────────────────────

export function insertChild(
  root: GroupNode,
  groupPath: NodePath,
  node: FilterNode,
  index?: number,
): GroupNode {
  return updateChildren(root, groupPath, (children) => {
    const at = index ?? children.length;
    return [...children.slice(0, at), node, ...children.slice(at)];
  });
}

// Remove the node at `path`, then collapse any group the removal leaves empty:
// an emptied non-root group is removed from its own parent, cascading upward as
// long as each removal empties the next ancestor. The root is the one group
// allowed to sit empty (it cannot be removed — the shell renders it as a "matches
// all" empty state), so the walk stops there. Keeps the invariant that no
// rendered, NOT-able group is ever empty (issue #236).
export function removeAt(root: GroupNode, path: NodePath): GroupNode {
  const { parentPath, index } = splitPath(path);
  let next = updateChildren(root, parentPath, (children) => children.filter((_, i) => i !== index));
  let groupPath: NodePath = parentPath;
  // Cascade the empty-group collapse upward, but only through *positional* group
  // children (numeric last step). A relation's child group (RELATION_CHILD-terminated)
  // is a boundary like the root: ANY over an empty child group is the meaningful
  // "has ≥1 related row" presence test, so it may sit empty and the relation stays.
  while (
    groupPath.length > 0 &&
    typeof groupPath[groupPath.length - 1] === "number" &&
    groupAt(next, groupPath).children.length === 0
  ) {
    const { parentPath: grandparentPath, index: groupIndex } = splitPath(groupPath);
    next = updateChildren(next, grandparentPath, (children) =>
      children.filter((_, i) => i !== groupIndex),
    );
    groupPath = grandparentPath;
  }
  return next;
}

export function duplicateAt(root: GroupNode, path: NodePath): GroupNode {
  const { parentPath, index } = splitPath(path);
  return updateChildren(root, parentPath, (children) => {
    const clone = reassignIds(structuredClone(children[index]));
    return [...children.slice(0, index + 1), clone, ...children.slice(index + 1)];
  });
}

// A duplicated subtree must get fresh ids on every node — a structuredClone copies
// the source ids, which would collide with the originals in the shell's id→DOM map.
function reassignIds(node: FilterNode): FilterNode {
  node.id = nextNodeId();
  if (node.kind === "group") node.children.forEach(reassignIds);
  else if (node.kind === "relation") reassignIds(node.child);
  return node;
}

// Move the node at `path` one slot earlier (-1) or later (+1) among its siblings.
// A move past either boundary returns the *same* root reference unchanged, so a
// caller can identity-compare to detect the no-op (the element also disables ↑/↓
// at the ends).
export function move(root: GroupNode, path: NodePath, direction: -1 | 1): GroupNode {
  const { parentPath, index } = splitPath(path);
  const siblings = groupAt(root, parentPath).children;
  const target = index + direction;
  if (target < 0 || target >= siblings.length) return root;
  return updateChildren(root, parentPath, (children) => {
    const reordered = [...children];
    [reordered[index], reordered[target]] = [reordered[target], reordered[index]];
    return reordered;
  });
}

export function setConnective(root: GroupNode, groupPath: NodePath, connective: Connective): GroupNode {
  return replaceNodeAt(root, groupPath, (node) => {
    if (node.kind !== "group") throw new Error(`Node at path is not a group`);
    return { ...node, connective };
  });
}

// Flip a group's connective between the two values (AND<->OR). The connective is
// a fixed binary (design spec), so the chip UI in component 2 is a flip, not a
// pick; this is the payload-free operation it dispatches. `setConnective` keeps
// the explicit-value setter for programmatic/import use.
export function toggleConnective(root: GroupNode, groupPath: NodePath): GroupNode {
  return replaceNodeAt(root, groupPath, (node) => {
    if (node.kind !== "group") throw new Error(`Node at path is not a group`);
    return { ...node, connective: node.connective === "AND" ? "OR" : "AND" };
  });
}

export function setMatch(root: GroupNode, path: NodePath, match: RelationMatch): GroupNode {
  return replaceNodeAt(root, path, (node) => {
    if (node.kind !== "relation") throw new Error(`Node at path is not a relation`);
    return { ...node, match };
  });
}

// Pick (or change) a relation node's field (issue #193). Changing the field can
// change the target model, whose fields differ, so the child group is reset to a
// fresh empty AND group — no silent carry-over of leaves keyed by the old model's
// fields (mirrors `setLeafField`'s reset). Re-picking the SAME field is a no-op that
// preserves the in-progress child group. `id`, `negate`, and `match` are preserved.
export function setRelationField(root: GroupNode, path: NodePath, field: string): GroupNode {
  return replaceNodeAt(root, path, (node) => {
    if (node.kind !== "relation") throw new Error(`Node at path is not a relation`);
    if (node.field === field) return node;
    return { ...node, field, child: group("AND", []) };
  });
}

// ── Leaf payload edits (issue #192) ──────────────────────────────────────────

// Pick (or change) a criterion leaf's field: replace it with a FRESH leaf for the
// chosen field via `criterionForField` (modifier reset to the field's first valid,
// value dropped — no silent type-coercion). The node's own `negate` flag is
// preserved (changing the field shouldn't silently un-negate the row).
export function setLeafField(root: GroupNode, path: NodePath, meta: FilterFieldMeta): GroupNode {
  return replaceNodeAt(root, path, (node) => {
    if (node.kind !== "criterion") throw new Error(`Node at path is not a criterion leaf`);
    // Keep the node's id (and negate): it's the same row, so the shell reuses its
    // row element and only swaps the value widget for the new field's kind.
    return { ...criterionForField(meta), id: node.id, negate: node.negate };
  });
}

// Set a criterion leaf's whole opaque payload (what a value widget produced). The
// serializer wraps it verbatim as `{field: payload}`, so the widget owns the shape.
export function setLeafCriterion(
  root: GroupNode,
  path: NodePath,
  criterion: CriterionPayload,
): GroupNode {
  return replaceNodeAt(root, path, (node) => {
    if (node.kind !== "criterion") throw new Error(`Node at path is not a criterion leaf`);
    return { ...node, criterion };
  });
}

// ── Pruning incomplete leaves for the query (issue #192) ─────────────────────

// Drop every incomplete criterion leaf (see `isCriterionComplete`) so the count /
// Apply query never carries one (an incomplete leaf with `field === ""` serializes
// to `{"": …}` — one key — so the serializer's empty-child filter does NOT drop it;
// pruning is required). A non-root group emptied by pruning collapses out of its
// parent (the #236 invariant: no rendered, NOT-able empty group); the root may sit
// empty (→ `{}` matches-all). A full recursive walk — relations descend into their
// child group too — and a relation is kept even if its child empties (ANY over an
// empty group is the meaningful "has ≥1 related row" presence test).
export function pruneIncomplete(root: GroupNode): GroupNode {
  return pruneGroup(root);
}

function pruneGroup(node: GroupNode): GroupNode {
  const children: FilterNode[] = [];
  for (const child of node.children) {
    const pruned = pruneNode(child);
    if (pruned !== null) children.push(pruned);
  }
  return { ...node, children };
}

function pruneNode(node: FilterNode): FilterNode | null {
  switch (node.kind) {
    case "criterion":
      return isCriterionComplete(node) ? node : null;
    case "comparison":
      return isComparisonComplete(node) ? node : null;
    case "relation":
      // A field-unset relation would serialize to `{"": …}`; drop it like an
      // incomplete leaf. With a field chosen it survives even when its child group
      // empties (ANY over empty = the "has ≥1 related row" presence test).
      return node.field === "" ? null : { ...node, child: pruneGroup(node.child) };
    case "group": {
      const pruned = pruneGroup(node);
      return pruned.children.length === 0 ? null : pruned; // collapse emptied non-root group
    }
  }
}

// Negation is a per-node flag, never a connective (design spec). Toggling it twice
// cancels. The ¬ button UI lives in component 2; this is the operation it calls.
export function toggleNegate(root: GroupNode, path: NodePath): GroupNode {
  return replaceNodeAt(root, path, (node) => ({ ...node, negate: !node.negate }));
}

// Wrap the node at `path` in a new group whose connective defaults to the parent
// group's connective (design spec). The node becomes the wrapper's only child.
export function wrapInGroup(root: GroupNode, path: NodePath): GroupNode {
  const { parentPath } = splitPath(path);
  const parentConnective = groupAt(root, parentPath).connective;
  return replaceNodeAt(root, path, (node) => group(parentConnective, [node]));
}

// Dissolve the group at `path`, splicing its children into the parent at its slot.
// The dissolved group's connective and negate flag are dropped — only valid when
// `canUnwrap` holds (a non-root group); the element gates the button on it.
export function unwrapGroup(root: GroupNode, path: NodePath): GroupNode {
  const { parentPath, index } = splitPath(path);
  const node = nodeAt(root, path);
  if (node.kind !== "group") throw new Error(`Cannot unwrap a non-group node`);
  return updateChildren(root, parentPath, (children) => [
    ...children.slice(0, index),
    ...node.children,
    ...children.slice(index + 1),
  ]);
}

// ── Depth ────────────────────────────────────────────────────────────────────

// The deepest group-nesting depth anywhere in `group`'s subtree, given the group
// itself sits at `groupDepth`. A child group is +1; a relation's child group is +1
// (the relation node is not itself a group); leaves contribute nothing. This is the
// single primitive every cap check is derived from.
export function deepestGroupDepth(node: GroupNode, groupDepth: number): number {
  let deepest = groupDepth;
  for (const child of node.children) {
    if (child.kind === "group") {
      deepest = Math.max(deepest, deepestGroupDepth(child, groupDepth + 1));
    } else if (child.kind === "relation") {
      deepest = Math.max(deepest, deepestGroupDepth(child.child, groupDepth + 1));
    }
  }
  return deepest;
}

// The group-nesting depth of the group reached at `groupPath`. Path length is no
// longer a proxy: a numeric step onto a relation node is not a group level (only the
// following RELATION_CHILD step is), so the tree is walked, counting each landing on
// a group node. `game AND (rel sessions where AND …)`: the child group at
// `[0, RELATION_CHILD]` is depth 1 (two steps, one group level).
export function groupDepthAt(root: GroupNode, groupPath: NodePath): number {
  let node: FilterNode = root;
  let depth = 0;
  for (const step of groupPath) {
    if (step === RELATION_CHILD) {
      if (node.kind !== "relation") throw new Error(`RELATION_CHILD step on a non-relation node`);
      node = node.child;
      depth += 1; // a relation's child group is one level below the relation's group
      continue;
    }
    if (node.kind !== "group") throw new Error(`Path descends into a non-group node`);
    node = node.children[step];
    if (node?.kind === "group") depth += 1;
  }
  return depth;
}

// `+ group`/`+ relation` add a child group one level below the current group; allow
// only while that child stays within the soft cap.
export function canAddGroup(root: GroupNode, groupPath: NodePath): boolean {
  return groupDepthAt(root, groupPath) < SOFT_DEPTH_CAP;
}

export function canAddRelation(root: GroupNode, groupPath: NodePath): boolean {
  return canAddGroup(root, groupPath);
}

// Wrapping pushes the node's whole subtree one level deeper (under a fresh wrapper
// group at the node's current slot depth). Allowed only when the deepest resulting
// group stays within the soft cap. Works for every node kind because the wrapper is
// a group holding the node, and `deepestGroupDepth` accounts for groups/relations.
export function canWrap(root: GroupNode, path: NodePath): boolean {
  if (path.length === 0) return false; // the root cannot be wrapped
  // The wrapper takes the node's slot, sitting one level below its containing group;
  // groupDepthAt (not path.length) gives that group's true depth through relations.
  const slotDepth = groupDepthAt(root, path.slice(0, -1)) + 1;
  const node = nodeAt(root, path);
  return deepestGroupDepth(group("AND", [node]), slotDepth) <= SOFT_DEPTH_CAP;
}

// Unwrap is meaningful only for a non-root group. A relation's child group
// (RELATION_CHILD-terminated) is owned by its relation, never a splice-able list
// slot, so it is not unwrappable.
export function canUnwrap(root: GroupNode, path: NodePath): boolean {
  return (
    path.length > 0 &&
    path[path.length - 1] !== RELATION_CHILD &&
    nodeAt(root, path).kind === "group"
  );
}
