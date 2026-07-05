/**
 * Shared filter value-widget logic — the per-kind readers (DOM → criterion JSON)
 * and the modifier-select enable/disable behaviors, used by BOTH the flat filter
 * bar (filter-bar.ts) and the nested filter builder's leaf row (filter-group.ts,
 * #192). Extracted verbatim from filter-bar.ts so the tree reuses the exact same
 * widget contract the bars produce via the Python `field_widget` builder (#242).
 */
import type { LeafWidgetKind } from "../generated/filter-metadata.js";
import { writeSideValue } from "./date-range-picker.js";
import { isPresenceModifier, isRangeModifier } from "./filter-tokens.js";
import { readFilterSelect, writeFilterSelect } from "./search-select.js";

export interface Criterion {
  value: unknown;
  modifier: string;
  value2?: unknown;
}

export interface PillEntry {
  id: string;
  label: string;
}

export function criterion(value: unknown, value2: unknown, modifier: string): Criterion {
  const result: Criterion = { value, modifier };
  if (value2 !== null && value2 !== undefined && value2 !== "") {
    result.value2 = value2;
  }
  return result;
}

export function parseNumberInputValue(element: HTMLInputElement | null): number | "" {
  if (!element || element.value === "") return "";
  const value = parseFloat(element.value);
  return isNaN(value) ? "" : value;
}

// The value2 slot's [data-number-value2] marker may be the input itself or a
// wrapper around one — the single lookup shared by the reader and the writer.
function resolveValue2Input(element: HTMLElement): HTMLInputElement | null {
  const marker = element.querySelector("[data-number-value2]");
  if (marker instanceof HTMLInputElement) return marker;
  return marker?.querySelector<HTMLInputElement>("input") ?? null;
}

export function buildRangeCriterion(
  valueMin: number | string,
  valueMax: number | string,
): Criterion | null {
  if (valueMin !== "" && valueMax !== "") return criterion(valueMin, valueMax, "BETWEEN");
  if (valueMin !== "") return criterion(valueMin, null, "GREATER_THAN");
  if (valueMax !== "") return criterion(valueMax, null, "LESS_THAN");
  return null;
}

export function parseJSONAttr<T>(element: Element, attr: string): T[] {
  const raw = element.getAttribute(attr);
  if (!raw) return [];
  try {
    return JSON.parse(raw);
  } catch {
    console.warn("filter-widgets: malformed JSON attribute", attr, raw);
    return [];
  }
}

// ── Per-kind readers: each scoped to a single widget element, returns a criterion
// object or null to omit the field. ──

export function readStringWidget(element: HTMLElement): Record<string, unknown> | null {
  const modifier =
    element.querySelector<HTMLSelectElement>("select[data-string-modifier-select]")?.value ??
    "EQUALS";
  if (isPresenceModifier(modifier)) {
    return { modifier };
  }
  const textInput = element.querySelector<HTMLInputElement>('input[type="text"]');
  if (textInput && textInput.value.trim()) {
    return { value: textInput.value.trim(), modifier };
  }
  return null;
}

export function readNumberWidget(element: HTMLElement): Criterion | Record<string, unknown> | null {
  const modifier =
    element.querySelector<HTMLSelectElement>("select[data-number-modifier-select]")?.value ??
    "EQUALS";
  if (isPresenceModifier(modifier)) {
    return { modifier };
  }
  const value = parseNumberInputValue(
    element.querySelector<HTMLInputElement>('input[type="number"]:not([data-number-value2])'),
  );
  if (isRangeModifier(modifier)) {
    const value2 = parseNumberInputValue(resolveValue2Input(element));
    if (value !== "") return criterion(value, value2, modifier);
    return null;
  }
  if (value !== "") return criterion(value, null, modifier);
  return null;
}

export function readDateWidget(element: HTMLElement): Criterion | null {
  const valueMin =
    element.querySelector<HTMLInputElement>("[data-range-min]")?.value ?? "";
  const valueMax =
    element.querySelector<HTMLInputElement>("[data-range-max]")?.value ?? "";
  return buildRangeCriterion(valueMin, valueMax);
}

export function readBoolWidget(element: HTMLElement): Criterion | null {
  const checked = element.querySelector<HTMLInputElement>('input[type="radio"]:checked');
  if (!checked) return null;
  return criterion(checked.value === "true", null, "EQUALS");
}

// Build a set criterion from already-read include/exclude/modifier state.
export function buildSetCriterion(
  included: PillEntry[],
  excluded: PillEntry[],
  modifier: string | null,
): Record<string, unknown> | null {
  if (modifier && isPresenceModifier(modifier)) {
    return { modifier };
  }
  if (included.length > 0 || excluded.length > 0) {
    return {
      value: included.map((item) => ({ id: item.id, label: item.label })),
      excludes: excluded.map((item) => ({ id: item.id, label: item.label })),
      modifier: modifier || "INCLUDES",
    };
  }
  return null;
}

