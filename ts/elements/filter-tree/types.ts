/**
 * Filter-tree node model + import metadata interface (issue #188).
 *
 * The discriminated union every nested-filter-builder component switches on, plus
 * the per-model metadata the importer needs to classify JSON keys. Types only +
 * shared constants; the transform logic lives in `serializer.ts`.
 */

export type Connective = "AND" | "OR";
export type RelationMatch = "ANY" | "NONE" | "ALL";

// ── Field-metadata contract (issue #247) ──────────────────────────────────────
// The parsed shape of the `data-meta` JSON each field-picker option carries.
// Codegen'd from the Python `FieldMeta` & friends (common/criteria.py) by
// `manage.py gen_element_types`, so the contract can't drift silently — a Python
// schema change re-emits these and breaks `tsc`. Imported here (so `ComparisonRow`
// below can reference `ModifierToken`) and re-exported through this barrel — with
// `FieldMeta` kept available under its historical `FilterFieldMeta` name — so
// consumers keep importing from `./types.js`. #192's leaf row consumes it to reset
// modifier/value.
import type {
  ChoiceMeta,
  FieldMeta,
  FieldMetaKind,
  ModifierToken,
  RelationTarget,
} from "../../generated/filter-metadata.js";

export type {
  ChoiceMeta,
  FieldMeta,
  FieldMeta as FilterFieldMeta,
  FieldMetaKind,
  ModifierToken,
  RelationTarget,
};

// Opaque to the serializer: whatever a leaf widget produced. Never inspected.
export type CriterionPayload = Record<string, unknown>;

// The concrete shape one field-comparison row produces (issue #246): two column
// names + a modifier, plus an optional comparison space (date or year granularity;
// omitted → raw, so the filter JSON stays compact). Lives here — not the DOM widget
// module — so the widget, the serializer, and the completeness check share one definition.
export interface ComparisonRow {
  left: string;
  right: string;
  modifier: ModifierToken;
  granularity?: "date" | "year";
}

// What a field-comparison leaf carries: a Partial while the user fills it (a fresh
// leaf is `{}`), a full ComparisonRow once complete. The serializer wraps it
// verbatim into `field_comparisons: [payload]` and never inspects it;
// `isComparisonComplete` (operations.ts) is the single place its shape is read, and
// `Partial<ComparisonRow>` makes that read typo-checked (a renamed field fails tsc).
export type ComparisonPayload = Partial<ComparisonRow>;

// Every node carries a stable client-only `id` (see node-id.ts): the serializer
// ignores it (never reaches the wire); <filter-group> reconciles DOM on it so a
// leaf's live widget survives structural edits. Assigned at construction by the
// factories + deserialize; preserved through the immutable ops via `{...node}`.
export interface GroupNode {
  kind: "group";
  id: string;
  connective: Connective; // negation is a separate flag, never a connective
  // negate on a group with no children is meaningless and serializes away
  // (wrapNegate returns identity for an empty dict). The builder never lets that
  // state arise: non-root groups auto-collapse when emptied, and the empty root
  // renders a header-less "matches all" state with no NOT chip (issue #236). The
  // wrapNegate guard remains only as defense for imported/legacy JSON.
  negate: boolean;
  children: FilterNode[];
}

export interface CriterionLeaf {
  kind: "criterion";
  id: string;
  field: string;
  criterion: CriterionPayload;
  // Aggregate scope (issue #151): a sub-filter over the related rows the
  // aggregate reduces, e.g. session_count counting only Steam Deck sessions.
  // Present only on aggregate fields (ModelMeta.scopes says which, and names the
  // model the group's rows filter). Serializes as a `scope` key inside the
  // criterion payload; an empty group serializes away (unscoped is canonical).
  scope?: GroupNode;
  negate: boolean;
}

export interface ComparisonLeaf {
  kind: "comparison";
  id: string;
  comparison: ComparisonPayload;
  negate: boolean;
}

export interface RelationNode {
  kind: "relation";
  id: string;
  field: string;
  match: RelationMatch;
  child: GroupNode; // exactly one canonical group
  negate: boolean;
}

export type FilterNode = GroupNode | CriterionLeaf | ComparisonLeaf | RelationNode;

// Payload of the `filter-tree-change` CustomEvent the <filter-group> shell
// dispatches after every edit — the new root tree. Named so producer (the
// element) and consumers (2d serialize/count, tests) share one typed contract,
// mirroring the OpenMenuDetail precedent in menu-behavior.ts.
export interface FilterTreeChangeDetail {
  tree: GroupNode;
  // How many criterion leaves are incomplete (no field, or a value widget with no
  // usable value / a half-filled BETWEEN). The builder page (#192 comp 10) disables
  // Apply while this is > 0; incomplete leaves are excluded from serializeForQuery.
  incompleteCount: number;
}

// Per-model metadata the importer consumes to classify a JSON key as a relation
// descent (and find its target model) or a criterion leaf. Unknown keys are
// dropped, mirroring the backend's `from_json` (it iterates declared fields only).
export interface ModelMeta {
  fields: ReadonlySet<string>; // valid criterion field names (includes "search")
  relations: Readonly<Record<string, string>>; // relationField -> targetModelKey
  // aggregateField -> the model its scope sub-filter targets (issue #151); keys
  // are a subset of `fields` (an aggregate is still a criterion field).
  scopes: Readonly<Record<string, string>>;
}

export type MetadataRegistry = Readonly<Record<string, ModelMeta>>; // modelKey -> meta

// Mirror the backend parse-time caps (common/criteria.py:791,802,803) so the builder
// and backend agree on validity and a deep blob cannot blow the JS stack.
export const MAX_FILTER_DEPTH = 10;
export const MAX_FILTER_BREADTH = 100;
export const MAX_FIELD_COMPARISONS = 100;

export const RESERVED_KEYS: ReadonlySet<string> = new Set([
  "AND",
  "OR",
  "NOT",
  "match",
  "field_comparisons",
]);

export type FilterTreeErrorCode =
  | "DEPTH_EXCEEDED"
  | "BREADTH_EXCEEDED"
  | "FIELD_COMPARISONS_EXCEEDED"
  | "INVALID_FIELD_COMPARISON"
  | "UNKNOWN_MODEL"
  | "INVALID_MATCH"
  | "INVALID_SCOPE"
  | "SERIALIZE_DEPTH_EXCEEDED";

export class FilterTreeError extends Error {
  constructor(message: string, readonly code: FilterTreeErrorCode) {
    super(message);
    this.name = "FilterTreeError";
  }
}
