// @vitest-environment jsdom
import { describe, expect, it } from "vitest";
import {
  readComparisonRow,
  refreshRow,
  unpackOperator,
  wireComparisonRowListeners,
} from "./field-comparison-set.js";
import type { Column } from "./field-comparison-set.js";

// Ordered modifiers that the server emits for ordered-type columns.
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
  {
    value: "timestamp_start",
    label: "Timestamp Start",
    group: "datetime",
    operators: ORDERED_MODIFIERS,
    source: "",
  },
  {
    value: "timestamp_end",
    label: "Timestamp End",
    group: "datetime",
    operators: ORDERED_MODIFIERS,
    source: "",
  },
  {
    value: "note",
    label: "Note",
    group: "string",
    operators: STRING_MODIFIERS,
    source: "",
  },
  {
    value: "game__year_released",
    label: "Game: Year Released",
    group: "number",
    operators: ORDERED_MODIFIERS,
    source: "Game",
  },
];

/**
 * Construct the server-rendered markup that _field_comparison_row emits:
 * - [data-fc-left]: full option set with data-group per option
 * - [data-fc-op]: empty, data-selected holds packed value
 * - [data-fc-right]: empty, data-selected holds bare path value
 */
function buildRow(leftValue: string, operatorSelected: string, rightSelected: string): HTMLElement {
  const row = document.createElement("div");
  row.setAttribute("data-fc-row", "");

  const leftSelect = document.createElement("select");
  leftSelect.setAttribute("data-fc-left", "");
  // Blank placeholder option
  const blankOption = document.createElement("option");
  blankOption.value = "";
  blankOption.textContent = "column…";
  leftSelect.appendChild(blankOption);
  for (const column of COLUMNS) {
    const option = document.createElement("option");
    option.value = column.value;
    option.textContent = column.label;
    option.setAttribute("data-group", column.group);
    leftSelect.appendChild(option);
  }
  if (leftValue) leftSelect.value = leftValue;
  row.appendChild(leftSelect);

  const operatorSelect = document.createElement("select");
  operatorSelect.setAttribute("data-fc-op", "");
  if (operatorSelected) operatorSelect.setAttribute("data-selected", operatorSelected);
  row.appendChild(operatorSelect);

  const rightSelect = document.createElement("select");
  rightSelect.setAttribute("data-fc-right", "");
  if (rightSelected) rightSelect.setAttribute("data-selected", rightSelected);
  row.appendChild(rightSelect);

  return row;
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
});

function optgroupLabels(container: HTMLElement, selector: string): string[] {
  return [...container.querySelectorAll<HTMLOptGroupElement>(`${selector} optgroup`)].map(
    (group) => group.label,
  );
}

function optionValues(container: HTMLElement, selector: string): string[] {
  return [...container.querySelectorAll<HTMLOptionElement>(`${selector} option`)].map(
    (option) => option.value,
  );
}

