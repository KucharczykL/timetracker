// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";
import {
  applyComparisonSelection,
  comparisonOperandValue,
  readComparisonRow,
  refreshRow,
  unpackOperator,
  wireComparisonRowListeners,
} from "./field-comparison-set.js";
import type { Column } from "./field-comparison-set.js";
import type { SearchSelectElement, SearchSelectOption } from "./search-select.js";
import { choiceControl } from "./choice-control.js";
import { choicePickerHtml } from "../test-setup/choice-picker.js";

Element.prototype.scrollIntoView = () => {};

afterEach(() => document.body.replaceChildren());

const ORDERED_MODIFIERS = [
  "EQUALS",
  "NOT_EQUALS",
  "GREATER_THAN",
  "LESS_THAN",
  "GREATER_THAN_OR_EQUAL",
  "LESS_THAN_OR_EQUAL",
];
const STRING_MODIFIERS = ["INCLUDES", "EXCLUDES"];

const COLUMNS: Column[] = [
  { value: "timestamp_start", label: "Timestamp Start", group: "datetime", operators: ORDERED_MODIFIERS, source: "Session", multivalued: false },
  { value: "timestamp_end", label: "Timestamp End", group: "datetime", operators: ORDERED_MODIFIERS, source: "Session", multivalued: false },
  { value: "note", label: "Note", group: "string", operators: STRING_MODIFIERS, source: "Session", multivalued: false },
  { value: "game__year_released", label: "Game: Year Released", group: "number", operators: ORDERED_MODIFIERS, source: "Game", multivalued: false },
  { value: "game__purchases__date_refunded", label: "Game › Purchases: Refunded", group: "date", operators: ORDERED_MODIFIERS, source: "Game › Purchases", multivalued: true },
];

/** The row _field_comparison_row emits, connected, so every picker wires. */
function buildRow(operatorSelected = "", quantifierSelected = ""): HTMLElement {
  const row = document.createElement("div");
  row.setAttribute("data-fc-row", "");
  const operatorSeed = operatorSelected ? ` data-selected="${operatorSelected}"` : "";
  const quantifierSeed = quantifierSelected ? ` data-selected="${quantifierSelected}"` : "";
  row.innerHTML =
    `<div data-fc-left>${choicePickerHtml({
      name: "fc-left",
      rows: COLUMNS.map((column) => ({ value: column.value, label: column.label })),
    })}</div>` +
    `<div data-fc-op${operatorSeed}>${choicePickerHtml({ name: "fc-op" })}</div>` +
    `<div data-fc-quantifier class="hidden"${quantifierSeed}>${choicePickerHtml({
      name: "fc-quantifier",
      rows: ["ANY", "NONE", "ALL"].map((value) => ({ value, label: value.toLowerCase() })),
      held: "ANY",
    })}</div>` +
    `<div data-fc-right>${choicePickerHtml({ name: "fc-right" })}</div>`;
  document.body.append(row);
  return row;
}

function operand(row: HTMLElement, side: "left" | "right"): SearchSelectElement {
  return row.querySelector<SearchSelectElement>(`[data-fc-${side}] search-select`)!;
}

// The rows a picker offers now.
function offered(picker: HTMLElement): SearchSelectOption[] {
  return [...picker.querySelectorAll<HTMLElement>("[data-search-select-option]")].map((row) => {
    const data: Record<string, string> = {};
    for (const key of ["group", "multivalued"]) {
      const value = row.getAttribute(`data-${key}`);
      if (value !== null) data[key] = value;
    }
    return { value: row.getAttribute("data-value") ?? "", label: row.getAttribute("data-label") ?? "", data };
  });
}

function groupHeaders(row: HTMLElement): string[] {
  return [...row.querySelectorAll("[data-fc-op] [data-search-select-group-header]")].map(
    (header) => header.textContent ?? "",
  );
}

function operatorBox(row: HTMLElement): HTMLInputElement {
  return row.querySelector<HTMLInputElement>("[data-fc-op] [data-search-select-search]")!;
}

