// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderSessionRow } from "./session-row.js";

const formatSessionTimeRange = vi.hoisted(() => vi.fn());

vi.mock("./date-time-presentation.js", () => ({ formatSessionTimeRange }));

function serverRenderedRow(): HTMLTableRowElement {
  const row = document.createElement("tr");
  row.innerHTML = `
    <th>Example game</th>
    <td>server-rendered time</td>
    <td>server-rendered duration</td>
    <td>PC</td>
    <td>server-rendered created</td>
    <td>
      <session-actions is-open="true">
        <button data-finish>Finish</button>
        <button data-reset>Reset</button>
        <div data-reset-modal>Reset confirmation</div>
        <a data-edit>Edit</a>
      </session-actions>
    </td>
  `;
  return row;
}

function expectFinishedActionCleanup(row: HTMLTableRowElement): void {
  const actions = row.querySelector("session-actions");
  expect(actions).not.toBeNull();
  expect(actions?.getAttribute("is-open")).toBe("false");
  expect(actions?.querySelector("[data-finish]")).toBeNull();
  expect(actions?.querySelector("[data-reset]")).toBeNull();
  expect(actions?.querySelector("[data-reset-modal]")).toBeNull();
  expect(actions?.querySelector("[data-edit]")).not.toBeNull();
}

describe("renderSessionRow", () => {
  beforeEach(() => {
    formatSessionTimeRange.mockReset();
    document.body.replaceChildren();
  });

  it("uses the presentation formatter, calculates duration, and cleans up finished actions", () => {
    formatSessionTimeRange.mockReturnValue("2026-07-02 19:05 — 21:15");
    const oldRow = serverRenderedRow();
    const session = {
      id: 1,
      timestamp_start: "2026-07-02T17:05:00Z",
      timestamp_end: "2026-07-02T19:35:00Z",
      duration_manual_seconds: 1800,
      is_manual: true,
    };

    const newRow = renderSessionRow(session, oldRow);

    expect(newRow).not.toBe(oldRow);
    expect(newRow.children[1]?.textContent).toBe("2026-07-02 19:05 — 21:15");
    expect(newRow.children[2]?.textContent).toBe("3.0*");
    expect(oldRow.children[1]?.textContent).toBe("server-rendered time");
    expect(oldRow.children[2]?.textContent).toBe("server-rendered duration");
    expect(formatSessionTimeRange).toHaveBeenCalledOnce();
    expect(formatSessionTimeRange).toHaveBeenCalledWith(
      "2026-07-02T17:05:00Z",
      "2026-07-02T19:35:00Z",
    );
    expectFinishedActionCleanup(newRow);
  });

  it("keeps server-rendered time when the presentation formatter returns null", () => {
    formatSessionTimeRange.mockReturnValue(null);
    const oldRow = serverRenderedRow();

    const newRow = renderSessionRow(
      {
        id: 1,
        timestamp_start: "2026-07-02T17:05:00Z",
        timestamp_end: "2026-07-02T18:35:00Z",
        duration_manual_seconds: 0,
        is_manual: false,
      },
      oldRow,
    );

    expect(newRow.children[1]?.textContent).toBe("server-rendered time");
    expect(newRow.children[2]?.textContent).toBe("1.5");
    expect(formatSessionTimeRange).toHaveBeenCalledOnce();
    expectFinishedActionCleanup(newRow);
  });

  it("keeps both server-rendered cells for invalid timestamps while cleaning up actions", () => {
    formatSessionTimeRange.mockReturnValue(null);
    const oldRow = serverRenderedRow();
    let newRow!: HTMLTableRowElement;

    expect(() => {
      newRow = renderSessionRow(
        {
          id: 1,
          timestamp_start: "not an ISO timestamp",
          timestamp_end: "2026-07-02T18:35:00Z",
          duration_manual_seconds: 0,
          is_manual: false,
        },
        oldRow,
      );
    }).not.toThrow();

    expect(newRow.children[1]?.textContent).toBe("server-rendered time");
    expect(newRow.children[2]?.textContent).toBe("server-rendered duration");
    expect(formatSessionTimeRange).toHaveBeenCalledOnce();
    expectFinishedActionCleanup(newRow);
  });
});
