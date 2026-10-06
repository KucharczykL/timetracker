/**
 * Field-to-field comparison row logic ("left <op> right", #167/#246).
 *
 * Drives the nested filter builder's comparison leaves: each row's left column
 * is server-rendered with the full column option set (the template from
 * common/components/filters.py comparison_row_template); this module fills the
 * operator picker from the chosen column's server-supplied `operators` list and
 * the right-column picker from the same-group columns, restoring any saved
 * value stashed in data-selected. filter-group.ts wires and reads the rows.
 */
import type { ComparisonRow, RelationMatch } from "./filter-tree/types.js";
import type {
  SearchSelectElement,
  SearchSelectOption,
  SearchSelectOptionGroup,
} from "./search-select.js";
import { choiceControl, isChoicePick, type ChoiceControl } from "./choice-control.js";
// The comparable-column shape AND the comparison-space vocabulary are codegen'd
// from Python (common/criteria.py) by `manage.py gen_element_types` (#152/#284):
// `SPACE_GROUPS` is the Python `SPACE_GROUPS` table, `SPACE_ORDERED_MODIFIERS`
// is `Modifier.for_ordered_field_comparisons()` — so vocabulary drift fails
// `tsc` instead of hiding behind a hand-kept mirror. `ComparableColumn` is
// re-exported under its historical `Column` name for existing consumers.
import {
  SPACE_GROUPS,
  SPACE_ORDERED_MODIFIERS,
  type ComparableColumn,
  type ComparisonGroup,
  type ComparisonSpace,
} from "../generated/filter-metadata.js";

// The row shape lives in filter-tree/types.ts (shared with the serializer +
// completeness check); re-exported here for the widget's existing consumers.
export type { ComparisonRow };
export type { ComparableColumn };
export type Column = ComparableColumn;

// The two operands are searchable SearchSelect comboboxes (#282 review): the
// option lists (own + FK + multi-valued blocks) outgrew a plain <select>. Each is
// wrapped in a `[data-fc-left]` / `[data-fc-right]` marker; the <search-select>
// element inside carries the committed value in a hidden input and exposes
// setSelected / setOptions / clearSelection.
type OperandMarker = "data-fc-left" | "data-fc-right";

function operandElement(row: HTMLElement, marker: OperandMarker): SearchSelectElement | null {
  return row.querySelector<SearchSelectElement>(`[${marker}] search-select`);
}

function operandValue(row: HTMLElement, marker: OperandMarker): string {
  return choiceControl(row, marker)?.read() ?? "";
}

const OPERATOR = "data-fc-op";
const QUANTIFIER = "data-fc-quantifier";

function operatorControl(row: HTMLElement): ChoiceControl | null {
  return choiceControl(row, OPERATOR);
}

// The wrapper carries the seed and the hidden state.
function slot(row: HTMLElement, marker: string): HTMLElement | null {
  return row.querySelector<HTMLElement>(`[${marker}]`);
}

// The seed on first paint, else what the picker holds.
function takeSeed(row: HTMLElement, marker: string, control: ChoiceControl): string {
  const wrapper = slot(row, marker);
  const saved = wrapper?.getAttribute("data-selected");
  wrapper?.removeAttribute("data-selected");
  return saved || control.read() || "";
}

/** The committed value of one operand combobox, for callers outside this module
 *  (filter-group's "touched" gate). `container` is the comparison row or the
 *  wrapping value cell. */
export function comparisonOperandValue(
  container: HTMLElement,
  side: "left" | "right",
): string {
  return operandValue(container, side === "left" ? "data-fc-left" : "data-fc-right");
}

function columnOption(column: Column): SearchSelectOption {
  return {
    value: column.value,
    label: column.label,
    data: { group: column.group, multivalued: String(column.multivalued) },
  };
}

// Presentation-only glyphs for the operator tokens the server sends. Not a
// source of truth for *which* operators are valid — that's the per-column
// `operators` list (server-derived from _allowed_comparison_modifiers). A token
// with no glyph here falls back to its raw value, so an added operator still
// renders. Intentionally NOT contract-guarded against the Python enum: these are
// labels, not vocabulary, so a renamed modifier degrades to its raw token (e.g.
// "GREATER_THAN" instead of ">") rather than breaking — acceptable for a
// cosmetic map.
const OPERATOR_LABELS: Record<string, string> = {
  EQUALS: "=",
  NOT_EQUALS: "≠",
  GREATER_THAN: ">",
  LESS_THAN: "<",
  GREATER_THAN_OR_EQUAL: "≥",
  LESS_THAN_OR_EQUAL: "≤",
  INCLUDES: "contains",
  EXCLUDES: "doesn't contain",
};

// Presentation labels per comparison space. Keyed by the codegen'd
// `ComparisonSpace`, so a space added in Python fails tsc here until labeled.
const SPACE_HEADERS: Record<ComparisonSpace, string> = {
  date: "By date",
  year: "By year",
};