// Flat-bar set reader: reads the data-* attributes the global readSearchSelect
// pass writes onto the <search-select> container.
export function readSetWidget(element: HTMLElement): Record<string, unknown> | null {
  return buildSetCriterion(
    parseJSONAttr<PillEntry>(element, "data-included"),
    parseJSONAttr<PillEntry>(element, "data-excluded"),
    element.getAttribute("data-modifier"),
  );
}

// Tree set reader: self-serializing, no global pass — reads the <search-select>
// inside `valueCell` (or `valueCell` itself, when the widget root IS the
// search-select, as in the quick filter bar) straight from its pills (issue
// #192's FilterSelect rework).
export function readTreeSetWidget(valueCell: HTMLElement): Record<string, unknown> | null {
  const searchSelect = valueCell.matches("search-select")
    ? valueCell
    : valueCell.querySelector<HTMLElement>("search-select");
  if (!searchSelect) return null;
  const { included, excluded, modifier } = readFilterSelect(searchSelect);
  return buildSetCriterion(included, excluded, modifier);
}

// Read one leaf value cell into a criterion payload by kind — the nested builder's
// entry point. For `set` it self-serializes; for the scalar kinds it reuses the
// shared readers. Returns null when the widget carries no usable value (incomplete).
export function readLeafWidget(
  valueCell: HTMLElement,
  kind: LeafWidgetKind,
): Record<string, unknown> | null {
  switch (kind) {
    case "string":
      return readStringWidget(valueCell);
    case "number":
      return readNumberWidget(valueCell) as Record<string, unknown> | null;
    case "date":
      return readDateWidget(valueCell) as Record<string, unknown> | null;
    case "bool":
      return readBoolWidget(valueCell) as Record<string, unknown> | null;
    case "set":
      return readTreeSetWidget(valueCell);
    case "field-comparison":
      return null; // comparison leaves are read by readComparisonRow, not here
    default: {
      // Exhaustive over LeafWidgetKind: a new widget kind fails tsc here until
      // it gets BOTH a reader case and a writeLeafWidget case (see below).
      const unhandled: never = kind;
      return unhandled;
    }
  }
}

// ── Modifier-select behaviors: enable/disable the value input(s) as the string /
// number modifier changes (presence → no value; number BETWEEN → reveal value2). ──

export function toggleStringFilterInput(select: HTMLSelectElement): void {
  const container = select.closest(".flex-col");
  if (!container) return;
  const textInput = container.querySelector<HTMLInputElement>('input[type="text"]');
  if (!textInput) return;
  const value = select.value;
  if (value === "IS_NULL" || value === "NOT_NULL") {
    textInput.disabled = true;
    textInput.value = "";
    textInput.classList.add("opacity-50", "cursor-not-allowed");
  } else {
    textInput.disabled = false;
    textInput.classList.remove("opacity-50", "cursor-not-allowed");
  }
}

export function toggleNumberFilterInput(select: HTMLSelectElement): void {
  const container = select.closest(".flex-col");
  if (!container) return;
  const inputs = container.querySelectorAll<HTMLInputElement>('input[type="number"]');
  const value2 = container.querySelector<HTMLInputElement>("[data-number-value2]");
  const modifier = select.value;
  const isPresence = modifier === "IS_NULL" || modifier === "NOT_NULL";
  const isBetween = modifier === "BETWEEN" || modifier === "NOT_BETWEEN";
  inputs.forEach((input) => {
    if (isPresence) {
      input.disabled = true;
      input.value = "";
      input.classList.add("opacity-50", "cursor-not-allowed");
    } else {
      input.disabled = false;
      input.classList.remove("opacity-50", "cursor-not-allowed");
    }
  });
  if (value2) value2.classList.toggle("hidden", isPresence || !isBetween);
}

// Delegated change handler wiring both string + number modifier toggles on a
// persistent root (the filter bar, or a filter-group leaf container).
export function setupModifierToggles(root: HTMLElement): void {
  root.addEventListener("change", (event) => {
    const target = event.target as Element;
    if (target.matches("select[data-string-modifier-select]")) {
      toggleStringFilterInput(target as HTMLSelectElement);
    } else if (target.matches("select[data-number-modifier-select]")) {
      toggleNumberFilterInput(target as HTMLSelectElement);
    }
  });
}

// ── Per-kind writers: the write-mirror of the readers above (issue #263) ──
// Hydrate a freshly-cloned blank widget from a leaf's stored criterion payload
// (preset load / ?filter= import), so serializeForQuery() — which reads the LIVE
// widgets — round-trips the prefilled values instead of dropping them. Each
// writer mirrors its server-side `_*_from_field` decode (common/components/
// filters.py). All writes are silent (no input/change events): hydration runs on
// a detached clone mid-render, and an event would reach the filter-group's
// delegated onValueEvent once attached — so the modifier toggle helpers are
// called directly instead of relying on the delegated change listener.

