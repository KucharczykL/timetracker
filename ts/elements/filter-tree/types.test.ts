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

  it("FilterTreeError carries a discriminant code", () => {
    const error = new FilterTreeError("nesting too deep", "DEPTH_EXCEEDED");
    expect(error).toBeInstanceOf(Error);
    expect(error.code).toBe("DEPTH_EXCEEDED");
    expect(error.name).toBe("FilterTreeError");
    expect(error.message).toBe("nesting too deep");
  });

  it("GroupNode children are mutable and connective is assignable", () => {
    const node: GroupNode = { kind: "group", id: "g1", connective: "AND", negate: false, children: [] };
    const inner: GroupNode = { kind: "group", id: "g2", connective: "OR", negate: false, children: [] };
    node.children.push(inner);
    expect(node.children).toHaveLength(1);
    expect((node.children[0] as GroupNode).connective).toBe("OR");
  });
});