describe("unpackOperator", () => {
  it("bare modifier is raw space", () => {
    expect(unpackOperator("EQUALS")).toEqual({ modifier: "EQUALS", granularity: "raw" });
  });
  it("suffixed modifier carries its date space", () => {
    expect(unpackOperator("LESS_THAN:date")).toEqual({ modifier: "LESS_THAN", granularity: "date" });
  });
  it("suffixed modifier carries its year space", () => {
    expect(unpackOperator("LESS_THAN:year")).toEqual({ modifier: "LESS_THAN", granularity: "year" });
  });
  it("unknown suffix falls through to raw", () => {
    expect(unpackOperator("EQUALS:unknown")).toEqual({ modifier: "EQUALS", granularity: "raw" });
  });
  it("Object.prototype member names are not spaces", () => {
    expect(unpackOperator("EQUALS:toString")).toEqual({ modifier: "EQUALS", granularity: "raw" });
    expect(unpackOperator("EQUALS:constructor")).toEqual({ modifier: "EQUALS", granularity: "raw" });
  });
  it("empty string yields an empty modifier in raw space", () => {
    expect(unpackOperator("")).toEqual({ modifier: "", granularity: "raw" });
  });
});

describe("refreshRow operator options", () => {
  it("offers Exact, date and year groups for a datetime left operand", () => {
    const row = buildRow();
    operand(row, "left").setSelected("timestamp_start");
    refreshRow(row, COLUMNS);
    expect(groupHeaders(row)).toEqual(["Exact", "By date", "By year"]);
  });

  it("disables the operator until a left operand is chosen", () => {
    const row = buildRow();
    refreshRow(row, COLUMNS);
    expect(operatorBox(row).disabled).toBe(true);
  });
});

describe("right-operand repopulation via setOptions", () => {
  it("raw operator keeps the right list same-group, excluding the left column", () => {
    const row = buildRow("EQUALS");
    operand(row, "left").setSelected("timestamp_start");
    refreshRow(row, COLUMNS);
    const values = offered(operand(row, "right")).map((option) => option.value);
    expect(values).toContain("timestamp_end"); // datetime, same group
    expect(values).not.toContain("timestamp_start"); // the left column itself
    expect(values).not.toContain("game__year_released"); // number, wrong group
  });

  it("year-space operator admits number columns", () => {
    const row = buildRow("EQUALS:year");
    operand(row, "left").setSelected("timestamp_start");
    refreshRow(row, COLUMNS);
    const values = offered(operand(row, "right")).map((option) => option.value);
    expect(values).toContain("game__year_released");
  });

  it("carries group + multivalued as option data", () => {
    const row = buildRow("GREATER_THAN:date");
    operand(row, "left").setSelected("timestamp_end");
    refreshRow(row, COLUMNS);
    const option = offered(operand(row, "right")).find(
      (candidate) => candidate.value === "game__purchases__date_refunded",
    )!;
    expect(option.data).toEqual({ group: "date", multivalued: "true" });
  });
});

describe("quantifier visibility + read (#282)", () => {
  it("stays hidden for a single-valued comparison", () => {
    const row = buildRow("LESS_THAN:date");
    operand(row, "left").setSelected("timestamp_start");
    operand(row, "right").setSelected("timestamp_end");
    refreshRow(row, COLUMNS);
    const quantifier = row.querySelector<HTMLElement>("[data-fc-quantifier]")!;
    expect(quantifier.classList.contains("hidden")).toBe(true);
    expect(readComparisonRow(row)?.quantifier).toBeUndefined();
  });

  it("reveals when an operand is multi-valued", () => {
    const row = buildRow("GREATER_THAN:date");
    operand(row, "left").setSelected("timestamp_end");
    operand(row, "right").setSelected("game__purchases__date_refunded");
    refreshRow(row, COLUMNS);
    expect(row.querySelector<HTMLElement>("[data-fc-quantifier]")!.classList.contains("hidden")).toBe(false);
  });

  it("emits a non-default quantifier and omits ANY", () => {
    const row = buildRow("GREATER_THAN:date");
    operand(row, "left").setSelected("timestamp_end");
    operand(row, "right").setSelected("game__purchases__date_refunded");
    refreshRow(row, COLUMNS);
    const quantifier = choiceControl(row, "data-fc-quantifier")!;
    quantifier.write("ALL");
    expect(readComparisonRow(row)?.quantifier).toBe("ALL");
    quantifier.write("ANY");
    expect(readComparisonRow(row)?.quantifier).toBeUndefined();
  });

  it("restores a seeded quantifier via data-selected", () => {
    const row = buildRow("GREATER_THAN:date", "NONE");
    operand(row, "left").setSelected("timestamp_end");
    operand(row, "right").setSelected("game__purchases__date_refunded");
    refreshRow(row, COLUMNS);
    expect(readComparisonRow(row)?.quantifier).toBe("NONE");
  });
});