// The granularity type: "raw" means a plain column-to-column comparison within
// the same group; the codegen'd `ComparisonSpace` values are the cross-group
// comparison spaces. Mirrors `ComparisonGranularity = ComparisonSpace | "raw"`
// in common/criteria.py — only the trivial `| "raw"` shape is repeated here;
// the space vocabulary itself is generated.
export type Granularity = ComparisonSpace | "raw";

/** Pack a modifier + granularity into the wire value the server also emits.
 *  Mirrors _pack_operator in common/components/filters.py. */
export function packOperator(modifier: string, granularity: Granularity): string {
  return granularity === "raw" ? modifier : `${modifier}:${granularity}`;
}

/** Unpack a wire value into its modifier + granularity components.
 *  Mirrors the inverse of _pack_operator in common/components/filters.py. */
export function unpackOperator(value: string): { modifier: string; granularity: Granularity } {
  const colonIndex = value.indexOf(":");
  if (colonIndex === -1) {
    return { modifier: value, granularity: "raw" };
  }
  const modifier = value.slice(0, colonIndex);
  const suffix = value.slice(colonIndex + 1);
  // Validate the suffix against the codegen'd space table, not a literal list.
  // Object.hasOwn, not `in`: `in` walks the prototype chain, so a crafted
  // suffix like "toString" would classify as a space and poison downstream
  // SPACE_GROUPS lookups with inherited Object.prototype members.
  const granularity: Granularity = Object.hasOwn(SPACE_GROUPS, suffix)
    ? (suffix as ComparisonSpace)
    : "raw";
  return { modifier, granularity };
}

function optionGroup(label: string, options: [string, string][]): SearchSelectOptionGroup {
  return { label, options: options.map(([value, text]) => ({ value, label: text, data: {} })) };
}

/** Repopulate the right-operand combobox with the columns type/space-compatible
 *  with the chosen left column + operator (#282 review). Runs client-side via the
 *  SearchSelect `.setOptions` primitive; a still-compatible committed right value
 *  is preserved, an incompatible one dropped. The <search-select> must be live
 *  (connected), so this runs from refreshRow, never during the detached build. */
function refreshRightOptions(row: HTMLElement, columns: Column[]): void {
  const right = operandElement(row, "data-fc-right");
  const operator = operatorControl(row);
  if (!right || !operator) return;

  const leftValue = operandValue(row, "data-fc-left");
  const leftColumn = columns.find((column) => column.value === leftValue) ?? null;
  if (!leftColumn) {
    right.setOptions([]);
    return;
  }

  // No fallback on the space lookup: unpackOperator only returns a granularity
  // it validated as an own key of SPACE_GROUPS, so the lookup is total.
  const { granularity } = unpackOperator(operator.read() ?? "");
  const allowedGroups: ComparisonGroup[] =
    granularity === "raw" ? [leftColumn.group] : SPACE_GROUPS[granularity];

  // comparable_columns already orders own → FK → multi-valued blocks (each sorted
  // by label), so the flat list stays grouped-ish; search covers the rest.
  const options = columns
    .filter((column) => column.value !== leftValue && allowedGroups.includes(column.group))
    .map(columnOption);
  right.setOptions(options);
}

/** The default comparison quantifier — mirrors RelationMatch's default (#282). */
const DEFAULT_QUANTIFIER: RelationMatch = "ANY";

/** Show/hide the row's quantifier select: visible only when the chosen left or
 * right operand traverses a multi-valued relation (#282). When hidden it is
 * reset to the default so a stale ALL/NONE can never leak into the serialized
 * comparison. Restores a saved value (data-selected) on first paint. */
function refreshQuantifier(row: HTMLElement, columns: Column[]): void {
  const wrapper = slot(row, QUANTIFIER);
  const quantifier = choiceControl(row, QUANTIFIER);
  if (!wrapper || !quantifier) return;
  const saved = wrapper.getAttribute("data-selected");
  if (saved !== null) {
    wrapper.removeAttribute("data-selected");
    if (saved) quantifier.write(saved);
  }
  const left = operandValue(row, "data-fc-left");
  const right = operandValue(row, "data-fc-right");
  const multivalued = columns.some(
    (column) => (column.value === left || column.value === right) && column.multivalued,
  );
  wrapper.classList.toggle("hidden", !multivalued);
  if (!multivalued) quantifier.write(DEFAULT_QUANTIFIER);
}

/** Rebuild a row's operator options + right-operand options + quantifier from its
 * current left column. The reusable single-row unit (see file header). Reads the
 * left value off its live <search-select>, so it must run after the row is
 * connected (filter-group calls it on the post-render reflect pass and on every
 * left-operand change). */
