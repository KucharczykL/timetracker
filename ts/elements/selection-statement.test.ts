import { describe, expect, it } from "vitest";
import {
  checkAllState,
  clearSelection,
  emptySelection,
  rangeKeys,
  selectAllMatching,
  selectionCount,
  setPage,
  statementFor,
  toggleKey,
} from "./selection-statement.js";

const page = ["a", "b", "c", "d"];

describe("toggleKey", () => {
  it("adds a key that was not marked", () => {
    const state = toggleKey(emptySelection(), "a");
    expect([...state.keys]).toEqual(["a"]);
  });

  it("removes a key that was marked", () => {
    const state = toggleKey(toggleKey(emptySelection(), "a"), "a");
    expect([...state.keys]).toEqual([]);
  });

  it("records an exclusion under all matching, keeping the scope", () => {
    const state = toggleKey(selectAllMatching(emptySelection()), "b");
    expect(state.all).toBe(true);
    expect([...state.except]).toEqual(["b"]);
  });

  it("takes an exclusion back", () => {
    const state = toggleKey(
      toggleKey(selectAllMatching(emptySelection()), "b"),
      "b",
    );
    expect(state.all).toBe(true);
    expect([...state.except]).toEqual([]);
  });
});

describe("setPage", () => {
  it("marks every key on the page", () => {
    const state = setPage(emptySelection(), page, true);
    expect([...state.keys].sort()).toEqual(page);
  });

  it("unmarks every key on the page and keeps the others", () => {
    const marked = toggleKey(setPage(emptySelection(), page, true), "z");
    const state = setPage(marked, page, false);
    expect([...state.keys]).toEqual(["z"]);
  });

  it("excludes the whole page under all matching", () => {
    const state = setPage(selectAllMatching(emptySelection()), page, false);
    expect([...state.except].sort()).toEqual(page);
  });
});

describe("rangeKeys", () => {
  it("takes the range from the anchor down, inclusive", () => {
    expect(rangeKeys(page, "b", "d")).toEqual(["b", "c", "d"]);
  });

  it("takes the same range upwards", () => {
    expect(rangeKeys(page, "d", "b")).toEqual(["b", "c", "d"]);
  });

  it("is the one row when anchor and target are the same", () => {
    expect(rangeKeys(page, "c", "c")).toEqual(["c"]);
  });

  it("is the target alone when the anchor left the page", () => {
    expect(rangeKeys(page, "gone", "c")).toEqual(["c"]);
  });
});

describe("checkAllState", () => {
  it("is unchecked with nothing marked", () => {
    expect(checkAllState(emptySelection(), page)).toBe("unchecked");
  });

  it("is indeterminate with some of the page marked", () => {
    expect(checkAllState(toggleKey(emptySelection(), "a"), page)).toBe(
      "indeterminate",
    );
  });

  it("is checked with the whole page marked", () => {
    expect(checkAllState(setPage(emptySelection(), page, true), page)).toBe(
      "checked",
    );
  });

  it("is checked under all matching", () => {
    expect(checkAllState(selectAllMatching(emptySelection()), page)).toBe(
      "checked",
    );
  });

  it("is indeterminate under all matching minus one row", () => {
    const state = toggleKey(selectAllMatching(emptySelection()), "b");
    expect(checkAllState(state, page)).toBe("indeterminate");
  });
});

describe("selectionCount", () => {
  it("counts the marked keys", () => {
    expect(selectionCount(toggleKey(emptySelection(), "a"), 50)).toBe(1);
  });

  it("counts the matching set minus its exclusions", () => {
    const state = toggleKey(selectAllMatching(emptySelection()), "b");
    expect(selectionCount(state, 50)).toBe(49);
  });
});

describe("statementFor", () => {
  it("states the keys, sorted, so one selection has one statement", () => {
    const state = toggleKey(toggleKey(emptySelection(), "b"), "a");
    expect(statementFor(state, "{}", 50)).toEqual({ keys: ["a", "b"] });
  });

  it("states the scope, its filter and its exclusions", () => {
    const state = toggleKey(selectAllMatching(emptySelection()), "b");
    expect(statementFor(state, '{"year":2025}', 50)).toEqual({
      all: true,
      filter: '{"year":2025}',
      count: 50,
      except: ["b"],
    });
  });
});

describe("clearSelection", () => {
  it("drops the scope and every exclusion", () => {
    const state = clearSelection();
    expect(state.all).toBe(false);
    expect([...state.except]).toEqual([]);
    expect([...state.keys]).toEqual([]);
  });
});
