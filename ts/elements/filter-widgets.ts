/**
 * Shared filter value-widget logic — the per-kind readers (DOM → criterion JSON)
 * and the modifier-select enable/disable behaviors, used by BOTH the flat filter
 * bar (filter-bar.ts) and the nested filter builder's leaf row (filter-group.ts,
 * #192). Extracted verbatim from filter-bar.ts so the tree reuses the exact same
 * widget contract the bars produce via the Python `field_widget` builder (#242).
 */
import { isPresenceModifier, isRangeModifier } from "./filter-tokens.js";
import { readFilterSelect } from "./search-select.js";

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
    const value2Marker = element.querySelector('[data-number-value2]');
    const value2Input =
      value2Marker instanceof HTMLInputElement
        ? value2Marker
        : (value2Marker?.querySelector<HTMLInputElement>("input") ?? null);
    const value2 = parseNumberInputValue(value2Input);
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
// inside `valueCell` straight from its pills (issue #192's FilterSelect rework).
export function readTreeSetWidget(valueCell: HTMLElement): Record<string, unknown> | null {
  const searchSelect = valueCell.querySelector<HTMLElement>("search-select");
  if (!searchSelect) return null;
  const { included, excluded, modifier } = readFilterSelect(searchSelect);
  return buildSetCriterion(included, excluded, modifier);
}

// Read one leaf value cell into a criterion payload by kind — the nested builder's
// entry point. For `set` it self-serializes; for the scalar kinds it reuses the
// shared readers. Returns null when the widget carries no usable value (incomplete).
export function readLeafWidget(valueCell: HTMLElement, kind: string): Record<string, unknown> | null {
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
    default:
      return null;
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