describe("refreshRow with a datetime left operand", () => {
  it("offers raw, date and year operator groups", () => {
    const row = buildRow("timestamp_start", "", "");
    refreshRow(row, COLUMNS);
    expect(optgroupLabels(row, "[data-fc-op]")).toEqual(["By date", "By year"]); // raw options are top-level
  });

  it("raw operators are top-level (not in optgroup)", () => {
    const row = buildRow("timestamp_start", "", "");
    refreshRow(row, COLUMNS);
    const operatorSelect = row.querySelector<HTMLSelectElement>("[data-fc-op]")!;
    // Top-level options (not inside an optgroup) carry the raw modifiers
    const topLevel = [...operatorSelect.children].filter(
      (child) => child.tagName === "OPTION",
    );
    // blank placeholder + N raw modifier options
    expect(topLevel.length).toBeGreaterThan(1);
  });

  it("year-space operator admits number columns on the right", () => {
    const row = buildRow("timestamp_start", "EQUALS:year", "");
    refreshRow(row, COLUMNS);
    expect(optionValues(row, "[data-fc-right]")).toContain("game__year_released");
  });

  it("raw operator keeps the right list same-group", () => {
    const row = buildRow("timestamp_start", "EQUALS", "");
    refreshRow(row, COLUMNS);
    const values = optionValues(row, "[data-fc-right]");
    expect(values).not.toContain("game__year_released");
    expect(values).toContain("timestamp_end");
  });

  it("date-space right list includes only date/datetime columns", () => {
    const row = buildRow("timestamp_start", "LESS_THAN:date", "");
    refreshRow(row, COLUMNS);
    const values = optionValues(row, "[data-fc-right]");
    // date space: date + datetime allowed
    expect(values).toContain("timestamp_end"); // datetime OK
    expect(values).not.toContain("game__year_released"); // number not in date space
  });

  it("excludes the left column from the right list in raw mode", () => {
    const row = buildRow("timestamp_start", "EQUALS", "");
    refreshRow(row, COLUMNS);
    expect(optionValues(row, "[data-fc-right]")).not.toContain("timestamp_start");
  });

  it("excludes the left column from the right list in year mode", () => {
    const row = buildRow("timestamp_start", "EQUALS:year", "");
    refreshRow(row, COLUMNS);
    expect(optionValues(row, "[data-fc-right]")).not.toContain("timestamp_start");
  });

  it("right list FK columns (non-empty source) render inside an optgroup", () => {
    const row = buildRow("timestamp_start", "EQUALS:year", "");
    refreshRow(row, COLUMNS);
    expect(optgroupLabels(row, "[data-fc-right]")).toContain("Game");
  });

  it("own columns (source='') render top-level, not in optgroup", () => {
    const row = buildRow("timestamp_start", "EQUALS", "");
    refreshRow(row, COLUMNS);
    const rightSelect = row.querySelector<HTMLSelectElement>("[data-fc-right]")!;
    const topLevelValues = [...rightSelect.children]
      .filter((child) => child.tagName === "OPTION")
      .map((child) => (child as HTMLOptionElement).value);
    // timestamp_end is in the datetime group, same-group as timestamp_start
    expect(topLevelValues).toContain("timestamp_end");
  });

  it("operator change re-filters the right list preserving a still-valid selection", () => {
    const row = buildRow("timestamp_start", "EQUALS", "timestamp_end");
    refreshRow(row, COLUMNS);
    wireComparisonRowListeners(row, COLUMNS);
    // timestamp_end is valid for raw operator (both datetime)
    const rightSelect = row.querySelector<HTMLSelectElement>("[data-fc-right]")!;
    expect(rightSelect.value).toBe("timestamp_end");

    // switch to year space: timestamp_end is still valid (datetime is in year space)
    const operatorSelect = row.querySelector<HTMLSelectElement>("[data-fc-op]")!;
    operatorSelect.value = "EQUALS:year";
    operatorSelect.dispatchEvent(new Event("change", { bubbles: true }));
    expect(optionValues(row, "[data-fc-right]")).toContain("timestamp_end");
    expect(rightSelect.value).toBe("timestamp_end"); // preserved (still valid)
  });

  it("operator change drops the right selection when it becomes invalid", () => {
    const row = buildRow("timestamp_start", "EQUALS:year", "game__year_released");
    refreshRow(row, COLUMNS);
    wireComparisonRowListeners(row, COLUMNS);
    // game__year_released is valid for year space
    const rightSelect = row.querySelector<HTMLSelectElement>("[data-fc-right]")!;
    expect(rightSelect.value).toBe("game__year_released");

    // switch to raw operator: game__year_released is now invalid (different group)
    const operatorSelect = row.querySelector<HTMLSelectElement>("[data-fc-op]")!;
    operatorSelect.value = "EQUALS";
    operatorSelect.dispatchEvent(new Event("change", { bubbles: true }));
    expect(optionValues(row, "[data-fc-right]")).not.toContain("game__year_released");
    // selection is cleared (no longer valid)
    expect(rightSelect.value).toBe("");
  });
});

