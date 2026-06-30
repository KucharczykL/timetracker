import { describe, it, expect } from "vitest";
import { group } from "./serializer.js";
import type { CriterionLeaf, FilterNode, GroupNode } from "./types.js";
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
  toggleConnective,
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
    const tree = group("AND", [criterion("a"), criterion("b")]);
    const snapshot = structuredClone(tree);
    insertChild(tree, [], criterion("c"));
    removeAt(tree, [0]);
    expect(tree).toEqual(snapshot);
  });

  it("removing the last child of root yields an empty group", () => {
    expect(removeAt(group("AND", [criterion("a")]), [0])).toEqual(group("AND", []));
  });

  it("removing the last child of a nested group removes that group", () => {
    const tree = group("AND", [criterion("a"), group("OR", [criterion("b")])]);
    expect(removeAt(tree, [1, 0])).toEqual(group("AND", [criterion("a")]));
  });

  it("cascades through multiple ancestors that empty as a result", () => {
    const tree = group("AND", [criterion("a"), group("OR", [group("AND", [criterion("b")])])]);
    // Removing the only leaf empties its group, which empties its parent group.
    expect(removeAt(tree, [1, 0, 0])).toEqual(group("AND", [criterion("a")]));
  });

  it("stops the cascade at the root, leaving it empty", () => {
    const tree = group("AND", [group("OR", [criterion("a")])]);
    expect(removeAt(tree, [0, 0])).toEqual(group("AND", []));
  });

  it("prunes only emptied groups, stopping at a non-empty ancestor", () => {
    const tree = group("AND", [group("OR", [group("AND", [criterion("a")]), criterion("keep")])]);
    // Removing 'a' empties its AND, which is pruned; the OR survives (has 'keep'),
    // so the cascade stops there — no spurious sibling removal.
    expect(removeAt(tree, [0, 0, 0])).toEqual(group("AND", [group("OR", [criterion("keep")])]));
  });

  it("does not descend or prune a relation's (possibly empty) child group", () => {
    // A relation is a terminal slot; removeAt never walks into its child group, so
    // an empty relation child (the ANY presence test) is never treated as prunable.
    const tree = group("OR", [criterion("a"), relation("sessions", group("AND", []))]);
    expect(removeAt(tree, [0])).toEqual(group("OR", [relation("sessions", group("AND", []))]));
  });

  it("does not mutate the input tree during a cascade", () => {
    const tree = group("AND", [criterion("a"), group("OR", [group("AND", [criterion("b")])])]);
    const snapshot = structuredClone(tree);
    removeAt(tree, [1, 0, 0]); // full multi-level cascade
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
    if (clone.kind !== "group" || clone.children[0].kind !== "criterion") {
      throw new Error("expected a nested group clone");
    }
    (clone.children[0] as CriterionLeaf).field = "MUTATED";
    const original = tree.children[0];
    if (original.kind !== "group") throw new Error("expected a group");
    expect((original.children[0] as CriterionLeaf).field).toBe("a"); // untouched
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

  it("returns the same root reference past the first slot", () => {
    expect(move(tree, [0], -1)).toBe(tree);
  });

  it("returns the same root reference past the last slot", () => {
    expect(move(tree, [2], 1)).toBe(tree);
  });

  it("reorders within a nested group", () => {
    const nested = group("AND", [group("OR", [criterion("a"), criterion("b")])]);
    expect(move(nested, [0, 0], 1)).toEqual(group("AND", [group("OR", [criterion("b"), criterion("a")])]));
  });
});

describe("error branches", () => {
  it("setConnective throws on a non-group node", () => {
    expect(() => setConnective(group("AND", [criterion("a")]), [0], "OR")).toThrow();
  });

  it("toggleConnective throws on a non-group node", () => {
    expect(() => toggleConnective(group("AND", [criterion("a")]), [0])).toThrow();
  });

  it("setMatch throws on a non-relation node", () => {
    expect(() => setMatch(group("AND", [criterion("a")]), [0], "NONE")).toThrow();
  });

  it("wrapInGroup and unwrapGroup throw at the root path", () => {
    expect(() => wrapInGroup(emptyRoot(), [])).toThrow();
    expect(() => unwrapGroup(emptyRoot(), [])).toThrow();
  });

  it("toggleNegate works on a relation node", () => {
    const tree = group("AND", [relation("sessions", group("AND", []))]);
    expect(nodeAt(toggleNegate(tree, [0]), [0])).toMatchObject({ kind: "relation", negate: true });
  });
});

describe("setConnective / setMatch / toggleNegate", () => {
  it("changes a group's connective in place", () => {
    const tree = group("AND", [criterion("a")]);
    expect(setConnective(tree, [], "OR")).toEqual(group("OR", [criterion("a")]));
  });

  it("flips a group's connective AND->OR and back", () => {
    const tree = group("AND", [criterion("a")]);
    expect(toggleConnective(tree, [])).toEqual(group("OR", [criterion("a")]));
    expect(toggleConnective(toggleConnective(tree, []), [])).toEqual(tree);
  });

  it("flips a nested group's connective by path", () => {
    const tree = group("AND", [group("OR", [criterion("a")])]);
    expect(nodeAt(toggleConnective(tree, [0]), [0])).toMatchObject({ kind: "group", connective: "AND" });
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

  it("recurses through a relation's nested child groups", () => {
    // root(0) → relation child group(1) → nested OR group(2).
    const tree = group("AND", [relation("sessions", group("AND", [group("OR", [criterion("a")])]))]);
    expect(deepestGroupDepth(tree, 0)).toBe(2);
  });

  it("canWrap accounts for a relation's child group depth", () => {
    expect(canWrap(group("AND", [relation("sessions", group("AND", []))]), [0])).toBe(true);
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
