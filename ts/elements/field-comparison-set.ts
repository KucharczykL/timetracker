/**
 * FieldComparisonSet — build "left <op> right" field-to-field comparison rows.
 *
 * Drives common/components/filters.py FieldComparisonSet. Each row's left column
 * is server-rendered with the full column option set; this module fills the
 * operator select from the chosen column's server-supplied `operators` list and
 * the right-column select from the same-group columns, restoring any saved value
 * stashed in data-selected. The set's rows + AND/OR mode are read back by
 * filter-bar.ts on Apply (see readFieldComparisonSet).
 *
 * The single-row logic (refreshRow) is intentionally separable from the set
 * container so the nested boolean builder (#168) can reuse it inside a group.
 */
import { readFieldComparisonSetProps } from "../generated/props.js";
import type { ComparisonRow } from "./filter-tree/types.js";

// The row shape lives in filter-tree/types.ts (shared with the serializer +
// completeness check); re-exported here for the widget's existing consumers.
export type { ComparisonRow };

// The comparable-column shape is codegen'd from the Python `ComparableColumn`
// (common/criteria.py) by `manage.py gen_element_types`; imported here so the
// widget body can use it and re-exported under its historical `Column` name for
// existing consumers. This tightens `group` from a bare string to the
// `ComparisonGroup` union.
import type { ComparableColumn, ComparisonGroup } from "../generated/filter-metadata.js";

export type { ComparableColumn };
export type Column = ComparableColumn;

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

// The ordered modifiers used inside each non-raw comparison space. These are the
// operators that make sense when comparing across spaces (e.g. datetime vs number
// in year granularity). Mirrors Modifier.for_ordered_field_comparisons() in common/criteria.py.
const SPACE_ORDERED_MODIFIERS = [
  "EQUALS",
  "NOT_EQUALS",
  "GREATER_THAN",
  "LESS_THAN",
  "GREATER_THAN_OR_EQUAL",
  "LESS_THAN_OR_EQUAL",
];

// Mirrors _SPACE_GROUPS in common/criteria.py — the operand groups each
// non-raw space accepts. Two entries; if this grows, move it into the
// gen-element-types codegen next to ComparableColumn.
const SPACE_GROUPS: Record<"date" | "year", ComparisonGroup[]> = {
  date: ["date", "datetime"],
  year: ["date", "datetime", "number"],
};

const SPACE_HEADERS: Record<"date" | "year", string> = {
  date: "By date",
  year: "By year",
};

// The granularity type: "raw" means a plain column-to-column comparison within
// the same group; "date" and "year" are cross-group comparison spaces.
export type Granularity = "raw" | "date" | "year";

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
  const granularity: Granularity =
    suffix === "date" || suffix === "year" ? suffix : "raw";
  return { modifier, granularity };
}

// A group of options for fillSelect: null header means top-level (no optgroup);
// non-null header means an optgroup with that label. Empty groups are skipped.
interface OptionGroup {
  header: string | null;
  options: [string, string][]; // [value, label]
}

function fillSelect(
  select: HTMLSelectElement,
  groups: OptionGroup[],
  selected: string,
  placeholder: string,
): void {
  select.textContent = "";
  const blank = document.createElement("option");
  blank.value = "";
  blank.textContent = placeholder;
  select.appendChild(blank);
  for (const group of groups) {
    if (group.options.length === 0) continue;
    if (group.header === null) {
      // Top-level options, no optgroup wrapper
      for (const [value, label] of group.options) {
        const option = document.createElement("option");
        option.value = value;
        option.textContent = label;
        if (value === selected) option.selected = true;
        select.appendChild(option);
      }
    } else {
      const optgroup = document.createElement("optgroup");
      optgroup.label = group.header;
      for (const [value, label] of group.options) {
        const option = document.createElement("option");
        option.value = value;
        option.textContent = label;
        if (value === selected) option.selected = true;
        optgroup.appendChild(option);
      }
      select.appendChild(optgroup);
    }
  }
}

/** Rebuild a row's right-column options from its left column + selected operator.
 *  Called both on initial refreshRow and on operator change, so the right list
 *  stays filtered to the currently-selected comparison space. */
function refreshRowRightList(
  right: HTMLSelectElement,
  left: HTMLSelectElement,
  operator: HTMLSelectElement,
  columns: Column[],
): void {
  const rightSaved = right.getAttribute("data-selected") ?? right.value;
  right.removeAttribute("data-selected");

  const leftColumn = columns.find((column) => column.value === left.value) ?? null;
  const group = leftColumn?.group ?? null;

  if (!leftColumn || !group) {
    fillSelect(right, [{ header: null, options: [] }], "", "column…");
    return;
  }

  const { granularity } = unpackOperator(operator.value);
  const allowedGroups: ComparisonGroup[] =
    granularity === "raw" ? [group] : SPACE_GROUPS[granularity] ?? [group];

  // Partition columns by source: "" = own model (top-level), non-empty = FK source (optgroup).
  const ownOptions: [string, string][] = [];
  const sourceOptions = new Map<string, [string, string][]>();

  for (const column of columns) {
    if (!allowedGroups.includes(column.group)) continue;
    if (column.value === left.value) continue;
    const pair: [string, string] = [column.value, column.label];
    if (column.source === "") {
      ownOptions.push(pair);
    } else {
      let bucket = sourceOptions.get(column.source);
      if (!bucket) {
        bucket = [];
        sourceOptions.set(column.source, bucket);
      }
      bucket.push(pair);
    }
  }

  const groups: OptionGroup[] = [{ header: null, options: ownOptions }];
  for (const [source, options] of sourceOptions) {
    groups.push({ header: source, options });
  }

  fillSelect(right, groups, rightSaved, "column…");
}

