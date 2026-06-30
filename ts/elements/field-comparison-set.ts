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

interface Column {
  value: string;
  label: string;
  group: string;
  operators: string[]; // server-supplied allowed operators (#152)
}

export interface ComparisonRow {
  left: string;
  right: string;
  modifier: string;
  granularity?: "date"; // omitted when "raw" to keep filter JSON compact
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

function fillSelect(
  select: HTMLSelectElement,
  options: [string, string][],
  selected: string,
  placeholder: string,
): void {
  select.textContent = "";
  const blank = document.createElement("option");
  blank.value = "";
  blank.textContent = placeholder;
  select.appendChild(blank);
  for (const [value, label] of options) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    if (value === selected) option.selected = true;
    select.appendChild(option);
  }
}

/** Rebuild a row's operator + right-column options from its left column. The
 * reusable single-row unit (see file header). */
function refreshRow(row: HTMLElement, columns: Column[]): void {
  const left = row.querySelector<HTMLSelectElement>("[data-fc-left]");
  const operator = row.querySelector<HTMLSelectElement>("[data-fc-op]");
  const right = row.querySelector<HTMLSelectElement>("[data-fc-right]");
  if (!left || !operator || !right) return;

  // Saved values: data-selected on first paint, then the live value afterwards.
  const operatorSaved = operator.getAttribute("data-selected") ?? operator.value;
  const rightSaved = right.getAttribute("data-selected") ?? right.value;
  operator.removeAttribute("data-selected");
  right.removeAttribute("data-selected");

  const leftColumn = columns.find((column) => column.value === left.value) ?? null;
  const group = leftColumn?.group ?? null;

  // Day-granular toggle is only meaningful for datetime operands.
  const granularityWrap = row.querySelector<HTMLElement>("[data-fc-granularity-wrap]");
  const granularityInput = row.querySelector<HTMLInputElement>("[data-fc-granularity]");
  const isDatetime = group === "datetime";
  if (granularityWrap) granularityWrap.hidden = !isDatetime;
  if (granularityInput && !isDatetime) granularityInput.checked = false;

  if (!leftColumn || !group) {
    fillSelect(operator, [], "", "—");
    fillSelect(right, [], "", "column…");
    operator.disabled = true;
    right.disabled = true;
    return;
  }
  operator.disabled = false;
  right.disabled = false;
  // `?? []` defends against a columns prop missing `operators` (server/client
  // skew, a stale cached page): degrade to an empty operator list rather than
  // throwing mid-loop and leaving the rest of the rows unwired.
  const operators = leftColumn.operators ?? [];
  fillSelect(
    operator,
    operators.map((modifier) => [modifier, OPERATOR_LABELS[modifier] ?? modifier]),
    operatorSaved,
    "—",
  );
  fillSelect(
    right,
    columns
      .filter((column) => column.group === group && column.value !== left.value)
      .map((column) => [column.value, column.label]),
    rightSaved,
    "column…",
  );
}

function wireRow(row: HTMLElement, columns: Column[]): void {
  refreshRow(row, columns);
  row
    .querySelector<HTMLSelectElement>("[data-fc-left]")
    ?.addEventListener("change", () => refreshRow(row, columns));
  row
    .querySelector<HTMLElement>("[data-fc-remove]")
    ?.addEventListener("click", () => row.remove());
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
    const left = row.querySelector<HTMLSelectElement>("[data-fc-left]")?.value ?? "";
    const modifier = row.querySelector<HTMLSelectElement>("[data-fc-op]")?.value ?? "";
    const right = row.querySelector<HTMLSelectElement>("[data-fc-right]")?.value ?? "";
    const byDay = row.querySelector<HTMLInputElement>("[data-fc-granularity]");
    const byDayWrap = row.querySelector<HTMLElement>("[data-fc-granularity-wrap]");
    const isDate = Boolean(byDay?.checked && byDayWrap && !byDayWrap.hidden);
    if (left && right && modifier && left !== right) {
      const entry: ComparisonRow = { left, right, modifier };
      if (isDate) entry.granularity = "date";
      comparisons.push(entry);
    }
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
