import { describe, it, expect } from "vitest";
import {
  MAX_FILTER_DEPTH,
  MAX_FILTER_BREADTH,
  MAX_FIELD_COMPARISONS,
  RESERVED_KEYS,
  FilterTreeError,
  type GroupNode,
} from "./types.js";

describe("types module", () => {
  it("exposes backend-matching caps", () => {
    expect(MAX_FILTER_DEPTH).toBe(10);
    expect(MAX_FILTER_BREADTH).toBe(100);
    expect(MAX_FIELD_COMPARISONS).toBe(100);
  });

  it("reserves the structural keys", () => {
    for (const key of ["AND", "OR", "NOT", "match", "field_comparisons"]) {
      expect(RESERVED_KEYS.has(key)).toBe(true);
    }
    expect(RESERVED_KEYS.has("status")).toBe(false);
  });

  it("has a dedicated error type", () => {
    expect(new FilterTreeError("x")).toBeInstanceOf(Error);
  });

  it("models an AND root group", () => {
    const root: GroupNode = { kind: "group", connective: "AND", negate: false, children: [] };
    expect(root.kind).toBe("group");
  });
});
