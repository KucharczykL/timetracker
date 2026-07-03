import { describe, it, expect } from "vitest";
import { serialize, group } from "./serializer.js";
import { deserialize } from "./serializer.js";
import type { FilterNode, GroupNode, ModelMeta } from "./types.js";
import type { MetadataRegistry } from "./types.js";
import { FilterTreeError } from "./types.js";

function root(...children: FilterNode[]): GroupNode {
  return { kind: "group", id: "g", connective: "AND", negate: false, children };
}

describe("serialize", () => {
  it("emits an empty root as {}", () => {
    expect(serialize(root())).toEqual({});
  });

  it("emits a criterion leaf under its connective", () => {
    const node = serialize(
      root({ kind: "criterion", id: "c", field: "status", criterion: { value: ["f"], modifier: "INCLUDES" }, negate: false }),
    );
    expect(node).toEqual({ AND: [{ status: { value: ["f"], modifier: "INCLUDES" } }] });
  });

  it("wraps a negated leaf in NOT", () => {
    const node = serialize(
      root({ kind: "criterion", id: "c", field: "name", criterion: { value: "x", modifier: "INCLUDES" }, negate: true }),
    );
    expect(node).toEqual({ AND: [{ NOT: [{ name: { value: "x", modifier: "INCLUDES" } }] }] });
  });

  it("emits a comparison leaf as field_comparisons", () => {
    const node = serialize(
      root({ kind: "comparison", id: "c", comparison: { left: "a", right: "b", modifier: "LESS_THAN" }, negate: false }),
    );
    expect(node).toEqual({ AND: [{ field_comparisons: [{ left: "a", right: "b", modifier: "LESS_THAN" }] }] });
  });

  it("emits an OR group nested under the AND root", () => {
    const orGroup = group("OR", [
      { kind: "criterion", id: "c", field: "status", criterion: { value: ["f"], modifier: "INCLUDES" }, negate: false },
      { kind: "criterion", id: "c", field: "status", criterion: { value: ["p"], modifier: "INCLUDES" }, negate: false },
    ]);
    expect(serialize(root(orGroup))).toEqual({
      AND: [{ OR: [{ status: { value: ["f"], modifier: "INCLUDES" } }, { status: { value: ["p"], modifier: "INCLUDES" } }] }],
    });
  });

  it("merges match onto a relation child group, omitting ANY", () => {
    const relationAny: FilterNode = {
      kind: "relation",
      id: "r",
      field: "session_filter",
      match: "ANY",
      child: { kind: "group", id: "g", connective: "AND", negate: false, children: [
        { kind: "criterion", id: "c", field: "device", criterion: { value: [1], modifier: "INCLUDES" }, negate: false },
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
      id: "r",
      field: "session_filter",
      match: "NONE",
      child: { kind: "group", id: "g", connective: "AND", negate: false, children: [] },
      negate: false,
    };
    expect(serialize(root(relationNone))).toEqual({ AND: [{ session_filter: { match: "NONE" } }] });
  });

  it("drops empty children but never a relation", () => {
    const emptyGroup: FilterNode = { kind: "group", id: "g", connective: "AND", negate: false, children: [] };
    const relationAnyEmpty: FilterNode = {
      kind: "relation",
      id: "r",
      field: "session_filter",
      match: "ANY",
      child: { kind: "group", id: "g", connective: "AND", negate: false, children: [] },
      negate: false,
    };
    expect(serialize(root(emptyGroup, relationAnyEmpty))).toEqual({ AND: [{ session_filter: {} }] });
  });

  it("does not wrap an empty negated group", () => {
    const negatedEmpty: GroupNode = { kind: "group", id: "g", connective: "AND", negate: true, children: [] };
    expect(serialize(negatedEmpty)).toEqual({});
  });

  it("negated relation serialize: round-trip is a fixed point", () => {
    const input: Record<string, unknown> = {
      NOT: [{ session_filter: { device: { value: [1], modifier: "INCLUDES" } } }],
    };
    const once = serialize(deserialize(input, "game", registry));
    const twice = serialize(deserialize(once, "game", registry));
    expect(twice).toEqual(once);
    // The negated relation is preserved: the canonical form contains a NOT wrapper.
    expect(JSON.stringify(once)).toContain('"NOT"');
  });
});

// Fixture registry: game has a session relation and a session-scoped aggregate
// (session_count, issue #151); session has neither used here.
const registry: MetadataRegistry = {
  game: {
    fields: new Set(["name", "status", "year_released", "search", "session_count"]),
    relations: { session_filter: "session" },
    scopes: { session_count: "session" },
  },
  session: { fields: new Set(["device", "note"]), relations: {}, scopes: {} },
};

type Json = Record<string, unknown>;

describe("deserialize — faithful fold", () => {
  it("root is always a group with criterion imported", () => {
    const tree = deserialize({ status: { value: ["f"], modifier: "INCLUDES" } }, "game", registry);
    expect(tree.kind).toBe("group");
    expect(tree.connective).toBe("AND");
    expect(tree.children[0].kind).toBe("criterion");
  });

  it("{name, OR:[o1,o2]} => OR[name, o1, o2]", () => {
    const tree = deserialize(
      {
        name: { value: "x", modifier: "INCLUDES" },
        OR: [{ status: { value: ["f"], modifier: "INCLUDES" } }, { status: { value: ["p"], modifier: "INCLUDES" } }],
      },
      "game",
      registry,
    );
    expect(tree.connective).toBe("OR");
    expect(tree.children.map((c) => c.kind)).toEqual(["criterion", "criterion", "criterion"]);
  });

  it("{OR:[o1], NOT:[n1]} => AND[o1, n1¬]", () => {
    const tree = deserialize(
      { OR: [{ status: { value: ["f"], modifier: "INCLUDES" } }], NOT: [{ status: { value: ["p"], modifier: "INCLUDES" } }] },
      "game",
      registry,
    );
    expect(tree.connective).toBe("AND");
    expect(tree.children).toHaveLength(2);
    const negated = tree.children[1];
    expect(negated.negate).toBe(true);
  });

  it("places field_comparisons at the outermost AND (after OR)", () => {
    // {name, OR:[a], field_comparisons:[K]} => (name OR a) AND K
    const tree = deserialize(
      {
        name: { value: "x", modifier: "INCLUDES" },
        OR: [{ status: { value: ["f"], modifier: "INCLUDES" } }],
        field_comparisons: [{ left: "a", right: "b", modifier: "LESS_THAN" }],
      },
      "game",
      registry,
    );
    expect(tree.connective).toBe("AND");
    expect(tree.children).toHaveLength(2);
    expect(tree.children[0].kind).toBe("group"); // the OR
    expect((tree.children[0] as GroupNode).connective).toBe("OR");
    expect(tree.children[1].kind).toBe("comparison");
  });

  it("{NOT:[{OR:[a,b]}]} => OR[a,b] with negate", () => {
    const tree = deserialize(
      { NOT: [{ OR: [{ status: { value: ["f"], modifier: "INCLUDES" } }, { status: { value: ["p"], modifier: "INCLUDES" } }] }] },
      "game",
      registry,
    );
    expect(tree.kind).toBe("group");
    // root-wrapped AND over the single negated OR
    const inner = tree.children[0] as GroupNode;
    expect(inner.connective).toBe("OR");
    expect(inner.negate).toBe(true);
  });

  it("double NOT cancels: {NOT:[{NOT:[x]}]} => x", () => {
    const tree = deserialize(
      { NOT: [{ NOT: [{ status: { value: ["f"], modifier: "INCLUDES" } }] }] },
      "game",
      registry,
    );
    const leaf = tree.children[0];
    expect(leaf.kind).toBe("criterion");
    expect(leaf.negate).toBe(false);
  });

  it("{NOT:[a,b]} => AND[a¬, b¬]", () => {
    const tree = deserialize(
      { NOT: [{ status: { value: ["f"], modifier: "INCLUDES" } }, { name: { value: "x", modifier: "INCLUDES" } }] },
      "game",
      registry,
    );
    expect(tree.children.every((c) => c.negate)).toBe(true);
    expect(tree.children).toHaveLength(2);
  });

  it("imports a relation descent with quantifier and target model", () => {
    const tree = deserialize(
      { session_filter: { match: "NONE", device: { value: [1], modifier: "INCLUDES" } } },
      "game",
      registry,
    );
    const relation = tree.children[0];
    expect(relation.kind).toBe("relation");
    if (relation.kind === "relation") {
      expect(relation.match).toBe("NONE");
      expect(relation.field).toBe("session_filter");
      expect(relation.child.children[0].kind).toBe("criterion");
    }
  });

  it("keeps an empty relation (ANY) as a presence test", () => {
    const tree = deserialize({ session_filter: {} }, "game", registry);
    const relation = tree.children[0];
    expect(relation.kind).toBe("relation");
    if (relation.kind === "relation") {
      expect(relation.match).toBe("ANY");
      expect(relation.child.children).toHaveLength(0);
    }
  });

  it("drops unknown keys (backend from_json parity)", () => {
    const tree = deserialize({ totally_unknown: { value: 1, modifier: "EQUALS" } }, "game", registry);
    expect(tree.children).toHaveLength(0);
  });

  it("known field with non-object value is dropped", () => {
    const tree = deserialize({ status: "bad" }, "game", registry);
    expect(tree.children).toHaveLength(0);
  });

  it("rejects over-deep nesting", () => {
    let blob: Json = { status: { value: ["f"], modifier: "INCLUDES" } };
    for (let i = 0; i < 12; i++) blob = { AND: [blob] };
    expect(() => deserialize(blob, "game", registry)).toThrow(/too deep/i);
  });

  it("depth boundary: 10 nested AND wraps does not throw", () => {
    let blob: Json = { status: { value: ["f"], modifier: "INCLUDES" } };
    for (let i = 0; i < 10; i++) blob = { AND: [blob] };
    expect(() => deserialize(blob, "game", registry)).not.toThrow();
  });

  it("depth boundary: 11 nested AND wraps throws DEPTH_EXCEEDED", () => {
    let blob: Json = { status: { value: ["f"], modifier: "INCLUDES" } };
    for (let i = 0; i < 11; i++) blob = { AND: [blob] };
    let thrownError: unknown;
    try {
      deserialize(blob, "game", registry);
    } catch (error) {
      thrownError = error;
    }
    expect(thrownError).toBeInstanceOf(FilterTreeError);
    expect((thrownError as FilterTreeError).code).toBe("DEPTH_EXCEEDED");
  });

  it("breadth cap: OR of 101 items throws BREADTH_EXCEEDED", () => {
    const orItems = Array.from({ length: 101 }, () => ({ status: { value: ["f"], modifier: "INCLUDES" } }));
    let thrownError: unknown;
    try {
      deserialize({ OR: orItems }, "game", registry);
    } catch (error) {
      thrownError = error;
    }
    expect(thrownError).toBeInstanceOf(FilterTreeError);
    expect((thrownError as FilterTreeError).code).toBe("BREADTH_EXCEEDED");
  });

  it("field_comparisons count cap: 101 entries throws FIELD_COMPARISONS_EXCEEDED", () => {
    const comparisons = Array.from({ length: 101 }, () => ({ left: "a", right: "b", modifier: "LESS_THAN" }));
    let thrownError: unknown;
    try {
      deserialize({ field_comparisons: comparisons }, "game", registry);
    } catch (error) {
      thrownError = error;
    }
    expect(thrownError).toBeInstanceOf(FilterTreeError);
    expect((thrownError as FilterTreeError).code).toBe("FIELD_COMPARISONS_EXCEEDED");
  });

  it("field_comparisons non-dict entry throws INVALID_FIELD_COMPARISON", () => {
    let thrownError: unknown;
    try {
      deserialize({ field_comparisons: ["nope"] }, "game", registry);
    } catch (error) {
      thrownError = error;
    }
    expect(thrownError).toBeInstanceOf(FilterTreeError);
    expect((thrownError as FilterTreeError).code).toBe("INVALID_FIELD_COMPARISON");
  });

  it("unknown model key throws UNKNOWN_MODEL", () => {
    let thrownError: unknown;
    try {
      deserialize({ status: { value: ["f"], modifier: "INCLUDES" } }, "nonexistent", registry);
    } catch (error) {
      thrownError = error;
    }
    expect(thrownError).toBeInstanceOf(FilterTreeError);
    expect((thrownError as FilterTreeError).code).toBe("UNKNOWN_MODEL");
  });

  it("invalid relation match quantifier throws INVALID_MATCH", () => {
    let thrownError: unknown;
    try {
      deserialize(
        { session_filter: { match: "SOME", device: { value: [1], modifier: "INCLUDES" } } },
        "game",
        registry,
      );
    } catch (error) {
      thrownError = error;
    }
    expect(thrownError).toBeInstanceOf(FilterTreeError);
    expect((thrownError as FilterTreeError).code).toBe("INVALID_MATCH");
  });

  it("relation match is case-sensitive: lowercase 'none' throws INVALID_MATCH", () => {
    let thrownError: unknown;
    try {
      deserialize({ session_filter: { match: "none" } }, "game", registry);
    } catch (error) {
      thrownError = error;
    }
    expect(thrownError).toBeInstanceOf(FilterTreeError);
    expect((thrownError as FilterTreeError).code).toBe("INVALID_MATCH");
  });

  it("serialize guards against a cyclic node tree (SERIALIZE_DEPTH_EXCEEDED)", () => {
    const cyclic = group("AND", []);
    cyclic.children.push(cyclic); // a group that contains itself
    let thrownError: unknown;
    try {
      serialize(cyclic);
    } catch (error) {
      thrownError = error;
    }
    expect(thrownError).toBeInstanceOf(FilterTreeError);
    expect((thrownError as FilterTreeError).code).toBe("SERIALIZE_DEPTH_EXCEEDED");
  });
});

import { writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import fixtures from "./fixtures.json";

type CanonicalCase = { description: string; model: string; filter: Record<string, unknown> };

function buildRegistry(raw: typeof fixtures.registry): MetadataRegistry {
  const registry: Record<string, ModelMeta> = {};
  for (const [model, meta] of Object.entries(raw)) {
    registry[model] = {
      fields: new Set(meta.fields),
      relations: meta.relations,
      scopes: "scopes" in meta ? meta.scopes : {},
    } as ModelMeta;
  }
  return registry;
}

describe("round-trip over fixtures + canonical artifact", () => {
  const registry = buildRegistry(fixtures.registry);
  const canonical: CanonicalCase[] = [];

  for (const testCase of fixtures.cases) {
    it(`serialize(deserialize(x)) is a fixed point: ${testCase.description}`, () => {
      const once = serialize(deserialize(testCase.filter as Record<string, unknown>, testCase.model, registry));
      const twice = serialize(deserialize(once, testCase.model, registry));
      expect(twice).toEqual(once); // canonical form is stable under re-round-trip
      canonical.push({ description: testCase.description, model: testCase.model, filter: once });
    });
  }

  it("writes the canonical artifact for the Python contract", () => {
    const canonicalPath = fileURLToPath(new URL("./fixtures.canonical.json", import.meta.url));
    writeFileSync(canonicalPath, JSON.stringify({ cases: canonical }, null, 2));
    expect(canonical.length).toBe(fixtures.cases.length);
  });
});

describe("aggregate scope (#151)", () => {
  function deckScope(): GroupNode {
    return {
      kind: "group",
      id: "sg",
      connective: "AND",
      negate: false,
      children: [
        { kind: "criterion", id: "sc", field: "device", criterion: { value: [1], modifier: "INCLUDES" }, negate: false },
      ],
    };
  }

  it("serializes the scope group inside the criterion payload", () => {
    const leaf: FilterNode = {
      kind: "criterion",
      id: "c",
      field: "session_count",
      criterion: { value: 5, modifier: "GREATER_THAN" },
      scope: deckScope(),
      negate: false,
    };
    expect(serialize(root(leaf))).toEqual({
      AND: [
        {
          session_count: {
            value: 5,
            modifier: "GREATER_THAN",
            scope: { AND: [{ device: { value: [1], modifier: "INCLUDES" } }] },
          },
        },
      ],
    });
  });

  it("omits an empty scope group entirely (canonical unscoped)", () => {
    const leaf: FilterNode = {
      kind: "criterion",
      id: "c",
      field: "session_count",
      criterion: { value: 5, modifier: "GREATER_THAN" },
      scope: { kind: "group", id: "sg", connective: "AND", negate: false, children: [] },
      negate: false,
    };
    expect(serialize(root(leaf))).toEqual({
      AND: [{ session_count: { value: 5, modifier: "GREATER_THAN" } }],
    });
  });

  it("deserializes a scoped aggregate into a leaf with a scope group", () => {
    const tree = deserialize(
      {
        session_count: {
          value: 5,
          modifier: "GREATER_THAN",
          scope: { device: { value: [1], modifier: "INCLUDES" } },
        },
      },
      "game",
      registry,
    );
    const leaf = tree.children[0];
    if (leaf.kind !== "criterion") throw new Error("expected a criterion leaf");
    // The scope key is split out of the opaque payload…
    expect(leaf.criterion).toEqual({ value: 5, modifier: "GREATER_THAN" });
    // …into a child group over the scope's target model.
    expect(leaf.scope).toBeDefined();
    expect(leaf.scope!.children).toEqual([
      expect.objectContaining({
        kind: "criterion",
        field: "device",
        criterion: { value: [1], modifier: "INCLUDES" },
        negate: false,
      }),
    ]);
  });

  it("deserializes an empty scope as unscoped (backend parity)", () => {
    const tree = deserialize(
      { session_count: { value: 1, modifier: "EQUALS", scope: {} } },
      "game",
      registry,
    );
    const leaf = tree.children[0];
    if (leaf.kind !== "criterion") throw new Error("expected a criterion leaf");
    expect(leaf.scope).toBeUndefined();
    expect(leaf.criterion).toEqual({ value: 1, modifier: "EQUALS" });
  });

  it("keeps a stray scope key verbatim on a non-scopable field", () => {
    const tree = deserialize(
      { year_released: { value: 2000, modifier: "EQUALS", scope: { device: { value: [1] } } } },
      "game",
      registry,
    );
    const leaf = tree.children[0];
    if (leaf.kind !== "criterion") throw new Error("expected a criterion leaf");
    expect(leaf.scope).toBeUndefined();
    expect(leaf.criterion).toEqual({
      value: 2000,
      modifier: "EQUALS",
      scope: { device: { value: [1] } },
    });
  });

  it("scoped aggregate round-trip is a fixed point", () => {
    const input = {
      session_count: {
        value: 5,
        modifier: "GREATER_THAN",
        scope: { OR: [{ device: { value: [1], modifier: "INCLUDES" } }, { note: { value: "docked", modifier: "INCLUDES" } }] },
      },
    };
    const once = serialize(deserialize(input, "game", registry));
    const twice = serialize(deserialize(once, "game", registry));
    expect(twice).toEqual(once);
    expect(JSON.stringify(once)).toContain('"scope"');
  });

  it("a scope descent consumes depth budget like a relation descent", () => {
    // A registry with the game<->session relation cycle (the file-level fixture
    // registry deliberately leaves session without relations).
    const cyclicRegistry: MetadataRegistry = {
      ...registry,
      session: { ...registry.session, relations: { game_filter: "game" } },
    };
    // Build a scope whose inner filter nests past MAX_FILTER_DEPTH via
    // game_filter/session_filter alternation. The scope is a *session* filter, so
    // the outermost relation must be session's `game_filter` (even final level),
    // then alternate — a wrong-model relation key would be silently dropped and
    // the depth guard never reached.
    let inner: Record<string, unknown> = { device: { value: [1], modifier: "INCLUDES" } };
    for (let level = 0; level < 11; level += 1) {
      inner = level % 2 === 0 ? { game_filter: inner } : { session_filter: inner };
    }
    expect(() =>
      deserialize({ session_count: { value: 1, scope: inner } }, "game", cyclicRegistry),
    ).toThrow(FilterTreeError);
  });
});