// Select `modifier` in a modifier <select> — only when a matching <option>
// exists, so a malformed stored modifier can't clobber the default selection.
function selectModifier(select: HTMLSelectElement | null, modifier: unknown): void {
  if (!select || typeof modifier !== "string" || modifier === "") return;
  const match = [...select.options].some((option) => option.value === modifier);
  if (match) select.value = modifier;
}

function scalarToInputValue(value: unknown): string {
  if (value === undefined || value === null) return "";
  return String(value);
}

export function writeStringWidget(element: HTMLElement, criterion: Record<string, unknown>): void {
  const select = element.querySelector<HTMLSelectElement>("select[data-string-modifier-select]");
  selectModifier(select, criterion["modifier"]);
  if (select) toggleStringFilterInput(select);
  const modifier = select?.value ?? "EQUALS";
  if (isPresenceModifier(modifier)) return; // presence carries no value; input stays disabled+empty
  const textInput = element.querySelector<HTMLInputElement>('input[type="text"]');
  // Trimmed like the read side (readStringWidget), so hydrate → serialize is stable.
  const value = scalarToInputValue(criterion["value"]).trim();
  if (textInput && value !== "") textInput.value = value;
}

export function writeNumberWidget(element: HTMLElement, criterion: Record<string, unknown>): void {
  const select = element.querySelector<HTMLSelectElement>("select[data-number-modifier-select]");
  selectModifier(select, criterion["modifier"]);
  if (select) toggleNumberFilterInput(select); // reveals value2 for BETWEEN, disables for presence
  const modifier = select?.value ?? "EQUALS";
  if (isPresenceModifier(modifier)) return;
  const valueInput = element.querySelector<HTMLInputElement>(
    'input[type="number"]:not([data-number-value2])',
  );
  const value = scalarToInputValue(criterion["value"]);
  if (valueInput && value !== "") valueInput.value = value;
  if (!isRangeModifier(modifier)) return;
  const value2Input = resolveValue2Input(element);
  const value2 = scalarToInputValue(criterion["value2"]);
  if (value2Input && value2 !== "") value2Input.value = value2;
}

// Hydrate the date range widget ONLY for modifiers the min/max pair can
// represent faithfully — the read side (readDateWidget → buildRangeCriterion)
// re-derives the modifier purely from which bounds are set, so writing an
// unrepresentable modifier's bounds would silently rewrite the query on
// Apply/count. A one-sided range stores its single bound in `value` regardless
// of side (the modifier decides the slot, mirroring _range_from_field);
// EQUALS(d) is written as the exactly-equivalent day range d..d (DateCriterion
// compiles both to the same rows — every datetime field filters via a __date
// lookup). NOT_EQUALS (a hole), NOT_BETWEEN (two rays), and presence modifiers
// have no faithful min/max form: leave the widget blank (the leaf prunes, the
// pre-hydration behavior) rather than apply a different query.
export function writeDateWidget(element: HTMLElement, criterion: Record<string, unknown>): void {
  const value = scalarToInputValue(criterion["value"]);
  const value2 = scalarToInputValue(criterion["value2"]);
  let bounds: { min: string; max: string } | null;
  switch (criterion["modifier"]) {
    case "LESS_THAN":
      bounds = { min: "", max: value };
      break;
    case "GREATER_THAN":
      bounds = { min: value, max: "" };
      break;
    case "BETWEEN":
      bounds = { min: value, max: value2 };
      break;
    case "EQUALS":
      bounds = { min: value, max: value };
      break;
    default:
      bounds = null;
  }
  if (!bounds) return;
  writeSideValue(element, "min", bounds.min);
  writeSideValue(element, "max", bounds.max);
}

// Mirrors _bool_from_field's coercion (string "true"/"1"/"yes" and friends).
export function writeBoolWidget(element: HTMLElement, criterion: Record<string, unknown>): void {
  const raw = criterion["value"];
  if (raw === undefined || raw === null) return;
  let value: boolean;
  if (typeof raw === "string") {
    const lowered = raw.toLowerCase();
    if (["true", "1", "yes"].includes(lowered)) value = true;
    else if (["false", "0", "no"].includes(lowered)) value = false;
    else value = Boolean(raw);
  } else {
    value = Boolean(raw);
  }
  const radio = element.querySelector<HTMLInputElement>(
    `input[type="radio"][value="${value ? "true" : "false"}"]`,
  );
  if (radio) radio.checked = true;
}