describe("readComparisonRow", () => {
  it("reads a complete comparison", () => {
    const row = buildRow("LESS_THAN:date");
    operand(row, "left").setSelected("timestamp_start");
    operand(row, "right").setSelected("timestamp_end");
    refreshRow(row, COLUMNS);
    choiceControl(row, "data-fc-op")!.write("LESS_THAN:date");
    expect(readComparisonRow(row)).toEqual({
      left: "timestamp_start",
      right: "timestamp_end",
      modifier: "LESS_THAN",
      granularity: "date",
    });
  });

  it("is null when both operands are equal", () => {
    const row = buildRow("EQUALS");
    operand(row, "left").setSelected("timestamp_start");
    operand(row, "right").setSelected("timestamp_start");
    refreshRow(row, COLUMNS);
    choiceControl(row, "data-fc-op")!.write("EQUALS");
    expect(readComparisonRow(row)).toBeNull();
  });

  it("is null when an operand is missing", () => {
    const row = buildRow("EQUALS");
    operand(row, "left").setSelected("timestamp_start");
    refreshRow(row, COLUMNS);
    expect(readComparisonRow(row)).toBeNull();
  });
});

describe("applyComparisonSelection + wiring", () => {
  it("commits stored operands onto both comboboxes", () => {
    const row = buildRow("LESS_THAN:date");
    applyComparisonSelection(
      row,
      { left: "timestamp_start", right: "timestamp_end", modifier: "LESS_THAN", granularity: "date" },
      COLUMNS,
    );
    expect(comparisonOperandValue(row, "left")).toBe("timestamp_start");
    expect(comparisonOperandValue(row, "right")).toBe("timestamp_end");
  });

  it("clears an operand when the payload omits it", () => {
    const row = buildRow();
    operand(row, "left").setSelected("timestamp_start");
    applyComparisonSelection(row, {}, COLUMNS);
    expect(comparisonOperandValue(row, "left")).toBe("");
  });

  it("a left-operand pick rebuilds the right list", () => {
    const row = buildRow();
    wireComparisonRowListeners(row, COLUMNS);
    const left = operand(row, "left");
    left.setSelected("timestamp_start");
    // setSelected is silent; simulate the pick from the operand element
    // (the listener detects the side by ancestry, not the event name). A pick
    // carries the chosen option as `last` — the listener acts only on picks.
    left.dispatchEvent(
      new CustomEvent("search-select:change", {
        bubbles: true,
        detail: {
          name: "fc-left",
          values: ["timestamp_start"],
          last: { value: "timestamp_start", label: "Timestamp Start", data: {} },
        },
      }),
    );
    expect(offered(operand(row, "right")).length).toBeGreaterThan(0);
  });

  it("a left-operand edit-clear (last=null) does not cascade through the row", () => {
    const row = buildRow("LESS_THAN:date");
    applyComparisonSelection(
      row,
      { left: "timestamp_start", right: "timestamp_end", modifier: "LESS_THAN", granularity: "date" },
      COLUMNS,
    );
    refreshRow(row, COLUMNS);
    wireComparisonRowListeners(row, COLUMNS);
    const left = operand(row, "left");
    // Typing in a committed operand transiently clears its value without a pick.
    left.clearSelection();
    left.dispatchEvent(
      new CustomEvent("search-select:change", {
        bubbles: true,
        detail: { name: "fc-left", values: [], last: null },
      }),
    );
    // The operator and right operand survive; only a real pick re-derives.
    expect(operatorBox(row).disabled).toBe(false);
    expect(choiceControl(row, "data-fc-op")!.read()).toBe("LESS_THAN:date");
    expect(comparisonOperandValue(row, "right")).toBe("timestamp_end");
  });

  it("an operator pick refilters the right list", () => {
    const row = buildRow("EQUALS");
    operand(row, "left").setSelected("timestamp_start");
    refreshRow(row, COLUMNS);
    wireComparisonRowListeners(row, COLUMNS);
    expect(offered(operand(row, "right")).map((option) => option.value)).not.toContain(
      "game__year_released",
    );
    operatorBox(row).focus();
    row
      .querySelector<HTMLElement>('[data-fc-op] [data-search-select-option][data-value="EQUALS:year"]')!
      .click();
    expect(offered(operand(row, "right")).map((option) => option.value)).toContain(
      "game__year_released",
    );
  });

  it("setOptions drops a right value no longer compatible", () => {
    const row = buildRow("EQUALS");
    operand(row, "left").setSelected("timestamp_start");
    operand(row, "right").setSelected("game__year_released"); // number, incompatible with datetime raw
    refreshRow(row, COLUMNS);
    expect(comparisonOperandValue(row, "right")).toBe("");
  });
});
