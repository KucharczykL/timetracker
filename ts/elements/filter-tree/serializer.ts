/**
 * Filter-tree serializer/deserializer (issue #188).
 *
 * serialize: node tree -> canonical OperatorFilter JSON (single-key children,
 * never a mixed node). deserialize: arbitrary/legacy JSON -> node tree, faithfully
 * reproducing the backend fold order. See the design spec.
 */
import {
  type Connective,
  type FilterNode,
  type GroupNode,
  type MetadataRegistry,
  type RelationMatch,
  FilterTreeError,
  MAX_FIELD_COMPARISONS,
  MAX_FILTER_BREADTH,
  MAX_FILTER_DEPTH,
  RESERVED_KEYS,
} from "./types.js";

type Json = Record<string, unknown>;

export function group(connective: Connective, children: FilterNode[], negate = false): GroupNode {
  return { kind: "group", connective, negate, children };
}

// ── Export ─────────────────────────────────────────────────────────────────

export function serialize(root: GroupNode): Json {
  return serializeNode(root);
}

function serializeNode(node: FilterNode): Json {
  switch (node.kind) {
    case "group": {
      const children = node.children
        .map(serializeNode)
        .filter((dict) => Object.keys(dict).length > 0);
      const inner: Json = children.length ? { [node.connective]: children } : {};
      return wrapNegate(inner, node.negate);
    }
    case "criterion":
      return wrapNegate({ [node.field]: node.criterion }, node.negate);
    case "comparison":
      return wrapNegate({ field_comparisons: [node.comparison] }, node.negate);
    case "relation": {
      const childDict = serializeNode(node.child); // {} | {AND:…} | {OR:…} | {NOT:…}
      const relationDict: Json = {
        ...(node.match !== "ANY" ? { match: node.match } : {}),
        ...childDict,
      };
      return wrapNegate({ [node.field]: relationDict }, node.negate);
    }
  }
}

// Negating identity ({}) is still identity, so an empty dict is never wrapped.
function wrapNegate(dict: Json, negate: boolean): Json {
  if (!negate || Object.keys(dict).length === 0) return dict;
  return { NOT: [dict] };
}

// ── Import ─────────────────────────────────────────────────────────────────

export function deserialize(dict: Json, modelKey: string, registry: MetadataRegistry): GroupNode {
  return asGroup(deserializeNode(dict, modelKey, registry, 0));
}

function deserializeNode(dict: Json, modelKey: string, registry: MetadataRegistry, depth: number): FilterNode {
  if (depth > MAX_FILTER_DEPTH) {
    throw new FilterTreeError(`Filter nesting too deep (max ${MAX_FILTER_DEPTH})`);
  }
  const meta = registry[modelKey];
  if (!meta) throw new FilterTreeError(`Unknown model ${modelKey}`);

  // 1. Base: own criteria + relations + AND-subs, all &-composed (pre-OR).
  const baseChildren: FilterNode[] = [];
  for (const key of Object.keys(dict)) {
    if (RESERVED_KEYS.has(key)) continue;
    const value = dict[key];
    if (key in meta.relations) {
      if (isObject(value)) {
        baseChildren.push(relationNode(key, value, meta.relations[key], registry, depth));
      }
    } else if (meta.fields.has(key) && isObject(value)) {
      baseChildren.push({ kind: "criterion", field: key, criterion: value, negate: false });
    }
    // else: unknown key or non-object value -> dropped (backend from_json parity)
  }
  const andSubs = asArray(dict.AND);
  checkBreadth(andSubs);
  for (const sub of andSubs) {
    if (isObject(sub)) baseChildren.push(deserializeNode(sub, modelKey, registry, depth + 1));
  }
  let core: FilterNode = collapse(group("AND", baseChildren));

  // 2. OR: (base OR or-subs). An empty base is dropped (Q() | Q(x) == Q(x)).
  const orSubs = asArray(dict.OR);
  checkBreadth(orSubs);
  if (orSubs.length) {
    const orChildren: FilterNode[] = [];
    if (!isEmptyGroup(core)) orChildren.push(core);
    for (const sub of orSubs) {
      if (isObject(sub)) orChildren.push(deserializeNode(sub, modelKey, registry, depth + 1));
    }
    core = collapse(group("OR", orChildren));
  }

  // 3. Tail: ~NOT (negate toggled), then field_comparisons — the outermost &.
  const tail: FilterNode[] = [];
  const notSubs = asArray(dict.NOT);
  checkBreadth(notSubs);
  for (const sub of notSubs) {
    if (isObject(sub)) tail.push(withNegateToggled(deserializeNode(sub, modelKey, registry, depth + 1)));
  }
  const comparisons = asArray(dict.field_comparisons);
  if (comparisons.length > MAX_FIELD_COMPARISONS) {
    throw new FilterTreeError(`Too many field_comparisons (max ${MAX_FIELD_COMPARISONS})`);
  }
  for (const comparison of comparisons) {
    if (isObject(comparison)) tail.push({ kind: "comparison", comparison, negate: false });
  }

  if (!tail.length) return core;
  const andChildren: FilterNode[] = [];
  if (!isEmptyGroup(core)) andChildren.push(core);
  andChildren.push(...tail);
  return collapse(group("AND", andChildren));
}

function relationNode(
  field: string,
  raw: Json,
  targetModel: string,
  registry: MetadataRegistry,
  depth: number,
): FilterNode {
  const sub: Json = { ...raw };
  const match = parseMatch(sub.match);
  delete sub.match;
  const child = asGroup(deserializeNode(sub, targetModel, registry, depth + 1));
  return { kind: "relation", field, match, child, negate: false };
}

function parseMatch(value: unknown): RelationMatch {
  if (value == null) return "ANY";
  if (value === "ANY" || value === "NONE" || value === "ALL") return value;
  throw new FilterTreeError(`Unknown relation match ${JSON.stringify(value)}`);
}

// Negate is a composable node property: toggling the returned node's flag means
// "negate this node" (serialize wraps it in {NOT:[…]}), so ~~x cancels and no
// De Morgan rewrite is needed.
function withNegateToggled(node: FilterNode): FilterNode {
  return { ...node, negate: !node.negate };
}

// A single-child AND/OR group is its child (which keeps its own negate).
function collapse(node: FilterNode): FilterNode {
  if (node.kind === "group" && !node.negate && node.children.length === 1) {
    return node.children[0];
  }
  return node;
}

function isEmptyGroup(node: FilterNode): boolean {
  return node.kind === "group" && node.children.length === 0 && !node.negate;
}

function asGroup(node: FilterNode): GroupNode {
  if (node.kind === "group" && !node.negate) return node;
  return group("AND", [node]);
}

function asArray(value: unknown): unknown[] {
  if (value == null) return [];
  return Array.isArray(value) ? value : [value];
}

function checkBreadth(list: unknown[]): void {
  if (list.length > MAX_FILTER_BREADTH) {
    throw new FilterTreeError(`Operator list too long (max ${MAX_FILTER_BREADTH})`);
  }
}

function isObject(value: unknown): value is Json {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}
