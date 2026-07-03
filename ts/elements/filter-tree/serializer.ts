/**
 * Filter-tree serializer/deserializer (issue #188).
 *
 * serialize: node tree -> canonical OperatorFilter JSON (single-key children,
 * never a mixed node). deserialize: arbitrary/legacy JSON -> node tree, faithfully
 * reproducing the backend fold order. See the design spec.
 */
import {
  type Connective,
  type CriterionLeaf,
  type FilterNode,
  type GroupNode,
  type MetadataRegistry,
  type ModelMeta,
  type RelationMatch,
  FilterTreeError,
  MAX_FIELD_COMPARISONS,
  MAX_FILTER_BREADTH,
  MAX_FILTER_DEPTH,
  RESERVED_KEYS,
} from "./types.js";
import { nextNodeId } from "./node-id.js";

type Json = Record<string, unknown>;

export function group(connective: Connective, children: FilterNode[], negate = false): GroupNode {
  return { kind: "group", id: nextNodeId(), connective, negate, children };
}

// ── Export ─────────────────────────────────────────────────────────────────

export function serialize(root: GroupNode): Json {
  return serializeNode(root, 0);
}

function serializeNode(node: FilterNode, depth: number): Json {
  // Symmetric with deserialize's guard: a cyclic in-memory node tree (a builder
  // bug — e.g. a group appended to itself) would otherwise recurse until the JS
  // stack overflows and locks the tab. Bound it and throw loudly instead.
  if (depth > MAX_FILTER_DEPTH) {
    throw new FilterTreeError(
      `Filter nesting too deep (max ${MAX_FILTER_DEPTH})`,
      "SERIALIZE_DEPTH_EXCEEDED",
    );
  }
  switch (node.kind) {
    case "group": {
      const children = node.children
        .map((child) => serializeNode(child, depth + 1))
        .filter((childJson) => Object.keys(childJson).length > 0);
      const inner: Json = children.length ? { [node.connective]: children } : {};
      return wrapNegate(inner, node.negate);
    }
    case "criterion": {
      // An aggregate's scope group (issue #151) rides inside the criterion payload
      // as a `scope` key; an empty scope group serializes away entirely (matching
      // the backend, which normalizes an empty scope to unscoped).
      const scopeJson = node.scope ? serializeNode(node.scope, depth + 1) : {};
      const criterion = Object.keys(scopeJson).length
        ? { ...node.criterion, scope: scopeJson }
        : node.criterion;
      return wrapNegate({ [node.field]: criterion }, node.negate);
    }
    case "comparison":
      return wrapNegate({ field_comparisons: [node.comparison] }, node.negate);
    case "relation": {
      const serializedChild = serializeNode(node.child, depth + 1); // {} | {AND:…} | {OR:…} | {NOT:…}
      const relationJson: Json = {
        ...(node.match !== "ANY" ? { match: node.match } : {}),
        ...serializedChild,
      };
      return wrapNegate({ [node.field]: relationJson }, node.negate);
    }
  }
}

// Negating identity ({}) is still identity, so an empty dict is never wrapped.
function wrapNegate(json: Json, negate: boolean): Json {
  if (!negate || Object.keys(json).length === 0) return json;
  return { NOT: [json] };
}

// ── Import ─────────────────────────────────────────────────────────────────

export function deserialize(json: Json, modelKey: string, registry: MetadataRegistry): GroupNode {
  return asGroup(deserializeNode(json, modelKey, registry, 0));
}

