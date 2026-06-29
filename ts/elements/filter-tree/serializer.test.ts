import { describe, it, expect } from "vitest";
import { serialize, group } from "./serializer.js";
import type { FilterNode, GroupNode } from "./types.js";

function root(...children: FilterNode[]): GroupNode {
  return { kind: "group", connective: "AND", negate: false, children };
}

describe("serialize", () => {
  it("emits an empty root as {}", () => {
    expect(serialize(root())).toEqual({});
  });

  it("emits a criterion leaf under its connective", () => {
    const node = serialize(
      root({ kind: "criterion", field: "status", criterion: { value: ["f"], modifier: "INCLUDES" }, negate: false }),
    );
    expect(node).toEqual({ AND: [{ status: { value: ["f"], modifier: "INCLUDES" } }] });
  });

  it("wraps a negated leaf in NOT", () => {
    const node = serialize(
      root({ kind: "criterion", field: "name", criterion: { value: "x", modifier: "INCLUDES" }, negate: true }),
    );
    expect(node).toEqual({ AND: [{ NOT: [{ name: { value: "x", modifier: "INCLUDES" } }] }] });
  });

  it("emits a comparison leaf as field_comparisons", () => {
    const node = serialize(
      root({ kind: "comparison", comparison: { left: "a", right: "b", modifier: "LESS_THAN" }, negate: false }),
    );
    expect(node).toEqual({ AND: [{ field_comparisons: [{ left: "a", right: "b", modifier: "LESS_THAN" }] }] });
  });

  it("emits an OR group nested under the AND root", () => {
    const orGroup = group("OR", [
      { kind: "criterion", field: "status", criterion: { value: ["f"], modifier: "INCLUDES" }, negate: false },
      { kind: "criterion", field: "status", criterion: { value: ["p"], modifier: "INCLUDES" }, negate: false },
    ]);
    expect(serialize(root(orGroup))).toEqual({
      AND: [{ OR: [{ status: { value: ["f"], modifier: "INCLUDES" } }, { status: { value: ["p"], modifier: "INCLUDES" } }] }],
    });
  });

  it("merges match onto a relation child group, omitting ANY", () => {
    const relationAny: FilterNode = {
      kind: "relation",
      field: "session_filter",
      match: "ANY",
      child: { kind: "group", connective: "AND", negate: false, children: [
        { kind: "criterion", field: "device", criterion: { value: [1], modifier: "INCLUDES" }, negate: false },
      ] },
      negate: false,
    };
    expect(serialize(root(relationAny))).toEqual({
      AND: [{ session_filter: { AND: [{ device: { value: [1], modifier: "INCLUDES" } }] } }],
    });
  });

  it("keeps an empty relation child (presence test) and emits NONE", () => {
    const relationNone: FilterNode = {
      kind: "relation",
      field: "session_filter",
      match: "NONE",
      child: { kind: "group", connective: "AND", negate: false, children: [] },
      negate: false,
    };
    expect(serialize(root(relationNone))).toEqual({ AND: [{ session_filter: { match: "NONE" } }] });
  });

  it("drops empty children but never a relation", () => {
    const emptyGroup: FilterNode = { kind: "group", connective: "AND", negate: false, children: [] };
    const relationAnyEmpty: FilterNode = {
      kind: "relation",
      field: "session_filter",
      match: "ANY",
      child: { kind: "group", connective: "AND", negate: false, children: [] },
      negate: false,
    };
    expect(serialize(root(emptyGroup, relationAnyEmpty))).toEqual({ AND: [{ session_filter: {} }] });
  });

  it("does not wrap an empty negated group", () => {
    const negatedEmpty: GroupNode = { kind: "group", connective: "AND", negate: true, children: [] };
    expect(serialize(negatedEmpty)).toEqual({});
  });
});
