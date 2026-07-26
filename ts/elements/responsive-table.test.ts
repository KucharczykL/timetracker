// @vitest-environment jsdom
import { describe, expect, it } from "vitest";
import {
  ResponsiveTableElement,
  columnCosts,
  computeHiddenColumns,
  hiddenColumnClass,
} from "./responsive-table.js";
// Importing the module defines <responsive-table>.
import "./responsive-table.js";

describe("computeHiddenColumns", () => {
  it("hides nothing when everything fits", () => {
    expect(computeHiddenColumns([100, 100, 100], [1, 1, 1], 300)).toEqual(
      new Set(),
    );
  });

  it("drops the lowest priority first", () => {
    const hidden = computeHiddenColumns([100, 100, 100], [1, 1, 3], 250);
    expect(hidden).toEqual(new Set([1]));
  });

  it("breaks priority ties rightmost-first", () => {
    const hidden = computeHiddenColumns([100, 100, 100, 100], [1, 1, 1, 1], 350);
    expect(hidden).toEqual(new Set([3]));
  });

  it("keeps dropping until the total fits", () => {
    const hidden = computeHiddenColumns(
      [100, 50, 60, 70, 80],
      [1, 1, 2, 2, 3],
      200,
    );
    // Drop order: index 1 (p1), then p2 rightmost-first: index 3, index 2.
    // 360 -> 310 -> 240 -> 180 <= 200.
    expect(hidden).toEqual(new Set([1, 2, 3]));
  });

  it("never drops the first column, even when it alone overflows", () => {
    const hidden = computeHiddenColumns([400, 100], [1, 1], 300);
    expect(hidden).toEqual(new Set([1]));
  });
});

describe("columnCosts", () => {
  const policies = [
    { priority: 1, wrap: false, shrinkable: true },
    { priority: 1, wrap: false, shrinkable: false },
    { priority: 1, wrap: true, shrinkable: false },
  ];

  it("uses natural widths above md", () => {
    expect(columnCosts(policies, [250, 120, 200], true)).toEqual([
      250, 120, 200,
    ]);
  });

  it("substitutes the floor for the shrinkable first column below md", () => {
    // The max-md greed squeezes it below its natural width; the floor is the
    // minimum the fit must preserve for it.
    expect(columnCosts(policies, [250, 120, 200], false)).toEqual([
      160, 120, 200,
    ]);
  });

  it("clamps a wrap column to the cap: it wraps instead of widening", () => {
    expect(columnCosts(policies, [250, 120, 1400], true)).toEqual([
      250, 120, 304,
    ]);
  });

  it("does not floor a shrinkable column that is not first", () => {
    const shrinkableSecond = [
      { priority: 1, wrap: false, shrinkable: false },
      { priority: 1, wrap: false, shrinkable: true },
    ];
    expect(columnCosts(shrinkableSecond, [100, 250], false)).toEqual([
      100, 250,
    ]);
  });
});

function mountTable(headers: string[][]): {
  element: ResponsiveTableElement;
  table: HTMLTableElement;
} {
  const element = document.createElement(
    "responsive-table",
  ) as ResponsiveTableElement;
  const headerCells = headers
    .map(
      ([priority, extra]) =>
        `<th scope="col" data-priority="${priority}"${extra ?? ""}>h</th>`,
    )
    .join("");
  element.innerHTML = `
    <div role="region" tabindex="0">
      <table>
        <thead><tr>${headerCells}</tr></thead>
        <tbody><tr><th scope="row">a</th>${"<td>b</td>".repeat(
          headers.length - 1,
        )}</tr></tbody>
      </table>
    </div>`;
  document.body.appendChild(element);
  const table = element.querySelector("table") as HTMLTableElement;
  return { element, table };
}

describe("<responsive-table> applyDecision", () => {
  it("toggles the table-level drop classes for hidden columns", () => {
    const { element, table } = mountTable([["1"], ["1"], ["3"]]);
    element.applyDecision([100, 100, 100], 250, true);
    expect(table.classList.contains(hiddenColumnClass(1))).toBe(true);
    expect(table.classList.contains(hiddenColumnClass(0))).toBe(false);
    expect(table.classList.contains(hiddenColumnClass(2))).toBe(false);
  });

  it("brings columns back when the region widens", () => {
    const { element, table } = mountTable([["1"], ["1"], ["3"]]);
    element.applyDecision([100, 100, 100], 250, true);
    expect(table.classList.contains(hiddenColumnClass(1))).toBe(true);
    element.applyDecision([100, 100, 100], 400, true);
    expect(table.classList.contains(hiddenColumnClass(1))).toBe(false);
  });

  it("reads the wrap policy from the header cell", () => {
    const { element, table } = mountTable([
      ["1"],
      ["1", " data-wrap"],
      ["3"],
    ]);
    // Raw widths would demand dropping; the wrap clamp (1400 -> 304) fits.
    element.applyDecision([100, 1400, 100], 550, true);
    expect(table.classList.contains(hiddenColumnClass(1))).toBe(false);
  });

  it("reads the shrinkable policy from the header cell below md", () => {
    const { element, table } = mountTable([
      ["1", " data-shrinkable"],
      ["2"],
      ["3"],
    ]);
    // Natural 300 would force a drop at 380; the floor (160) plus the others
    // fits, which is exactly the mobile situation the greed creates.
    element.applyDecision([300, 100, 100], 380, false);
    expect(table.classList.contains(hiddenColumnClass(1))).toBe(false);
    expect(table.classList.contains(hiddenColumnClass(2))).toBe(false);
  });

  it("survives connect in an environment with no layout engine", () => {
    // jsdom reports zero widths everywhere; connectedCallback must not throw
    // and must leave every column visible.
    const { table } = mountTable([["1"], ["1"]]);
    expect(table.classList.contains(hiddenColumnClass(1))).toBe(false);
  });
});