function deserializeNode(json: Json, modelKey: string, registry: MetadataRegistry, depth: number): FilterNode {
  if (depth > MAX_FILTER_DEPTH) {
    throw new FilterTreeError(`Filter nesting too deep (max ${MAX_FILTER_DEPTH})`, "DEPTH_EXCEEDED");
  }
  const meta = registry[modelKey];
  if (!meta) throw new FilterTreeError(`Unknown model ${modelKey}`, "UNKNOWN_MODEL");

  // 1. Base: own criteria + relations + AND-subs, all &-composed (pre-OR).
  const baseChildren: FilterNode[] = [];
  for (const key of Object.keys(json)) {
    if (RESERVED_KEYS.has(key)) continue;
    const value = json[key];
    // Criterion-first, mirroring Python from_json (criteria.py:1303-1317 resolves
    // _criterion_class_for before _filter_class_for). fields/relations are disjoint
    // for well-formed metadata, so order only matters if a key ever appears in both.
    if (meta.fields.has(key)) {
      if (isObject(value)) {
        baseChildren.push(criterionNode(key, value, meta, registry, depth));
      }
    } else if (key in meta.relations) {
      if (isObject(value)) {
        baseChildren.push(relationNode(key, value, meta.relations[key], registry, depth));
      }
    }
    // else: unknown key or non-object value -> dropped (backend from_json parity)
  }
  const andSubfilters = asArray(json.AND);
  checkBreadth(andSubfilters);
  for (const subfilter of andSubfilters) {
    if (isObject(subfilter)) baseChildren.push(deserializeNode(subfilter, modelKey, registry, depth + 1));
  }
  let core: FilterNode = collapse(group("AND", baseChildren));

  // 2. OR: (base OR or-subs). An empty base is dropped (Q() | Q(x) == Q(x)).
  const orSubfilters = asArray(json.OR);
  checkBreadth(orSubfilters);
  if (orSubfilters.length) {
    const orChildren: FilterNode[] = [];
    if (!isEmptyGroup(core)) orChildren.push(core);
    for (const subfilter of orSubfilters) {
      if (isObject(subfilter)) orChildren.push(deserializeNode(subfilter, modelKey, registry, depth + 1));
    }
    core = collapse(group("OR", orChildren));
  }

  // 3. Tail: ~NOT (negate toggled), then field_comparisons — the outermost &.
  const tail: FilterNode[] = [];
  const notSubfilters = asArray(json.NOT);
  checkBreadth(notSubfilters);
  for (const subfilter of notSubfilters) {
    if (isObject(subfilter)) tail.push(withNegateToggled(deserializeNode(subfilter, modelKey, registry, depth + 1)));
  }
  const comparisons = asArray(json.field_comparisons);
  if (comparisons.length > MAX_FIELD_COMPARISONS) {
    throw new FilterTreeError(`Too many field_comparisons (max ${MAX_FIELD_COMPARISONS})`, "FIELD_COMPARISONS_EXCEEDED");
  }
  for (const comparison of comparisons) {
    if (!isObject(comparison)) {
      throw new FilterTreeError(
        "field_comparisons entries must be objects",
        "INVALID_FIELD_COMPARISON",
      );
    }
    tail.push({ kind: "comparison", id: nextNodeId(), comparison, negate: false });
  }

  if (!tail.length) return core;
  const andChildren: FilterNode[] = [];
  if (!isEmptyGroup(core)) andChildren.push(core);
  andChildren.push(...tail);
  return collapse(group("AND", andChildren));
}

// A criterion leaf; on a scopable (aggregate) field, a `scope` key in the payload
// is split off into a child group over the scope's target model (issue #151). An
// empty scope deserializes to no scope at all — backend parity (it normalizes an
// empty scope to unscoped). On a non-scopable field the payload stays verbatim
// (opaque-payload principle; the backend equally ignores a stray `scope` key).
function criterionNode(
  field: string,
  raw: Json,
  meta: ModelMeta,
  registry: MetadataRegistry,
  depth: number,
): CriterionLeaf {
  const scopeModel = meta.scopes[field];
  if (scopeModel === undefined || !isObject(raw.scope)) {
    return { kind: "criterion", id: nextNodeId(), field, criterion: raw, negate: false };
  }
  const { scope: scopeJson, ...criterion } = raw;
  const child = asGroup(deserializeNode(scopeJson as Json, scopeModel, registry, depth + 1));
  return {
    kind: "criterion",
    id: nextNodeId(),
    field,
    criterion,
    ...(isEmptyGroup(child) ? {} : { scope: child }),
    negate: false,
  };
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
  return { kind: "relation", id: nextNodeId(), field, match, child, negate: false };
}

function parseMatch(value: unknown): RelationMatch {
  if (value == null) return "ANY";
  if (value === "ANY" || value === "NONE" || value === "ALL") return value;
  throw new FilterTreeError(`Unknown relation match ${JSON.stringify(value)}`, "INVALID_MATCH");
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
    throw new FilterTreeError(`Operator list too long (max ${MAX_FILTER_BREADTH})`, "BREADTH_EXCEEDED");
  }
}

function isObject(value: unknown): value is Json {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}
