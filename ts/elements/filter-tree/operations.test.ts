import { describe, it, expect } from "vitest";
import { group } from "./serializer.js";
import type { FilterNode, GroupNode } from "./types.js";
import {
  SOFT_DEPTH_CAP,
  canAddGroup,
  canAddRelation,
  canUnwrap,
  canWrap,
  deepestGroupDepth,
  duplicateAt,
  emptyCriterion,
  emptyGroup,
  emptyRelation,
  emptyRoot,
  groupDepthAt,
  insertChild,
  move,
  nodeAt,
  removeAt,
  setConnective,
  setMatch,
  toggleNegate,
  unwrapGroup,
  wrapInGroup,
} from "./operations.js";

function criterion(field: string): FilterNode {
  return { kind: "criterion", field, criterion: { value: field, modifier: "INCLUDES" }, negate: false };
}

function relation(field: string, child: GroupNode): FilterNode {
  return { kind: "relation", field, match: "ANY", child, negate: false };
}

describe("factories", () => {
  it("emptyRoot is an AND group with one empty criterion", () => {
    expect(emptyRoot()).toEqual(group("AND", [emptyCriterion()]));
  });

  it("emptyCriterion has empty field and payload", () => {
    expect(emptyCriterion()).toEqual({ kind: "criterion", field: "", criterion: {}, negate: false });
  });

  it("emptyRelation is ANY over an empty child group", () => {
    expect(emptyRelation()).toEqual({
      kind: "relation",
      field: "",
      match: "ANY",
      child: group("AND", []),
      negate: false,
    });
  });
});

describe("nodeAt", () => {
  const tree = group("AND", [criterion("a"), group("OR", [criterion("b"), criterion("c")])]);

  it("returns the root at the empty path", () => {
    expect(nodeAt(tree, [])).toBe(tree);
  });

  it("descends through group children", () => {
    expect(nodeAt(tree, [1, 0])).toEqual(criterion("b"));
  });

  it("throws on an out-of-range index", () => {
    expect(() => nodeAt(tree, [5])).toThrow();
  });

  it("throws when descending into a leaf", () => {
    expect(() => nodeAt(tree, [0, 0])).toThrow();
  });
});

describe("insertChild / removeAt", () => {
  it("appends a child by default", () => {
    const tree = group("AND", [criterion("a")]);
    expect(insertChild(tree, [], criterion("b"))).toEqual(group("AND", [criterion("a"), criterion("b")]));
  });

  it("inserts at an explicit index", () => {
    const tree = group("AND", [criterion("a"), criterion("c")]);
    expect(insertChild(tree, [], criterion("b"), 1)).toEqual(
      group("AND", [criterion("a"), criterion("b"), criterion("c")]),
    );
  });

  it("inserts into a nested group", () => {
    const tree = group("AND", [group("OR", [criterion("a")])]);
    expect(insertChild(tree, [0], criterion("b"))).toEqual(
      group("AND", [group("OR", [criterion("a"), criterion("b")])]),
    );
  });

  it("removes the addressed child", () => {
    const tree = group("AND", [criterion("a"), criterion("b"), criterion("c")]);
    expect(removeAt(tree, [1])).toEqual(group("AND", [criterion("a"), criterion("c")]));
  });

  it("does not mutate the input tree", () => {
    const tree = group("AND", [criterion("a")]);
    const snapshot = structuredClone(tree);
    insertChild(tree, [], criterion("b"));
    removeAt(group("AND", [criterion("a"), criterion("b")]), [0]);
    expect(tree).toEqual(snapshot);
  });
});

describe("duplicateAt", () => {
  it("inserts a deep clone immediately after the original", () => {
    const tree = group("AND", [criterion("a"), criterion("b")]);
    expect(duplicateAt(tree, [0])).toEqual(group("AND", [criterion("a"), criterion("a"), criterion("b")]));
  });

  it("clones deeply (mutating the copy does not touch the original)", () => {
    const tree = group("AND", [group("OR", [criterion("a")])]);
    const result = duplicateAt(tree, [0]);
    const clone = result.children[1];
    if (clone.kind !== "group") throw new Error("expected a group clone");
    expect(clone).toEqual(tree.children[0]);
    expect(clone).not.toBe(tree.children[0]);
  });
});

describe("move", () => {
  const tree = group("AND", [criterion("a"), criterion("b"), criterion("c")]);

  it("moves a node earlier", () => {
    expect(move(tree, [1], -1)).toEqual(group("AND", [criterion("b"), criterion("a"), criterion("c")]));
  });

  it("moves a node later", () => {
    expect(move(tree, [1], 1)).toEqual(group("AND", [criterion("a"), criterion("c"), criterion("b")]));
  });

  it("is a no-op past the first slot", () => {
    expect(move(tree, [0], -1)).toEqual(tree);
  });

  it("is a no-op past the last slot", () => {
    expect(move(tree, [2], 1)).toEqual(tree);
  });
});