export function refreshRow(row: HTMLElement, columns: Column[]): void {
  const operator = operatorControl(row);
  if (!operator) return;
  const operatorSaved = takeSeed(row, OPERATOR, operator);

  const leftValue = operandValue(row, "data-fc-left");
  const leftColumn = columns.find((column) => column.value === leftValue) ?? null;
  const group = leftColumn?.group ?? null;

  if (!leftColumn || !group) {
    operator.setChoices([]);
    operator.setDisabled(true);
    refreshRightOptions(row, columns); // clears the right list
    refreshQuantifier(row, columns);
    return;
  }
  operator.setDisabled(false);

  // Build operator options:
  //   1. Raw options under "Exact": the column's own operators with glyph labels.
  //   2. Per non-raw space: a group of SPACE_ORDERED_MODIFIERS packed values,
  //      labeled with the space header in parentheses — but only when the left group
  //      belongs to that space (e.g. datetime is in both "date" and "year").
  // `?? []` defends against a columns prop missing `operators` (server/client
  // skew, a stale cached page): degrade to an empty operator list rather than
  // throwing mid-loop and leaving the rest of the rows unwired.
  const rawOperators = leftColumn.operators ?? [];
  const rawOptions: [string, string][] = rawOperators.map((modifier) => [
    modifier,
    OPERATOR_LABELS[modifier] ?? modifier,
  ]);

  const operatorGroups = [optionGroup("Exact", rawOptions)];
  for (const space of Object.keys(SPACE_GROUPS) as ComparisonSpace[]) {
    if (!SPACE_GROUPS[space].includes(group)) continue;
    const spaceOptions: [string, string][] = SPACE_ORDERED_MODIFIERS.map((modifier) => [
      packOperator(modifier, space),
      `${OPERATOR_LABELS[modifier] ?? modifier} (${SPACE_HEADERS[space].toLowerCase()})`,
    ]);
    operatorGroups.push(optionGroup(SPACE_HEADERS[space], spaceOptions));
  }

  operator.setChoices(operatorGroups.filter((operatorGroup) => operatorGroup.options.length));
  if (operatorSaved) operator.write(operatorSaved);
  refreshRightOptions(row, columns);
  refreshQuantifier(row, columns);
}

/** Commit the stored left/right operands onto their live <search-select>s (the
 * seed for a hydrated preset / ?filter= import, #282 review). Must run after the
 * row is connected — filter-group calls it on the post-render reflect pass, right
 * before refreshRow. Idempotent: re-committing the same value is a no-op. */
export function applyComparisonSelection(
  row: HTMLElement,
  comparison: Partial<ComparisonRow>,
  columns: Column[],
): void {
  seedOperand(row, "data-fc-left", comparison.left, columns);
  seedOperand(row, "data-fc-right", comparison.right, columns);
}

function seedOperand(
  row: HTMLElement,
  marker: OperandMarker,
  value: string | undefined,
  columns: Column[],
): void {
  const element = operandElement(row, marker);
  if (!element) return;
  if (!value) {
    element.clearSelection();
    return;
  }
  const column = columns.find((candidate) => candidate.value === value) ?? null;
  element.setSelected(value, column?.label ?? value);
}

/** Wire a comparison row's live listeners (idempotent per cell — attached once at
 *  build). A left-operand pick rebuilds the operator + right options; an operator
 *  change refilters the right list; a right-operand pick re-checks the quantifier.
 *  All three also bubble `search-select:change` / `change` to <filter-group>,
 *  which re-serialises the leaf. */
export function wireComparisonRowListeners(row: HTMLElement, columns: Column[]): void {
  if (!slot(row, OPERATOR)) return;

  // Detect which control changed by DOM ancestry, not the event's `name`: the
  // nested builder's `uniquify` suffixes each cloned picker's name.
  row.addEventListener("search-select:change", (event) => {
    // Only a real pick re-derives the row. Typing in a committed picker emits
    // a transient drop with last=null — cascading through refreshRow would
    // empty the operator and wipe the other operand irrecoverably while the
    // row merely serializes as incomplete.
    if (isChoicePick(event, "data-fc-left")) refreshRow(row, columns);
    else if (isChoicePick(event, "data-fc-right")) refreshQuantifier(row, columns);
    else if (isChoicePick(event, OPERATOR)) {
      refreshRightOptions(row, columns);
      refreshQuantifier(row, columns);
    }
  });
}

/** Read one comparison row into its complete value, or null when incomplete (a
 * missing column/operator, or the two columns equal). The reusable single-row read
 * the set loops over — the nested builder's comparison leaf (#246) reads its lone
 * row directly. `granularity` is emitted only when a non-raw packed operator is
 * selected, keeping the filter JSON compact. */
export function readComparisonRow(row: HTMLElement): ComparisonRow | null {
  const left = operandValue(row, "data-fc-left");
  const operatorValue = operatorControl(row)?.read() ?? "";
  const right = operandValue(row, "data-fc-right");
  if (!left || !right || !operatorValue || left === right) return null;
  const { modifier, granularity } = unpackOperator(operatorValue);
  if (!modifier) return null;
  const entry: ComparisonRow = { left, right, modifier };
  if (granularity !== "raw") entry.granularity = granularity;
  // The quantifier is meaningful only when visible (an operand is multi-valued,
  // #282). Emit it only when set to a non-default so raw-comparison JSON stays
  // byte-compatible; refreshQuantifier resets a hidden picker to the default.
  const quantifier = choiceControl(row, QUANTIFIER)?.read();
  if (
    quantifier &&
    !slot(row, QUANTIFIER)?.classList.contains("hidden") &&
    quantifier !== DEFAULT_QUANTIFIER
  ) {
    entry.quantifier = quantifier as RelationMatch;
  }
  return entry;
}
