// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  forgetSelection,
  readSelection,
  storageKeyFor,
  writeSelection,
} from "./selection-storage.js";
import {
  emptySelection,
  markedKeys,
  selectAllMatching,
  toggleKey,
} from "./selection-statement.js";

const FILTER = '{"year":2025}';
const KEY = "list";

beforeEach(() => {
  sessionStorage.clear();
});

describe("storageKeyFor", () => {
  it("names the library, the table and the path", () => {
    expect(storageKeyFor("lib-1:Games", "/tracker/game/list")).toBe(
      "selectable-table:lib-1:Games:/tracker/game/list",
    );
  });

  it("tells two tables of one page apart", () => {
    expect(storageKeyFor("lib-1:Sessions", "/game/1/")).not.toBe(
      storageKeyFor("lib-1:Playthroughs", "/game/1/"),
    );
  });

  it("tells two people at one browser apart", () => {
    expect(storageKeyFor("lib-1:Games", "/list")).not.toBe(
      storageKeyFor("lib-2:Games", "/list"),
    );
  });
});

describe("writeSelection and readSelection", () => {
  it("brings back the keys a person marked", () => {
    writeSelection(KEY, FILTER, toggleKey(toggleKey(emptySelection(), "a"), "b"));
    const restored = readSelection(KEY, FILTER)!;
    expect(restored.mode).toBe("some");
    expect([...markedKeys(restored)].sort()).toEqual(["a", "b"]);
  });

  it("brings back the scope and its exclusions", () => {
    writeSelection(KEY, FILTER, toggleKey(selectAllMatching(), "b"));
    const restored = readSelection(KEY, FILTER)!;
    expect(restored.mode).toBe("all");
    expect([...markedKeys(restored)]).toEqual(["b"]);
  });

  it("brings back a scope with no exclusion", () => {
    writeSelection(KEY, FILTER, selectAllMatching());
    expect(readSelection(KEY, FILTER)!.mode).toBe("all");
  });

  it("answers nothing for another filter: the set is not the same set", () => {
    writeSelection(KEY, FILTER, toggleKey(emptySelection(), "a"));
    expect(readSelection(KEY, '{"year":2024}')).toBeNull();
  });

  it("keeps a value the filter did not match, for a person who goes back", () => {
    writeSelection(KEY, FILTER, toggleKey(emptySelection(), "a"));
    readSelection(KEY, '{"year":2024}');
    expect(readSelection(KEY, FILTER)).not.toBeNull();
  });

  it("answers nothing for another table", () => {
    writeSelection(KEY, FILTER, toggleKey(emptySelection(), "a"));
    expect(readSelection("other", FILTER)).toBeNull();
  });

  it("answers nothing for an empty selection", () => {
    writeSelection(KEY, FILTER, emptySelection());
    expect(readSelection(KEY, FILTER)).toBeNull();
  });

  it("forgets what a person cleared", () => {
    writeSelection(KEY, FILTER, toggleKey(emptySelection(), "a"));
    forgetSelection(KEY);
    expect(readSelection(KEY, FILTER)).toBeNull();
  });
});

describe("a value this page cannot read", () => {
  it("answers nothing for text that is not JSON, and forgets it", () => {
    sessionStorage.setItem(KEY, "{not json");
    expect(readSelection(KEY, FILTER)).toBeNull();
    expect(sessionStorage.getItem(KEY)).toBeNull();
  });

  it("answers nothing for JSON that is not an object", () => {
    sessionStorage.setItem(KEY, '"a string"');
    expect(readSelection(KEY, FILTER)).toBeNull();
    expect(sessionStorage.getItem(KEY)).toBeNull();
  });

  it("answers nothing for another version, and forgets it", () => {
    sessionStorage.setItem(
      KEY,
      JSON.stringify({ version: 99, filter: FILTER, keys: ["a"] }),
    );
    expect(readSelection(KEY, FILTER)).toBeNull();
    expect(sessionStorage.getItem(KEY)).toBeNull();
  });

  it("takes only the strings out of a key list", () => {
    sessionStorage.setItem(
      KEY,
      JSON.stringify({ version: 1, filter: FILTER, keys: ["a", 7, null] }),
    );
    expect([...markedKeys(readSelection(KEY, FILTER)!)]).toEqual(["a"]);
  });

  it("reads a scope beside keys as the scope alone", () => {
    // Nothing writes this pair; a hand-edited value must still land in one
    // of the two shapes the selection admits.
    sessionStorage.setItem(
      KEY,
      JSON.stringify({
        version: 1,
        filter: FILTER,
        all: true,
        keys: ["a"],
        except: ["b"],
      }),
    );
    const restored = readSelection(KEY, FILTER)!;
    expect(restored.mode).toBe("all");
    expect([...markedKeys(restored)]).toEqual(["b"]);
  });
});

describe("storage a page may not touch", () => {
  it("survives a write it is refused", () => {
    const denied = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("denied");
    });
    expect(() =>
      writeSelection(KEY, FILTER, toggleKey(emptySelection(), "a")),
    ).not.toThrow();
    denied.mockRestore();
  });

  it("survives a read it is refused", () => {
    const denied = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("denied");
    });
    expect(readSelection(KEY, FILTER)).toBeNull();
    denied.mockRestore();
  });

  it("survives a removal it is refused", () => {
    const denied = vi
      .spyOn(Storage.prototype, "removeItem")
      .mockImplementation(() => {
        throw new Error("denied");
      });
    expect(() => forgetSelection(KEY)).not.toThrow();
    denied.mockRestore();
  });
});
