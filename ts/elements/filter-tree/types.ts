/**
 * Filter-tree node model + import metadata interface (issue #188).
 *
 * The discriminated union every nested-filter-builder component switches on, plus
 * the per-model metadata the importer needs to classify JSON keys. Types only +
 * shared constants; the transform logic lives in `serializer.ts`.
 */

export type Connective = "AND" | "OR";
export type RelationMatch = "ANY" | "NONE" | "ALL";

// A Modifier value, e.g. "EQUALS" — mirrors the Python `ModifierToken` alias.
export type ModifierToken = string;

// The leaf/relation kind of a filter field — mirrors Python `FieldMetaKind`
// (common/criteria.py). The add-criterion field picker (#191) groups + resets by
// this; the field-comparison/relation kinds never reach a leaf criterion widget.
export type FieldMetaKind =
  | "string"
  | "number"
  | "date"
  | "bool"
  | "set"
  | "field-comparison"
  | "relation";

// ── Field-metadata contract (issue #191) ──────────────────────────────────────
// The parsed shape of the `data-meta` JSON each field-picker option carries — a
// faithful mirror of the Python `FieldMeta` (common/criteria.py). NOT codegen-
// guarded yet (the Python source is the only producer); a follow-up will emit
// this from the backend. #192's leaf row consumes it to reset modifier/value.

export interface ChoiceMeta {
  value: string;
  label: string;
}

export interface RelationTarget {
  field: string;
  filter: string;
  model: string;
}

export interface FilterFieldMeta {
  name: string;
  label: string;
  kind: FieldMetaKind;
  nullable: boolean;
  choices: ChoiceMeta[];
  modifiers: ModifierToken[]; // ordered; [0] is the reset default
  relations: RelationTarget[];
}

// Opaque to the serializer: whatever a leaf widget produced. Never inspected.
export type CriterionPayload = Record<string, unknown>;

// Opaque to the serializer: whatever a field-comparison widget produced.
export type ComparisonPayload = Record<string, unknown>;

export interface GroupNode {
  kind: "group";
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
  field: string;
  criterion: CriterionPayload;
  negate: boolean;
}

export interface ComparisonLeaf {
  kind: "comparison";
  comparison: ComparisonPayload;
  negate: boolean;
}

export interface RelationNode {
  kind: "relation";
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
}

// Per-model metadata the importer consumes to classify a JSON key as a relation
// descent (and find its target model) or a criterion leaf. Unknown keys are
// dropped, mirroring the backend's `from_json` (it iterates declared fields only).
export interface ModelMeta {
  fields: ReadonlySet<string>; // valid criterion field names (includes "search")
  relations: Readonly<Record<string, string>>; // relationField -> targetModelKey
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
  | "SERIALIZE_DEPTH_EXCEEDED";

export class FilterTreeError extends Error {
  constructor(message: string, readonly code: FilterTreeErrorCode) {
    super(message);
    this.name = "FilterTreeError";
  }
}
