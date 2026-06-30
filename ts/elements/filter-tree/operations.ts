/**
 * Pure, immutable tree operations for the nested filter builder (issue #189).
 *
 * The builder's single source of truth is a `GroupNode`-rooted `FilterNode` tree
 * (the same model the serializer consumes — `types.ts`). Every restructuring
 * affordance is a pure function here: it returns a new tree and never mutates its
 * input, so the custom element can hold `tree`, call an op, reassign, and re-render.
 * DOM lives in `filter-group.ts`; correctness lives here (and is vitest-tested).
 *
 * Addressing: a `NodePath` is the list of `group.children` indices from the root.
 * Paths only ever descend through groups — leaves and relations are terminal (the
 * shell renders a relation's child group as an inert slot, not a navigable subtree),
 * so a group reached at path `P` always sits at group-nesting depth `P.length`.
 */
import {
  type Connective,
  type CriterionLeaf,
  type FilterNode,
  type GroupNode,
  type RelationMatch,
  type RelationNode,
} from "./types.js";
import { group } from "./serializer.js";

export type NodePath = readonly number[];

// Soft UI cap on group nesting (design spec): the root group is depth 0; a new
// group/relation child may be created up to depth 5, deeper is disabled. The
// backend hard bound is MAX_FILTER_DEPTH = 10 (types.ts) — this is only the hint.
export const SOFT_DEPTH_CAP = 5;

// ── Node factories ───────────────────────────────────────────────────────────

// An empty criterion leaf: field unchosen, payload empty. A leaf widget (comp 4)
// fills `field`/`criterion` in 2d; until then it is an inert slot in the shell.
export function emptyCriterion(): CriterionLeaf {
  return { kind: "criterion", field: "", criterion: {}, negate: false };
}

// An empty relation descent: ANY over an empty child group is the "has ≥1 related
// row" presence test (design spec). Relation field + quantifier are set by comp 5.
export function emptyRelation(): RelationNode {
  return { kind: "relation", field: "", match: "ANY", child: group("AND", []), negate: false };
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
  for (const index of path) {
    if (node.kind !== "group") throw new Error(`Path descends into a non-group node`);
    const child: FilterNode | undefined = node.children[index];
    if (child === undefined) throw new Error(`Path index ${index} out of range`);
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
  if (node.kind !== "group") throw new Error(`Path descends into a non-group node`);
  const [index, ...rest] = path;
  const child = node.children[index];
  if (child === undefined) throw new Error(`Path index ${index} out of range`);
  const newChild = replaceNode(child, rest, transform);
  return { ...node, children: node.children.map((existing, i) => (i === index ? newChild : existing)) };
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

function splitPath(path: NodePath): { parentPath: NodePath; index: number } {
  if (path.length === 0) throw new Error(`Path addresses the root, which has no parent`);
  return { parentPath: path.slice(0, -1), index: path[path.length - 1] };
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

export function removeAt(root: GroupNode, path: NodePath): GroupNode {
  const { parentPath, index } = splitPath(path);
  return updateChildren(root, parentPath, (children) => children.filter((_, i) => i !== index));
}

export function duplicateAt(root: GroupNode, path: NodePath): GroupNode {
  const { parentPath, index } = splitPath(path);
  return updateChildren(root, parentPath, (children) => {
    const clone = structuredClone(children[index]);
    return [...children.slice(0, index + 1), clone, ...children.slice(index + 1)];
  });
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

export function setMatch(root: GroupNode, path: NodePath, match: RelationMatch): GroupNode {
  return replaceNodeAt(root, path, (node) => {
    if (node.kind !== "relation") throw new Error(`Node at path is not a relation`);
    return { ...node, match };
  });
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

// A group reached at `groupPath` sits at depth `groupPath.length` (paths descend
// through group children only).
export function groupDepthAt(_root: GroupNode, groupPath: NodePath): number {
  return groupPath.length;
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
  const slotDepth = path.length;
  const node = nodeAt(root, path);
  return deepestGroupDepth(group("AND", [node]), slotDepth) <= SOFT_DEPTH_CAP;
}

// Unwrap is meaningful only for a non-root group.
export function canUnwrap(root: GroupNode, path: NodePath): boolean {
  return path.length > 0 && nodeAt(root, path).kind === "group";
}