describe("refreshRow with a number left operand", () => {
  it("offers a By year optgroup (number is in the year space)", () => {
    // number group is in SPACE_GROUPS.year (["date", "datetime", "number"]),
    // so a number left column gets a "By year" optgroup for cross-space comparisons.
    const row = buildRow("game__year_released", "", "");
    refreshRow(row, COLUMNS);
    expect(optgroupLabels(row, "[data-fc-op]")).toEqual(["By year"]);
  });

  it("right list in raw mode only has other number columns", () => {
    const row = buildRow("game__year_released", "EQUALS", "");
    refreshRow(row, COLUMNS);
    const values = optionValues(row, "[data-fc-right]");
    // No other number columns in COLUMNS (it only has timestamp_* as datetime and note as string)
    expect(values).not.toContain("timestamp_start");
    expect(values).not.toContain("note");
  });

  it("right list in year space includes datetime columns", () => {
    const row = buildRow("game__year_released", "EQUALS:year", "");
    refreshRow(row, COLUMNS);
    const values = optionValues(row, "[data-fc-right]");
    // year space: date, datetime, number — so datetime timestamp_* are included
    expect(values).toContain("timestamp_start");
    expect(values).toContain("timestamp_end");
  });
});

describe("refreshRow with no left column selected", () => {
  it("disables operator and right selects", () => {
    const row = buildRow("", "", "");
    refreshRow(row, COLUMNS);
    const operatorSelect = row.querySelector<HTMLSelectElement>("[data-fc-op]")!;
    const rightSelect = row.querySelector<HTMLSelectElement>("[data-fc-right]")!;
    expect(operatorSelect.disabled).toBe(true);
    expect(rightSelect.disabled).toBe(true);
  });
});

describe("readComparisonRow", () => {
  it("emits year granularity from a packed operator", () => {
    const row = buildRow("timestamp_start", "EQUALS:year", "game__year_released");
    refreshRow(row, COLUMNS);
    expect(readComparisonRow(row)).toEqual({
      left: "timestamp_start",
      right: "game__year_released",
      modifier: "EQUALS",
      granularity: "year",
    });
  });

  it("emits date granularity from a packed operator", () => {
    const row = buildRow("timestamp_start", "LESS_THAN:date", "timestamp_end");
    refreshRow(row, COLUMNS);
    expect(readComparisonRow(row)).toEqual({
      left: "timestamp_start",
      right: "timestamp_end",
      modifier: "LESS_THAN",
      granularity: "date",
    });
  });

  it("omits granularity in raw space", () => {
    const row = buildRow("timestamp_start", "LESS_THAN", "timestamp_end");
    refreshRow(row, COLUMNS);
    expect(readComparisonRow(row)).toEqual({
      left: "timestamp_start",
      right: "timestamp_end",
      modifier: "LESS_THAN",
    });
  });

  it("returns null when left is empty", () => {
    const row = buildRow("", "EQUALS", "timestamp_end");
    refreshRow(row, COLUMNS);
    expect(readComparisonRow(row)).toBeNull();
  });

  it("returns null when operator is empty", () => {
    const row = buildRow("timestamp_start", "", "timestamp_end");
    refreshRow(row, COLUMNS);
    expect(readComparisonRow(row)).toBeNull();
  });

  it("returns null when right is empty", () => {
    const row = buildRow("timestamp_start", "EQUALS", "");
    refreshRow(row, COLUMNS);
    expect(readComparisonRow(row)).toBeNull();
  });

  it("returns null when left === right", () => {
    // Can only happen in raw space with same column — refreshRow excludes left, but
    // readComparisonRow guards it anyway.
    const row = document.createElement("div");
    row.setAttribute("data-fc-row", "");
    const leftSelect = document.createElement("select");
    leftSelect.setAttribute("data-fc-left", "");
    leftSelect.innerHTML = '<option value="timestamp_start">ts</option>';
    leftSelect.value = "timestamp_start";
    const operatorSelect = document.createElement("select");
    operatorSelect.setAttribute("data-fc-op", "");
    operatorSelect.innerHTML = '<option value="EQUALS">EQUALS</option>';
    operatorSelect.value = "EQUALS";
    const rightSelect = document.createElement("select");
    rightSelect.setAttribute("data-fc-right", "");
    rightSelect.innerHTML = '<option value="timestamp_start">ts</option>';
    rightSelect.value = "timestamp_start";
    row.appendChild(leftSelect);
    row.appendChild(operatorSelect);
    row.appendChild(rightSelect);
    expect(readComparisonRow(row)).toBeNull();
  });
});