// Escape a user-authored value for use inside a quoted attribute selector.
// Control characters are CSS parse errors inside quoted strings, so they get
// hex-escaped (the native CSS.escape treatment); quotes and backslashes are
// backslash-escaped. Implemented locally rather than via CSS.escape so the
// behavior is identical in browsers and in jsdom (which lacks the CSS global).
function escapeSelectorValue(value: string): string {
  return value.replace(/[\u0000-\u001f\u007f"\\]/g, (character) =>
    character === '"' || character === "\\"
      ? `\\${character}`
      : `\\${character.charCodeAt(0).toString(16)} `,
  );
}

// The label a value id shows on its pill: the stored label when the payload
// carries {id, label} entries, else the pre-rendered option row's label, else
// the id itself (mirrors _extract_labeled's bare-value fallback). Ids come from
// user-authored ?filter= JSON, so the selector escape must cover control
// characters, not just quotes.
function normalizePillEntries(raw: unknown, searchSelect: HTMLElement): PillEntry[] {
  if (!Array.isArray(raw)) return [];
  const entries: PillEntry[] = [];
  for (const item of raw) {
    let id: string;
    let label = "";
    if (item !== null && typeof item === "object") {
      const record = item as { id?: unknown; label?: unknown };
      if (record.id === undefined || record.id === null) continue;
      id = String(record.id);
      if (typeof record.label === "string") label = record.label;
    } else if (typeof item === "string" || typeof item === "number") {
      id = String(item);
    } else {
      continue;
    }
    if (!label) {
      const optionRow = searchSelect.querySelector<HTMLElement>(
        `[data-search-select-option][data-value="${escapeSelectorValue(id)}"]`,
      );
      label = optionRow?.getAttribute("data-label") || id;
    }
    entries.push({ id, label });
  }
  return entries;
}

// Tree set writer — the mirror of readTreeSetWidget/_choice_from_raw, rendered
// through the <search-select>'s own writeFilterSelect so hydrated pills are
// identical to click-added ones. A modifier that matches one of the widget's
// pinned modifier rows becomes the sticky modifier pill (INCLUDES/EXCLUDES have
// no pinned row and no pill — the read side defaults to INCLUDES). EXCLUDES and
// NOT_EQUALS store their values in `value` but mean exclusion — the backend
// compiles them to exactly ~Q(field__in=…), the same Q the widget's exclude
// channel produces (criteria.py _value_q/to_q) — so they hydrate as ✗ exclude
// pills rather than silently inverting into includes.
export function writeTreeSetWidget(valueCell: HTMLElement, criterion: Record<string, unknown>): void {
  const searchSelect = valueCell.querySelector<HTMLElement>("search-select");
  if (!searchSelect) return;
  const modifier = typeof criterion["modifier"] === "string" ? criterion["modifier"] : "";
  const modifierRow = modifier
    ? searchSelect.querySelector<HTMLElement>(
        `[data-search-select-modifier-option="${escapeSelectorValue(modifier)}"]`,
      )
    : null;
  const valueEntries = normalizePillEntries(criterion["value"], searchSelect);
  const excludeEntries = normalizePillEntries(criterion["excludes"], searchSelect);
  const isExclusion = modifier === "EXCLUDES" || modifier === "NOT_EQUALS";
  writeFilterSelect(
    searchSelect,
    {
      included: isExclusion ? [] : valueEntries,
      excluded: isExclusion ? [...valueEntries, ...excludeEntries] : excludeEntries,
      modifier: modifierRow ? modifier : "",
    },
    modifierRow?.getAttribute("data-label") ?? "",
  );
}

// Write one leaf value cell from a criterion payload by kind — the write-mirror
// of readLeafWidget, called by the nested builder when it clones a value widget
// for a leaf that already carries a payload (preset load / ?filter= import).
// A fresh user field-pick carries only {modifier: firstModifier}, on which every
// writer is an idempotent no-op beyond selecting the already-default modifier.
export function writeLeafWidget(
  valueCell: HTMLElement,
  kind: LeafWidgetKind,
  criterion: Record<string, unknown>,
): void {
  if (Object.keys(criterion).length === 0) return;
  switch (kind) {
    case "string":
      writeStringWidget(valueCell, criterion);
      break;
    case "number":
      writeNumberWidget(valueCell, criterion);
      break;
    case "date":
      writeDateWidget(valueCell, criterion);
      break;
    case "bool":
      writeBoolWidget(valueCell, criterion);
      break;
    case "set":
      writeTreeSetWidget(valueCell, criterion);
      break;
    case "field-comparison":
      break; // comparison leaves hydrate via seedComparisonRow, not here
    default: {
      // Exhaustive over LeafWidgetKind: a new widget kind fails tsc here until
      // it gets BOTH this writer case and a readLeafWidget case (see above).
      const unhandled: never = kind;
      return unhandled;
    }
  }
}
