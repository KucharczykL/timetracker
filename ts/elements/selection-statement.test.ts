import { describe, expect, it } from "vitest";
import {
  checkAllState,
  emptySelection,
  forgetKeys,
  isMarked,
  markedKeys,
  rangeKeys,
  selectAllMatching,
  selectionCount,
  setPage,
  statementFor,
  toggleKey,
} from "./selection-statement.js";

const page = ["a", "b", "c", "d"];

function marks(state: ReturnType<typeof emptySelection>): string[] {
  return [...markedKeys(state)].sort();
}

describe("toggleKey", () => {
  it("adds a key that was not marked", () => {
    expect(marks(toggleKey(emptySelection(), "a"))).toEqual(["a"]);
  });

  it("removes a key that was marked", () => {
    expect(marks(toggleKey(toggleKey(emptySelection(), "a"), "a"))).toEqual([]);
  });

  it("records an exclusion under all matching, keeping the scope", () => {
    const state = toggleKey(selectAllMatching(), "b");
    expect(state.mode).toBe("all");
    expect(marks(state)).toEqual(["b"]);
    expect(isMarked(state, "b")).toBe(false);
    expect(isMarked(state, "a")).toBe(true);
  });

  it("takes an exclusion back", () => {
    const state = toggleKey(toggleKey(selectAllMatching(), "b"), "b");
    expect(state.mode).toBe("all");
    expect(marks(state)).toEqual([]);
  });
});

describe("setPage", () => {
  it("marks every key on the page", () => {
    expect(marks(setPage(emptySelection(), page, true))).toEqual(page);
  });

  it("unmarks every key on the page and keeps the others", () => {
    const marked = toggleKey(setPage(emptySelection(), page, true), "z");
    expect(marks(setPage(marked, page, false))).toEqual(["z"]);
  });

  it("excludes the whole page under all matching", () => {
    expect(marks(setPage(selectAllMatching(), page, false))).toEqual(page);
  });

  it("takes the exclusions back when the page is marked again", () => {
    const excluded = setPage(selectAllMatching(), page, false);
    expect(marks(setPage(excluded, page, true))).toEqual([]);
  });
});

describe("forgetKeys", () => {
  it("drops a key the table no longer holds", () => {
    const state = setPage(emptySelection(), page, true);
    expect(marks(forgetKeys(state, ["b"]))).toEqual(["a", "c", "d"]);
  });

  it("keeps an exclusion, because the row may be restored", () => {
    const state = toggleKey(selectAllMatching(), "b");
    expect(marks(forgetKeys(state, ["b"]))).toEqual(["b"]);
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
    expect(checkAllState(selectAllMatching(), page)).toBe("checked");
  });

  it("is indeterminate under all matching minus one row", () => {
    expect(checkAllState(toggleKey(selectAllMatching(), "b"), page)).toBe(
      "indeterminate",
    );
  });
});

describe("selectionCount", () => {
  it("counts the marked keys", () => {
    expect(selectionCount(toggleKey(emptySelection(), "a"), 50)).toBe(1);
  });

  it("counts the matching set minus its exclusions", () => {
    expect(selectionCount(toggleKey(selectAllMatching(), "b"), 50)).toBe(49);
  });

  it("counts nothing where the page states no count", () => {
    expect(selectionCount(selectAllMatching(), Number.NaN)).toBe(0);
  });
});

describe("statementFor", () => {
  it("states the keys, sorted, so one selection has one statement", () => {
    const state = toggleKey(toggleKey(emptySelection(), "b"), "a");
    expect(statementFor(state, "{}", 50)).toEqual({
      mode: "some",
      keys: ["a", "b"],
    });
  });

  it("states the scope, its filter and its exclusions", () => {
    const state = toggleKey(selectAllMatching(), "b");
    expect(statementFor(state, '{"year":2025}', 50)).toEqual({
      mode: "all",
      filter: '{"year":2025}',
      count: 50,
      except: ["b"],
    });
  });
});

describe("emptySelection", () => {
  it("holds no mark and names no scope", () => {
    const state = emptySelection();
    expect(state.mode).toBe("some");
    expect(marks(state)).toEqual([]);
  });
});
