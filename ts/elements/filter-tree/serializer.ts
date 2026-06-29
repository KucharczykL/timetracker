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
