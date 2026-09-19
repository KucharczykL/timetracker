// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  forgetSelection,
  readSelection,
  storageKeyFor,
  writeSelection,
} from "./selection-storage.js";
import { emptySelection, selectAllMatching, toggleKey } from "./selection-statement.js";

const FILTER = '{"year":2025}';

beforeEach(() => {
  sessionStorage.clear();
});

describe("storageKeyFor", () => {
  it("is the list's own path, so its pages share one selection", () => {
    expect(storageKeyFor("/tracker/game/list")).toBe(
      "selectable-table:/tracker/game/list",
    );
  });
});

describe("writeSelection and readSelection", () => {
  it("brings back the keys a person marked", () => {
    const state = toggleKey(toggleKey(emptySelection(), "a"), "b");
    writeSelection("list", FILTER, state);
    const restored = readSelection("list", FILTER);
    expect([...restored!.keys].sort()).toEqual(["a", "b"]);
    expect(restored!.all).toBe(false);
  });

  it("brings back the scope and its exclusions", () => {
    const state = toggleKey(selectAllMatching(emptySelection()), "b");
    writeSelection("list", FILTER, state);
    const restored = readSelection("list", FILTER);
    expect(restored!.all).toBe(true);
    expect([...restored!.except]).toEqual(["b"]);
  });

  it("answers nothing for another filter: the set is not the same set", () => {
    writeSelection("list", FILTER, toggleKey(emptySelection(), "a"));
    expect(readSelection("list", '{"year":2024}')).toBeNull();
  });

  it("answers nothing for another list", () => {
    writeSelection("list", FILTER, toggleKey(emptySelection(), "a"));
    expect(readSelection("other", FILTER)).toBeNull();
  });

  it("answers nothing for an empty selection", () => {
    writeSelection("list", FILTER, emptySelection());
    expect(readSelection("list", FILTER)).toBeNull();
  });

  it("forgets what a person cleared", () => {
    writeSelection("list", FILTER, toggleKey(emptySelection(), "a"));
    forgetSelection("list");
    expect(readSelection("list", FILTER)).toBeNull();
  });

  it("answers nothing for a value it cannot read", () => {
    sessionStorage.setItem("selectable-table:list", "{not json");
    expect(readSelection("list", FILTER)).toBeNull();
  });

  it("survives storage it may not touch", () => {
    const denied = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("denied");
    });
    expect(() =>
      writeSelection("list", FILTER, toggleKey(emptySelection(), "a")),
    ).not.toThrow();
    denied.mockRestore();
  });
});