/** Rebuild a row's operator + right-column options from its left column. The
 * reusable single-row unit (see file header) — the nested builder's comparison
 * leaf (#246) calls this directly on a standalone row. */
export function refreshRow(row: HTMLElement, columns: Column[]): void {
  const left = row.querySelector<HTMLSelectElement>("[data-fc-left]");
  const operator = row.querySelector<HTMLSelectElement>("[data-fc-op]");
  const right = row.querySelector<HTMLSelectElement>("[data-fc-right]");
  if (!left || !operator || !right) return;

  // Saved values: data-selected on first paint, then the live value afterwards.
  const operatorSaved = operator.getAttribute("data-selected") ?? operator.value;
  operator.removeAttribute("data-selected");

  const leftColumn = columns.find((column) => column.value === left.value) ?? null;
  const group = leftColumn?.group ?? null;

  if (!leftColumn || !group) {
    fillSelect(operator, [{ header: null, options: [] }], "", "—");
    fillSelect(right, [{ header: null, options: [] }], "", "column…");
    operator.disabled = true;
    right.disabled = true;
    return;
  }
  operator.disabled = false;
  right.disabled = false;

  // Build operator options:
  //   1. Raw options top-level: the column's own operators with glyph labels.
  //   2. Per non-raw space: an optgroup with SPACE_ORDERED_MODIFIERS packed values,
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

  const operatorGroups: OptionGroup[] = [{ header: null, options: rawOptions }];
  for (const space of ["date", "year"] as const) {
    if (!SPACE_GROUPS[space].includes(group)) continue;
    const spaceOptions: [string, string][] = SPACE_ORDERED_MODIFIERS.map((modifier) => [
      packOperator(modifier, space),
      `${OPERATOR_LABELS[modifier] ?? modifier} (${SPACE_HEADERS[space].toLowerCase()})`,
    ]);
    operatorGroups.push({ header: SPACE_HEADERS[space], options: spaceOptions });
  }

  fillSelect(operator, operatorGroups, operatorSaved, "—");

  // Fill the right list for the current operator value (uses operatorSaved restored above).
  refreshRowRightList(right, left, operator, columns);
}

/** Export the row-wiring helper so filter-group.ts can reuse it for the
 *  nested builder's comparison leaf — giving it the operator-change listener
 *  without duplicating the logic. */
export function wireComparisonRowListeners(row: HTMLElement, columns: Column[]): void {
  const operator = row.querySelector<HTMLSelectElement>("[data-fc-op]");
  const left = row.querySelector<HTMLSelectElement>("[data-fc-left]");
  const right = row.querySelector<HTMLSelectElement>("[data-fc-right]");
  if (!operator || !left || !right) return;

  left.addEventListener("change", () => refreshRow(row, columns));
  operator.addEventListener("change", () => refreshRowRightList(right, left, operator, columns));
}

function wireRow(row: HTMLElement, columns: Column[]): void {
  refreshRow(row, columns);
  wireComparisonRowListeners(row, columns);
  row
    .querySelector<HTMLElement>("[data-fc-remove]")
    ?.addEventListener("click", () => row.remove());
}

/** Read one comparison row into its complete value, or null when incomplete (a
 * missing column/operator, or the two columns equal). The reusable single-row read
 * the set folds over — the nested builder's comparison leaf (#246) reads its lone
 * row directly. `granularity` is emitted only when a non-raw packed operator is
 * selected, keeping the filter JSON compact. */
export function readComparisonRow(row: HTMLElement): ComparisonRow | null {
  const left = row.querySelector<HTMLSelectElement>("[data-fc-left]")?.value ?? "";
  const operatorValue = row.querySelector<HTMLSelectElement>("[data-fc-op]")?.value ?? "";
  const right = row.querySelector<HTMLSelectElement>("[data-fc-right]")?.value ?? "";
  if (!left || !right || !operatorValue || left === right) return null;
  const { modifier, granularity } = unpackOperator(operatorValue);
  if (!modifier) return null;
  const entry: ComparisonRow = { left, right, modifier };
  if (granularity !== "raw") entry.granularity = granularity;
  return entry;
}

/** Read the set's mode + complete rows for filter-bar.ts serialization. */
export function readFieldComparisonSet(element: HTMLElement): {
  mode: string;
  comparisons: ComparisonRow[];
} {
  const mode =
    element.querySelector<HTMLInputElement>("[data-fc-mode]:checked")?.value === "OR"
      ? "OR"
      : "AND";
  const comparisons: ComparisonRow[] = [];
  element.querySelectorAll<HTMLElement>("[data-fc-row]").forEach((row) => {
    const entry = readComparisonRow(row);
    if (entry) comparisons.push(entry);
  });
  return { mode, comparisons };
}

class FieldComparisonSetElement extends HTMLElement {
  connectedCallback(): void {
    const { columns: columnsJson } = readFieldComparisonSetProps(this);
    let columns: Column[] = [];
    try {
      columns = JSON.parse(columnsJson || "[]");
    } catch {
      console.warn("field-comparison-set: malformed columns prop", columnsJson);
    }
    const rowsContainer = this.querySelector<HTMLElement>("[data-fc-rows]");
    const template = this.querySelector<HTMLTemplateElement>("[data-fc-row-template]");
    if (!rowsContainer || !template) return;

    rowsContainer
      .querySelectorAll<HTMLElement>("[data-fc-row]")
      .forEach((row) => wireRow(row, columns));

    this.querySelector<HTMLElement>("[data-fc-add]")?.addEventListener("click", () => {
      const clone = template.content.firstElementChild?.cloneNode(true) as HTMLElement | null;
      if (!clone) return;
      rowsContainer.appendChild(clone);
      wireRow(clone, columns);
    });
  }
}

customElements.define("field-comparison-set", FieldComparisonSetElement);
