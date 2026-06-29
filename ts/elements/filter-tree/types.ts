/**
 * Filter-tree node model + import metadata interface (issue #188).
 *
 * The discriminated union every nested-filter-builder component switches on, plus
 * the per-model metadata the importer needs to classify JSON keys. Types only +
 * shared constants; the transform logic lives in `serializer.ts`.
 */

export type Connective = "AND" | "OR";
export type RelationMatch = "ANY" | "NONE" | "ALL";

// Opaque to the serializer: whatever a leaf widget produced. Never inspected.
export type CriterionPayload = Record<string, unknown>;

// Opaque to the serializer: whatever a field-comparison widget produced.
export type ComparisonPayload = Record<string, unknown>;

export interface GroupNode {
  kind: "group";
  connective: Connective; // negation is a separate flag, never a connective
  // negate on a group with no children is meaningless; silently dropped on
  // export — wrapNegate returns identity when the inner dict is empty.
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
  | "INVALID_MATCH";

export class FilterTreeError extends Error {
  constructor(message: string, readonly code: FilterTreeErrorCode) {
    super(message);
    this.name = "FilterTreeError";
  }
}
