// @vitest-environment jsdom
import { describe, expect, it } from "vitest";
import {
  applyComparisonSelection,
  comparisonOperandValue,
  readComparisonRow,
  refreshRow,
  unpackOperator,
  wireComparisonRowListeners,
} from "./field-comparison-set.js";
import type { Column } from "./field-comparison-set.js";
import type { SearchSelectOption } from "./search-select.js";

// A minimal <search-select> stub implementing the contract the comparison widget
// depends on (setSelected / setOptions / clearSelection + a committed hidden
// input under [data-search-select-pills]). field-comparison-set.ts imports only
// TYPES from search-select.js, so the real element is never registered here and
// this stub owns the tag. setOptions mirrors the real one: it drops a committed
// value no longer offered.
class StubSearchSelect extends HTMLElement {
  lastOptions: SearchSelectOption[] = [];

  private pills(): HTMLElement {
    let pills = this.querySelector<HTMLElement>("[data-search-select-pills]");
    if (!pills) {
      pills = document.createElement("div");
      pills.setAttribute("data-search-select-pills", "");
      this.appendChild(pills);
    }
    return pills;
  }

  private committed(): string {
    return this.pills().querySelector<HTMLInputElement>('input[type="hidden"]')?.value ?? "";
  }

  setSelected(value: string, _label?: string): void {
    const pills = this.pills();
    pills.replaceChildren();
    const input = document.createElement("input");
    input.type = "hidden";
    input.value = value;
    pills.appendChild(input);
  }

  clearSelection(): void {
    this.pills().replaceChildren();
  }

  setOptions(options: SearchSelectOption[]): void {
    this.lastOptions = options;
    const current = this.committed();
    if (current && !options.some((option) => String(option.value) === current)) {
      this.clearSelection();
    }
  }
}
customElements.define("search-select", StubSearchSelect);

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
  { value: "game__playevents__ended", label: "Game › Play Events: Ended", group: "date", operators: ORDERED_MODIFIERS, source: "Game › Play Events", multivalued: true },
];

/** Build the row markup _field_comparison_row emits: left/right are
 *  <search-select> operands (stubbed), operator + quantifier are plain <select>s
 *  with data-selected holding the seeded value. */
function buildRow(operatorSelected = "", quantifierSelected = ""): HTMLElement {
  const row = document.createElement("div");
  row.setAttribute("data-fc-row", "");

  const left = document.createElement("div");
  left.setAttribute("data-fc-left", "");
  left.appendChild(document.createElement("search-select"));
  row.appendChild(left);

  const operator = document.createElement("select");
  operator.setAttribute("data-fc-op", "");
  if (operatorSelected) operator.setAttribute("data-selected", operatorSelected);
  row.appendChild(operator);

  const quantifier = document.createElement("select");
  quantifier.setAttribute("data-fc-quantifier", "");
  quantifier.className = "hidden";
  for (const value of ["ANY", "ALL", "NONE"]) {
    const option = document.createElement("option");
    option.value = value;
    quantifier.appendChild(option);
  }
  if (quantifierSelected) quantifier.setAttribute("data-selected", quantifierSelected);
  row.appendChild(quantifier);

  const right = document.createElement("div");
  right.setAttribute("data-fc-right", "");
  right.appendChild(document.createElement("search-select"));
  row.appendChild(right);
  return row;
}

function operand(row: HTMLElement, side: "left" | "right"): StubSearchSelect {
  return row.querySelector<StubSearchSelect>(`[data-fc-${side}] search-select`)!;
}

function optgroupLabels(select: HTMLSelectElement): string[] {
  return [...select.querySelectorAll("optgroup")].map((group) => group.label);
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
    expect(optgroupLabels(row.querySelector("[data-fc-op]")!)).toEqual(["Exact", "By date", "By year"]);
  });

  it("disables the operator until a left operand is chosen", () => {
    const row = buildRow();
    refreshRow(row, COLUMNS);
    expect(row.querySelector<HTMLSelectElement>("[data-fc-op]")!.disabled).toBe(true);
  });
});

describe("right-operand repopulation via setOptions", () => {
  it("raw operator keeps the right list same-group, excluding the left column", () => {
    const row = buildRow("EQUALS");
    operand(row, "left").setSelected("timestamp_start");
    refreshRow(row, COLUMNS);
    const values = operand(row, "right").lastOptions.map((option) => option.value);
    expect(values).toContain("timestamp_end"); // datetime, same group
    expect(values).not.toContain("timestamp_start"); // the left column itself
    expect(values).not.toContain("game__year_released"); // number, wrong group
  });

  it("year-space operator admits number columns", () => {
    const row = buildRow("EQUALS:year");
    operand(row, "left").setSelected("timestamp_start");
    refreshRow(row, COLUMNS);
    const values = operand(row, "right").lastOptions.map((option) => option.value);
    expect(values).toContain("game__year_released");
  });

  it("carries group + multivalued as option data", () => {
    const row = buildRow("GREATER_THAN:date");
    operand(row, "left").setSelected("timestamp_end");
    refreshRow(row, COLUMNS);
    const option = operand(row, "right").lastOptions.find(
      (candidate) => candidate.value === "game__playevents__ended",
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
    const quantifier = row.querySelector<HTMLSelectElement>("[data-fc-quantifier]")!;
    expect(quantifier.classList.contains("hidden")).toBe(true);
    expect(readComparisonRow(row)?.quantifier).toBeUndefined();
  });

  it("reveals when an operand is multi-valued", () => {
    const row = buildRow("GREATER_THAN:date");
    operand(row, "left").setSelected("timestamp_end");
    operand(row, "right").setSelected("game__playevents__ended");
    refreshRow(row, COLUMNS);
    expect(row.querySelector<HTMLSelectElement>("[data-fc-quantifier]")!.classList.contains("hidden")).toBe(false);
  });

  it("emits a non-default quantifier and omits ANY", () => {
    const row = buildRow("GREATER_THAN:date");
    operand(row, "left").setSelected("timestamp_end");
    operand(row, "right").setSelected("game__playevents__ended");
    refreshRow(row, COLUMNS);
    const quantifier = row.querySelector<HTMLSelectElement>("[data-fc-quantifier]")!;
    quantifier.value = "ALL";
    expect(readComparisonRow(row)?.quantifier).toBe("ALL");
    quantifier.value = "ANY";
    expect(readComparisonRow(row)?.quantifier).toBeUndefined();
  });

  it("restores a seeded quantifier via data-selected", () => {
    const row = buildRow("GREATER_THAN:date", "NONE");
    operand(row, "left").setSelected("timestamp_end");
    operand(row, "right").setSelected("game__playevents__ended");
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
    row.querySelector<HTMLSelectElement>("[data-fc-op]")!.value = "LESS_THAN:date";
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
    row.querySelector<HTMLSelectElement>("[data-fc-op]")!.value = "EQUALS";
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
    // The stub does not emit events; simulate the pick from the operand element
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
    expect(operand(row, "right").lastOptions.length).toBeGreaterThan(0);
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
    const operator = row.querySelector<HTMLSelectElement>("[data-fc-op]")!;
    expect(operator.disabled).toBe(false);
    expect(operator.value).toBe("LESS_THAN:date");
    expect(comparisonOperandValue(row, "right")).toBe("timestamp_end");
  });

  it("setOptions drops a right value no longer compatible", () => {
    const row = buildRow("EQUALS");
    operand(row, "left").setSelected("timestamp_start");
    operand(row, "right").setSelected("game__year_released"); // number, incompatible with datetime raw
    refreshRow(row, COLUMNS);
    expect(comparisonOperandValue(row, "right")).toBe("");
  });
});
