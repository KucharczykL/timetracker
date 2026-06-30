import { describe, it, expect } from "vitest";
import { group } from "./serializer.js";
import type { CriterionLeaf, FilterNode, GroupNode } from "./types.js";
import type { FilterFieldMeta } from "./types.js";
import {
  SOFT_DEPTH_CAP,
  canAddGroup,
  canAddRelation,
  canUnwrap,
  canWrap,
  criterionForField,
  deepestGroupDepth,
  duplicateAt,
  emptyCriterion,
  emptyGroup,
  emptyRelation,
  emptyRoot,
  groupDepthAt,
  insertChild,
  isCriterionComplete,
  move,
  nodeAt,
  parseFieldMeta,
  pruneIncomplete,
  removeAt,
  setConnective,
  setLeafCriterion,
  setLeafField,
  setMatch,
  toggleConnective,
  toggleNegate,
  unwrapGroup,
  wrapInGroup,
} from "./operations.js";

function fieldMeta(overrides: Partial<FilterFieldMeta> = {}): FilterFieldMeta {
  return {
    name: "status",
    label: "Status",
    kind: "set",
    nullable: false,
    choices: [],
    modifiers: ["INCLUDES", "EXCLUDES"],
    relations: [],
    ...overrides,
  };
}

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

describe("add-criterion field picker contract (#191)", () => {
  describe("parseFieldMeta", () => {
    it("parses a well-formed data-meta blob", () => {
      const meta = fieldMeta();
      expect(parseFieldMeta(JSON.stringify(meta))).toEqual(meta);
    });

    it("returns null on empty or malformed JSON", () => {
      expect(parseFieldMeta("")).toBeNull();
      expect(parseFieldMeta("{not json")).toBeNull();
    });
  });

  describe("criterionForField", () => {
    it("resets to the field's first valid modifier and drops the value", () => {
      const leaf = criterionForField(
        fieldMeta({ name: "name", kind: "string", modifiers: ["EQUALS", "INCLUDES"] }),
      );
      expect(leaf).toEqual({
        kind: "criterion",
        field: "name",
        criterion: { modifier: "EQUALS" },
        negate: false,
      });
      expect("value" in leaf.criterion).toBe(false); // no silent coercion
    });

    it("picks the first modifier per kind", () => {
      expect(criterionForField(fieldMeta({ kind: "set" })).criterion).toEqual({
        modifier: "INCLUDES",
      });
      expect(
        criterionForField(fieldMeta({ kind: "number", modifiers: ["EQUALS", "GREATER_THAN"] }))
          .criterion,
      ).toEqual({ modifier: "EQUALS" });
    });

    it("yields an empty payload when the field has no modifiers", () => {
      expect(criterionForField(fieldMeta({ modifiers: [] })).criterion).toEqual({});
    });
  });

  describe("isCriterionComplete", () => {
    it("is incomplete with no field, no modifier, or empty value", () => {
      expect(isCriterionComplete(emptyCriterion())).toBe(false);
      expect(
        isCriterionComplete(criterionForField(fieldMeta({ name: "name", kind: "string" }))),
      ).toBe(false); // modifier set but value still empty
      expect(
        isCriterionComplete({
          kind: "criterion",
          field: "name",
          criterion: { modifier: "EQUALS", value: "" },
          negate: false,
        }),
      ).toBe(false);
    });

    it("is complete once a non-empty value is present", () => {
      expect(
        isCriterionComplete({
          kind: "criterion",
          field: "name",
          criterion: { modifier: "EQUALS", value: "Hades" },
          negate: false,
        }),
      ).toBe(true);
    });

    it("treats a presence modifier as complete without a value", () => {
      expect(
        isCriterionComplete({
          kind: "criterion",
          field: "year_released",
          criterion: { modifier: "IS_NULL" },
          negate: false,
        }),
      ).toBe(true);
    });

    it("is incomplete for an empty multi-value list", () => {
      expect(
        isCriterionComplete({
          kind: "criterion",
          field: "platform",
          criterion: { modifier: "INCLUDES", value: [] },
          negate: false,
        }),
      ).toBe(false);
    });

    it("requires both bounds for a range modifier (#192)", () => {
      const halfBetween: CriterionLeaf = {
        kind: "criterion",
        field: "year_released",
        criterion: { modifier: "BETWEEN", value: 1990 },
        negate: false,
      };
      expect(isCriterionComplete(halfBetween)).toBe(false);
      expect(
        isCriterionComplete({ ...halfBetween, criterion: { modifier: "BETWEEN", value: 1990, value2: 2000 } }),
      ).toBe(true);
    });
  });
});

describe("leaf payload edits (#192)", () => {
  it("setLeafField replaces the leaf with a fresh reset leaf, preserving negate", () => {
    const tree = group("AND", [
      { kind: "criterion", field: "name", criterion: { modifier: "EQUALS", value: "x" }, negate: true },
    ]);
    const next = setLeafField(tree, [0], fieldMeta({ name: "status", kind: "set" }));
    expect(nodeAt(next, [0])).toEqual({
      kind: "criterion",
      field: "status",
      criterion: { modifier: "INCLUDES" }, // value dropped, modifier reset
      negate: true, // preserved
    });
  });

  it("setLeafCriterion swaps the opaque payload verbatim", () => {
    const tree = group("AND", [emptyCriterion()]);
    const payload = { modifier: "INCLUDES", value: [{ id: "1", label: "PC" }] };
    const next = setLeafCriterion(tree, [0], payload);
    expect((nodeAt(next, [0]) as CriterionLeaf).criterion).toEqual(payload);
  });

  it("setLeafField / setLeafCriterion throw on a non-criterion node", () => {
    const tree = group("AND", [emptyGroup()]);
    expect(() => setLeafField(tree, [0], fieldMeta())).toThrow();
    expect(() => setLeafCriterion(tree, [0], {})).toThrow();
  });
});

describe("pruneIncomplete (#192)", () => {
  const complete = (field: string): CriterionLeaf => ({
    kind: "criterion",
    field,
    criterion: { modifier: "EQUALS", value: "v" },
    negate: false,
  });

  it("drops incomplete criterion leaves, keeps complete ones", () => {
    const tree = group("AND", [complete("name"), emptyCriterion()]);
    expect(pruneIncomplete(tree)).toEqual(group("AND", [complete("name")]));
  });

  it("collapses a non-root group emptied by pruning, but keeps an empty root", () => {
    const inner = group("OR", [emptyCriterion()]);
    const tree = group("AND", [complete("name"), inner]);
    expect(pruneIncomplete(tree)).toEqual(group("AND", [complete("name")]));
    expect(pruneIncomplete(group("AND", [emptyCriterion()]))).toEqual(group("AND", []));
  });

  it("keeps a relation even if its child group empties (presence test)", () => {
    const tree = group("AND", [relation("session_filter", group("AND", [emptyCriterion()]))]);
    expect(pruneIncomplete(tree)).toEqual(
      group("AND", [relation("session_filter", group("AND", []))]),
    );
  });
});