describe("setConnective / setMatch / toggleNegate", () => {
  it("changes a group's connective in place", () => {
    const tree = group("AND", [criterion("a")]);
    expect(setConnective(tree, [], "OR")).toEqual(group("OR", [criterion("a")]));
  });

  it("sets a relation's quantifier", () => {
    const tree = group("AND", [relation("sessions", group("AND", []))]);
    const result = setMatch(tree, [0], "NONE");
    expect(nodeAt(result, [0])).toMatchObject({ kind: "relation", match: "NONE" });
  });

  it("toggles a node's negate flag", () => {
    const tree = group("AND", [criterion("a")]);
    expect(toggleNegate(tree, [0])).toEqual(group("AND", [{ ...criterion("a"), negate: true }]));
  });

  it("cancels under double negation", () => {
    const tree = group("AND", [criterion("a")]);
    expect(toggleNegate(toggleNegate(tree, [0]), [0])).toEqual(tree);
  });

  it("negates a group", () => {
    const tree = group("AND", [group("OR", [criterion("a")])]);
    expect(nodeAt(toggleNegate(tree, [0]), [0])).toMatchObject({ kind: "group", negate: true });
  });
});

describe("wrapInGroup", () => {
  it("wraps a node in a group defaulting to the parent's connective", () => {
    const tree = group("OR", [criterion("a"), criterion("b")]);
    expect(wrapInGroup(tree, [0])).toEqual(group("OR", [group("OR", [criterion("a")]), criterion("b")]));
  });

  it("inherits an AND parent's connective", () => {
    const tree = group("AND", [criterion("a")]);
    expect(wrapInGroup(tree, [0])).toEqual(group("AND", [group("AND", [criterion("a")])]));
  });

  it("can wrap a nested group", () => {
    const tree = group("AND", [group("OR", [criterion("a")])]);
    expect(wrapInGroup(tree, [0])).toEqual(group("AND", [group("AND", [group("OR", [criterion("a")])])]));
  });
});

describe("unwrapGroup", () => {
  it("splices a group's children into the parent at its slot", () => {
    const tree = group("AND", [criterion("a"), group("OR", [criterion("b"), criterion("c")]), criterion("d")]);
    expect(unwrapGroup(tree, [1])).toEqual(
      group("AND", [criterion("a"), criterion("b"), criterion("c"), criterion("d")]),
    );
  });

  it("drops the dissolved group (connective and negate are lost)", () => {
    const tree = group("AND", [{ ...emptyGroup("OR"), negate: true, children: [criterion("b")] }]);
    expect(unwrapGroup(tree, [0])).toEqual(group("AND", [criterion("b")]));
  });

  it("throws on a non-group node", () => {
    const tree = group("AND", [criterion("a")]);
    expect(() => unwrapGroup(tree, [0])).toThrow();
  });
});

describe("depth", () => {
  it("reports a group's depth as its path length", () => {
    const tree = group("AND", [group("OR", [group("AND", [])])]);
    expect(groupDepthAt(tree, [])).toBe(0);
    expect(groupDepthAt(tree, [0])).toBe(1);
    expect(groupDepthAt(tree, [0, 0])).toBe(2);
  });

  it("counts a relation's child group as one level deeper", () => {
    const tree = group("AND", [relation("sessions", group("AND", [criterion("a")]))]);
    // root(0) → relation child group(1). The relation itself is not a group level.
    expect(deepestGroupDepth(tree, 0)).toBe(1);
  });

  it("counts nested groups", () => {
    const tree = group("AND", [criterion("a"), group("OR", [group("AND", [criterion("b")])])]);
    expect(deepestGroupDepth(tree, 0)).toBe(2);
  });

  it("a leaf-only group adds no depth", () => {
    expect(deepestGroupDepth(group("AND", [criterion("a"), criterion("b")]), 0)).toBe(0);
  });
});

describe("soft cap", () => {
  // Build a left-spine of nested groups to a given depth.
  function spine(depth: number): GroupNode {
    let node = emptyGroup("AND");
    for (let i = 0; i < depth; i++) node = group("AND", [node]);
    return node;
  }

  it("allows adding a group below the cap", () => {
    expect(canAddGroup(spine(4), [0, 0, 0, 0])).toBe(true); // depth-4 group → child depth 5
  });

  it("disallows adding a group at the cap", () => {
    const tree = spine(5);
    expect(groupDepthAt(tree, [0, 0, 0, 0, 0])).toBe(SOFT_DEPTH_CAP);
    expect(canAddGroup(tree, [0, 0, 0, 0, 0])).toBe(false); // depth-5 group → child depth 6
  });

  it("gates relations the same way as groups", () => {
    expect(canAddRelation(spine(5), [0, 0, 0, 0, 0])).toBe(false);
    expect(canAddRelation(spine(4), [0, 0, 0, 0])).toBe(true);
  });

  it("allows wrapping a leaf while the wrapper stays within the cap", () => {
    const tree = group("AND", [criterion("a")]);
    expect(canWrap(tree, [0])).toBe(true);
  });

  it("disallows wrapping when it would push the subtree past the cap", () => {
    // The deepest group of spine(5) is at depth 5; wrapping it lands the wrapper
    // at depth 5 and the group itself at depth 6 — past the cap.
    const tree = spine(5);
    expect(groupDepthAt(tree, [0, 0, 0, 0, 0])).toBe(SOFT_DEPTH_CAP);
    expect(canWrap(tree, [0, 0, 0, 0, 0])).toBe(false);
  });

  it("never allows wrapping the root", () => {
    expect(canWrap(emptyRoot(), [])).toBe(false);
  });

  it("allows unwrapping a non-root group only", () => {
    const tree = group("AND", [group("OR", [criterion("a")]), criterion("b")]);
    expect(canUnwrap(tree, [0])).toBe(true);
    expect(canUnwrap(tree, [1])).toBe(false); // a leaf
    expect(canUnwrap(tree, [])).toBe(false); // the root
  });
});
