# Tree Serializer/Deserializer (#188) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone TS module that converts a filter node-tree ↔ `OperatorFilter` JSON, with canonical export and faithful (backend-precedence) import, unit-tested under vitest and contract-tested against the Python backend.

**Architecture:** A types-only `filter-tree/types.ts` (discriminated node union + metadata interface) is the dependency hub. `filter-tree/serializer.ts` implements pure `serialize`/`deserialize` (no DOM). Correctness is pinned by vitest unit tests plus a shared `fixtures.json` that a Python test feeds through `filter_from_json` → `to_q()` for cross-language equivalence.

**Tech Stack:** TypeScript (ES2022, `moduleResolution: Bundler`, `.js` import specifiers), vitest, pytest/pytest-django, pnpm.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-06-29-issue-188-tree-serializer-design.md`. Every task implements part of it.
- This module is **isolated**: do **not** edit `ts/elements/filter-bar.ts` or any builder UI. No DOM access in `serializer.ts`/`types.ts`.
- Payloads (`CriterionPayload`, comparison dict) are **opaque** — never inspected, only passed through.
- Import mirrors backend caps verbatim: `MAX_FILTER_DEPTH = 10`, `MAX_FILTER_BREADTH = 100`, `MAX_FIELD_COMPARISONS = 100` (`common/criteria.py:791,803`).
- Backend fold precedence (the import contract): `own-criteria & relations → AND → OR → ~NOT → field_comparisons` (field_comparisons are the **outermost** `&`). Source: `common/criteria.py:1159-1194,1205-1211`.
- Reserved JSON keys (handled structurally, never treated as fields/relations): `AND`, `OR`, `NOT`, `match`, `field_comparisons`.
- `RelationMatch` values are uppercase `"ANY"|"NONE"|"ALL"`; `ANY` is default and omitted on export.
- Round-trip guarantee is **logical (`to_q`) equivalence**, not byte equality.
- Naming: complete words, no abbreviations (project convention).
- Commit after each task. Branch already exists: `feat/188-tree-serializer`.

---

### Task 1: Build wiring — vitest runs, never ships to dist

**Files:**
- Modify: `package.json` (add `vitest` devDependency + `test:ts` script)
- Create: `vitest.config.ts`
- Modify: `tsconfig.json` (exclude `*.test.ts` from the emit build)
- Modify: `Makefile` (add `test-ts` target; add it to `check`)
- Test (temporary): `ts/elements/filter-tree/smoke.test.ts`

**Interfaces:**
- Consumes: nothing.
- Produces: a working `make test-ts` (runs `vitest run`) and a build that excludes test files. Later tasks rely on `make test-ts` to run their vitest suites and on `make ts-check`/`make ts` ignoring `*.test.ts`.

- [ ] **Step 1: Add vitest as a devDependency**

Run: `pnpm add -D vitest`
Expected: `package.json` `devDependencies` gains a `vitest` entry; `pnpm-lock.yaml` updates.

- [ ] **Step 2: Add a `test:ts` script to `package.json`**

In `package.json`, add a `"scripts"` block (the file currently has none):

```json
  "scripts": {
    "test:ts": "vitest run"
  },
```

- [ ] **Step 3: Create `vitest.config.ts`**

```ts
import { defineConfig } from "vitest/config";

// Vitest/Vite resolves `./foo.js` import specifiers to the sibling `foo.ts`,
// so the module's NodeNext-style `.js` imports work without a compile step.
export default defineConfig({
  test: {
    include: ["ts/**/*.test.ts"],
    environment: "node",
  },
});
```

- [ ] **Step 4: Exclude test files from the emit build**

In `tsconfig.json`, add a top-level `"exclude"` key alongside `"include"`:

```json
  "include": ["ts/**/*.ts"],
  "exclude": ["ts/**/*.test.ts"]
```

This keeps `*.test.js` out of `games/static/js/dist/` and out of `tsc --noEmit` (`make ts-check`), so vitest-only imports never break the build.

- [ ] **Step 5: Add the `test-ts` Makefile target and wire it into `check`**

After the `ts-check` target (around `Makefile:47`), add:

```makefile
test-ts:
	pnpm exec vitest run
```

Then change the `check` line (`Makefile:115`) from:

```makefile
check: lint format-check typecheck ts-check check-icons test
```

to:

```makefile
check: lint format-check typecheck ts-check check-icons test-ts test
```

- [ ] **Step 6: Write a temporary smoke test**

Create `ts/elements/filter-tree/smoke.test.ts`:

```ts
import { describe, it, expect } from "vitest";

describe("vitest wiring", () => {
  it("runs", () => {
    expect(1 + 1).toBe(2);
  });
});
```

- [ ] **Step 7: Run the smoke test**

Run: `make test-ts`
Expected: vitest runs, 1 passing test.

- [ ] **Step 8: Verify the build ignores test files**

Run: `make ts-check`
Expected: PASS, no errors about the test file.
Run: `make ts && ls games/static/js/dist/elements/filter-tree/ 2>/dev/null`
Expected: directory does not exist or contains no `smoke.test.js` (test file not emitted).

- [ ] **Step 9: Delete the smoke test**

Run: `rm ts/elements/filter-tree/smoke.test.ts`

- [ ] **Step 10: Commit**

```bash
git add package.json pnpm-lock.yaml vitest.config.ts tsconfig.json Makefile
git commit -m "build(filters): wire vitest for the filter-tree module"
```

---

### Task 2: Node types + metadata interface (`types.ts`)

**Files:**
- Create: `ts/elements/filter-tree/types.ts`
- Test: `ts/elements/filter-tree/types.test.ts`

**Interfaces:**
- Consumes: nothing.
- Produces (imported by Tasks 3–5):
  - `type Connective = "AND" | "OR"`
  - `type RelationMatch = "ANY" | "NONE" | "ALL"`
  - `type CriterionPayload = Record<string, unknown>`
  - `interface GroupNode { kind: "group"; connective: Connective; negate: boolean; children: FilterNode[] }`
  - `interface CriterionLeaf { kind: "criterion"; field: string; criterion: CriterionPayload; negate: boolean }`
  - `interface ComparisonLeaf { kind: "comparison"; comparison: Record<string, unknown>; negate: boolean }`
  - `interface RelationNode { kind: "relation"; field: string; match: RelationMatch; child: GroupNode; negate: boolean }`
  - `type FilterNode = GroupNode | CriterionLeaf | ComparisonLeaf | RelationNode`
  - `interface ModelMeta { fields: ReadonlySet<string>; relations: Record<string, string> }`
  - `type MetadataRegistry = Record<string, ModelMeta>`
  - `const MAX_FILTER_DEPTH = 10`, `MAX_FILTER_BREADTH = 100`, `MAX_FIELD_COMPARISONS = 100`
  - `const RESERVED_KEYS: ReadonlySet<string>`
  - `class FilterTreeError extends Error`

- [ ] **Step 1: Write the failing test**

Create `ts/elements/filter-tree/types.test.ts`:

```ts
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `make test-ts`
Expected: FAIL — cannot resolve `./types.js`.

- [ ] **Step 3: Write `types.ts`**

```ts
/**
 * Filter-tree node model + import metadata interface (issue #188).
 *
 * The discriminated union every nested-filter-builder component switches on, plus
 * the per-model metadata the importer needs to classify JSON keys. Types only +
 * shared constants; the transform logic lives in `serializer.ts`.
 */

export type Connective = "AND" | "OR";
export type RelationMatch = "ANY" | "NONE" | "ALL";

// Opaque to the serializer: whatever a leaf widget produced. Never inspected.
export type CriterionPayload = Record<string, unknown>;

export interface GroupNode {
  kind: "group";
  connective: Connective; // negation is a separate flag, never a connective
  negate: boolean;
  children: FilterNode[];
}

export interface CriterionLeaf {
  kind: "criterion";
  field: string;
  criterion: CriterionPayload;
  negate: boolean;
}

export interface ComparisonLeaf {
  kind: "comparison";
  comparison: Record<string, unknown>;
  negate: boolean;
}

export interface RelationNode {
  kind: "relation";
  field: string;
  match: RelationMatch;
  child: GroupNode; // exactly one canonical group
  negate: boolean;
}

export type FilterNode = GroupNode | CriterionLeaf | ComparisonLeaf | RelationNode;

// Per-model metadata the importer consumes to classify a JSON key as a relation
// descent (and find its target model) or a criterion leaf. Unknown keys are
// dropped, mirroring the backend's `from_json` (it iterates declared fields only).
export interface ModelMeta {
  fields: ReadonlySet<string>; // valid criterion field names (includes "search")
  relations: Record<string, string>; // relationField -> targetModelKey
}

export type MetadataRegistry = Record<string, ModelMeta>; // modelKey -> meta

// Mirror the backend parse-time caps (common/criteria.py:791,803) so the builder
// and backend agree on validity and a deep blob cannot blow the JS stack.
export const MAX_FILTER_DEPTH = 10;
export const MAX_FILTER_BREADTH = 100;
export const MAX_FIELD_COMPARISONS = 100;

export const RESERVED_KEYS: ReadonlySet<string> = new Set([
  "AND",
  "OR",
  "NOT",
  "match",
  "field_comparisons",
]);

export class FilterTreeError extends Error {}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `make test-ts`
Expected: PASS (types + smoke suites green).

- [ ] **Step 5: Commit**

```bash
git add ts/elements/filter-tree/types.ts ts/elements/filter-tree/types.test.ts
git commit -m "feat(filters): filter-tree node model + metadata interface (#188)"
```

---

### Task 3: Canonical export — `serialize()`

**Files:**
- Create: `ts/elements/filter-tree/serializer.ts`
- Test: `ts/elements/filter-tree/serializer.test.ts`

**Interfaces:**
- Consumes: all type exports from Task 2.
- Produces: `export function serialize(root: GroupNode): Record<string, unknown>` and the internal factory `group(connective, children, negate?)` (re-used by Task 4 — export it).

- [ ] **Step 1: Write the failing test**

Create `ts/elements/filter-tree/serializer.test.ts`:

```ts
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `make test-ts`
Expected: FAIL — `./serializer.js` not found.

- [ ] **Step 3: Write `serialize()` in `serializer.ts`**

```ts
/**
 * Filter-tree serializer/deserializer (issue #188).
 *
 * serialize: node tree -> canonical OperatorFilter JSON (single-key children,
 * never a mixed node). deserialize: arbitrary/legacy JSON -> node tree, faithfully
 * reproducing the backend fold order. See the design spec.
 */
import {
  type Connective,
  type FilterNode,
  type GroupNode,
  type MetadataRegistry,
  type RelationMatch,
  FilterTreeError,
  MAX_FIELD_COMPARISONS,
  MAX_FILTER_BREADTH,
  MAX_FILTER_DEPTH,
  RESERVED_KEYS,
} from "./types.js";

type Json = Record<string, unknown>;

export function group(connective: Connective, children: FilterNode[], negate = false): GroupNode {
  return { kind: "group", connective, negate, children };
}

// ── Export ─────────────────────────────────────────────────────────────────

export function serialize(root: GroupNode): Json {
  return serializeNode(root);
}

function serializeNode(node: FilterNode): Json {
  switch (node.kind) {
    case "group": {
      const children = node.children
        .map(serializeNode)
        .filter((dict) => Object.keys(dict).length > 0);
      const inner: Json = children.length ? { [node.connective]: children } : {};
      return wrapNegate(inner, node.negate);
    }
    case "criterion":
      return wrapNegate({ [node.field]: node.criterion }, node.negate);
    case "comparison":
      return wrapNegate({ field_comparisons: [node.comparison] }, node.negate);
    case "relation": {
      const childDict = serializeNode(node.child); // {} | {AND:…} | {OR:…} | {NOT:…}
      const relationDict: Json = {
        ...(node.match !== "ANY" ? { match: node.match } : {}),
        ...childDict,
      };
      return wrapNegate({ [node.field]: relationDict }, node.negate);
    }
  }
}

// Negating identity ({}) is still identity, so an empty dict is never wrapped.
function wrapNegate(dict: Json, negate: boolean): Json {
  if (!negate || Object.keys(dict).length === 0) return dict;
  return { NOT: [dict] };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `make test-ts`
Expected: PASS (all serialize cases green).

- [ ] **Step 5: Commit**

```bash
git add ts/elements/filter-tree/serializer.ts ts/elements/filter-tree/serializer.test.ts
git commit -m "feat(filters): canonical filter-tree export serialize() (#188)"
```

---

### Task 4: Faithful import — `deserialize()`

**Files:**
- Modify: `ts/elements/filter-tree/serializer.ts` (add `deserialize` + helpers)
- Modify: `ts/elements/filter-tree/serializer.test.ts` (add import tests)

**Interfaces:**
- Consumes: Task 2 types, Task 3 `group()`/`serialize()`.
- Produces: `export function deserialize(dict: Record<string, unknown>, modelKey: string, registry: MetadataRegistry): GroupNode`.

- [ ] **Step 1: Write the failing tests**

Append to `ts/elements/filter-tree/serializer.test.ts`:

```ts
import { deserialize } from "./serializer.js";
import type { MetadataRegistry } from "./types.js";

// Fixture registry: game has a session relation; session has none used here.
const registry: MetadataRegistry = {
  game: { fields: new Set(["name", "status", "year_released", "search"]), relations: { session_filter: "session" } },
  session: { fields: new Set(["device", "note"]), relations: {} },
};

function crit(field: string, value: unknown) {
  return { kind: "criterion", field, criterion: { value, modifier: "INCLUDES" }, negate: false };
}

describe("deserialize — faithful fold", () => {
  it("root is always a group", () => {
    const tree = deserialize({ status: { value: ["f"], modifier: "INCLUDES" } }, "game", registry);
    expect(tree.kind).toBe("group");
    expect(tree.connective).toBe("AND");
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

  it("rejects over-deep nesting", () => {
    let blob: Json = { status: { value: ["f"], modifier: "INCLUDES" } };
    for (let i = 0; i < 12; i++) blob = { AND: [blob] };
    expect(() => deserialize(blob, "game", registry)).toThrow(/too deep/i);
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `make test-ts`
Expected: FAIL — `deserialize` not exported.

- [ ] **Step 3: Implement `deserialize()` and helpers**

Append to `ts/elements/filter-tree/serializer.ts`:

```ts
// ── Import ─────────────────────────────────────────────────────────────────

export function deserialize(dict: Json, modelKey: string, registry: MetadataRegistry): GroupNode {
  return asGroup(deserializeNode(dict, modelKey, registry, 0));
}

function deserializeNode(dict: Json, modelKey: string, registry: MetadataRegistry, depth: number): FilterNode {
  if (depth > MAX_FILTER_DEPTH) {
    throw new FilterTreeError(`Filter nesting too deep (max ${MAX_FILTER_DEPTH})`);
  }
  const meta = registry[modelKey];
  if (!meta) throw new FilterTreeError(`Unknown model ${modelKey}`);

  // 1. Base: own criteria + relations + AND-subs, all &-composed (pre-OR).
  const baseChildren: FilterNode[] = [];
  for (const key of Object.keys(dict)) {
    if (RESERVED_KEYS.has(key)) continue;
    const value = dict[key];
    if (key in meta.relations) {
      if (isObject(value)) {
        baseChildren.push(relationNode(key, value, meta.relations[key], registry, depth));
      }
    } else if (meta.fields.has(key) && isObject(value)) {
      baseChildren.push({ kind: "criterion", field: key, criterion: value, negate: false });
    }
    // else: unknown key or non-object value -> dropped (backend from_json parity)
  }
  const andSubs = asArray(dict.AND);
  checkBreadth(andSubs);
  for (const sub of andSubs) {
    if (isObject(sub)) baseChildren.push(deserializeNode(sub, modelKey, registry, depth + 1));
  }
  let core: FilterNode = collapse(group("AND", baseChildren));

  // 2. OR: (base OR or-subs). An empty base is dropped (Q() | Q(x) == Q(x)).
  const orSubs = asArray(dict.OR);
  checkBreadth(orSubs);
  if (orSubs.length) {
    const orChildren: FilterNode[] = [];
    if (!isEmptyGroup(core)) orChildren.push(core);
    for (const sub of orSubs) {
      if (isObject(sub)) orChildren.push(deserializeNode(sub, modelKey, registry, depth + 1));
    }
    core = collapse(group("OR", orChildren));
  }

  // 3. Tail: ~NOT (negate toggled), then field_comparisons — the outermost &.
  const tail: FilterNode[] = [];
  const notSubs = asArray(dict.NOT);
  checkBreadth(notSubs);
  for (const sub of notSubs) {
    if (isObject(sub)) tail.push(withNegateToggled(deserializeNode(sub, modelKey, registry, depth + 1)));
  }
  const comparisons = asArray(dict.field_comparisons);
  if (comparisons.length > MAX_FIELD_COMPARISONS) {
    throw new FilterTreeError(`Too many field_comparisons (max ${MAX_FIELD_COMPARISONS})`);
  }
  for (const comparison of comparisons) {
    if (isObject(comparison)) tail.push({ kind: "comparison", comparison, negate: false });
  }

  if (!tail.length) return core;
  const andChildren: FilterNode[] = [];
  if (!isEmptyGroup(core)) andChildren.push(core);
  andChildren.push(...tail);
  return collapse(group("AND", andChildren));
}

function relationNode(
  field: string,
  raw: Json,
  targetModel: string,
  registry: MetadataRegistry,
  depth: number,
): FilterNode {
  const sub: Json = { ...raw };
  const match = parseMatch(sub.match);
  delete sub.match;
  const child = asGroup(deserializeNode(sub, targetModel, registry, depth + 1));
  return { kind: "relation", field, match, child, negate: false };
}

function parseMatch(value: unknown): RelationMatch {
  if (value == null) return "ANY";
  if (value === "ANY" || value === "NONE" || value === "ALL") return value;
  throw new FilterTreeError(`Unknown relation match ${JSON.stringify(value)}`);
}

// Negate is a composable node property: toggling the returned node's flag means
// "negate this node" (serialize wraps it in {NOT:[…]}), so ~~x cancels and no
// De Morgan rewrite is needed.
function withNegateToggled(node: FilterNode): FilterNode {
  return { ...node, negate: !node.negate };
}

// A single-child AND/OR group is its child (which keeps its own negate).
function collapse(node: FilterNode): FilterNode {
  if (node.kind === "group" && !node.negate && node.children.length === 1) {
    return node.children[0];
  }
  return node;
}

function isEmptyGroup(node: FilterNode): boolean {
  return node.kind === "group" && node.children.length === 0 && !node.negate;
}

function asGroup(node: FilterNode): GroupNode {
  return node.kind === "group" ? node : group("AND", [node]);
}

function asArray(value: unknown): unknown[] {
  if (value == null) return [];
  return Array.isArray(value) ? value : [value];
}

function checkBreadth(list: unknown[]): void {
  if (list.length > MAX_FILTER_BREADTH) {
    throw new FilterTreeError(`Operator list too long (max ${MAX_FILTER_BREADTH})`);
  }
}

function isObject(value: unknown): value is Json {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `make test-ts`
Expected: PASS (all import + export cases green).

- [ ] **Step 5: Verify the build still type-checks**

Run: `make ts-check`
Expected: PASS (serializer.ts compiles; test files excluded).

- [ ] **Step 6: Commit**

```bash
git add ts/elements/filter-tree/serializer.ts ts/elements/filter-tree/serializer.test.ts
git commit -m "feat(filters): faithful filter-tree import deserialize() (#188)"
```

---

### Task 5: Shared fixtures + cross-language contract test

**Files:**
- Create: `ts/elements/filter-tree/fixtures.json`
- Modify: `ts/elements/filter-tree/serializer.test.ts` (round-trip over fixtures)
- Create: `tests/test_filter_tree_contract.py`

**Interfaces:**
- Consumes: Task 3 `serialize`, Task 4 `deserialize` (TS side); `parse_game_filter`/`parse_session_filter` + `GameFilter`/`SessionFilter` from `games.filters` (Python side).
- Produces: a `fixtures.json` of `{ description, model, filter }` cases that BOTH languages read.

- [ ] **Step 1: Create `fixtures.json`**

Each case is a real `OperatorFilter` JSON dict. `model` is the registry key. Uses only fields/relations that exist on the named filter (`games/filters.py`).

```json
{
  "registry": {
    "game": {
      "fields": ["name", "status", "year_released", "search"],
      "relations": { "session_filter": "session" }
    },
    "session": {
      "fields": ["device", "note"],
      "relations": { "game_filter": "game" }
    }
  },
  "cases": [
    { "description": "single criterion", "model": "game",
      "filter": { "status": { "value": ["f"], "modifier": "INCLUDES" } } },
    { "description": "canonical OR", "model": "game",
      "filter": { "OR": [ { "status": { "value": ["f"], "modifier": "INCLUDES" } }, { "status": { "value": ["p"], "modifier": "INCLUDES" } } ] } },
    { "description": "mixed name OR status (faithful fold)", "model": "game",
      "filter": { "name": { "value": "zelda", "modifier": "INCLUDES" }, "OR": [ { "status": { "value": ["f"], "modifier": "INCLUDES" } } ] } },
    { "description": "OR with NOT", "model": "game",
      "filter": { "OR": [ { "status": { "value": ["f"], "modifier": "INCLUDES" } } ], "NOT": [ { "status": { "value": ["p"], "modifier": "INCLUDES" } } ] } },
    { "description": "NOT of OR (De Morgan)", "model": "game",
      "filter": { "NOT": [ { "OR": [ { "status": { "value": ["f"], "modifier": "INCLUDES" } }, { "status": { "value": ["p"], "modifier": "INCLUDES" } } ] } ] } },
    { "description": "multi-child NOT", "model": "game",
      "filter": { "NOT": [ { "status": { "value": ["f"], "modifier": "INCLUDES" } }, { "name": { "value": "x", "modifier": "INCLUDES" } } ] } },
    { "description": "relation ANY with child", "model": "game",
      "filter": { "session_filter": { "device": { "value": [1], "modifier": "INCLUDES" } } } },
    { "description": "relation NONE presence test", "model": "game",
      "filter": { "session_filter": { "match": "NONE" } } },
    { "description": "relation ANY presence test", "model": "game",
      "filter": { "session_filter": {} } }
  ]
}
```

Note: the `field_comparisons` precedence case is exercised only by the TS unit test in Task 4 (PurchaseFilter is the comparison-bearing model; keep the cross-language fixtures to game/session to stay simple). The Python contract still covers OR/NOT/relation/presence — the cases most likely to diverge.

- [ ] **Step 2: Write the TS round-trip test that also emits the canonical artifact**

The genuine cross-language contract is: the **TS serializer's actual output** (not a
backend re-derivation) must be `to_q`-equivalent to the source. So the TS test writes
`serialize(deserialize(fixture))` for each case to a generated artifact that the Python
test then evaluates. Append to `ts/elements/filter-tree/serializer.test.ts`:

```ts
import { writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import fixtures from "./fixtures.json";
import type { ModelMeta } from "./types.js";

function buildRegistry(raw: typeof fixtures.registry): MetadataRegistry {
  const out: MetadataRegistry = {};
  for (const [model, meta] of Object.entries(raw)) {
    out[model] = { fields: new Set(meta.fields), relations: meta.relations } as ModelMeta;
  }
  return out;
}

describe("round-trip over fixtures + canonical artifact", () => {
  const reg = buildRegistry(fixtures.registry);
  const canonical: Array<{ description: string; model: string; filter: Record<string, unknown> }> = [];

  for (const testCase of fixtures.cases) {
    it(`serialize(deserialize(x)) is a fixed point: ${testCase.description}`, () => {
      const once = serialize(deserialize(testCase.filter as Record<string, unknown>, testCase.model, reg));
      const twice = serialize(deserialize(once, testCase.model, reg));
      expect(twice).toEqual(once); // canonical form is stable under re-round-trip
      canonical.push({ description: testCase.description, model: testCase.model, filter: once });
    });
  }

  it("writes the canonical artifact for the Python contract", () => {
    const out = fileURLToPath(new URL("./fixtures.canonical.json", import.meta.url));
    writeFileSync(out, JSON.stringify({ cases: canonical }, null, 2));
    expect(canonical.length).toBe(fixtures.cases.length);
  });
});
```

- [ ] **Step 3: Run the TS round-trip test**

Run: `make test-ts`
Expected: PASS — every fixture is a fixed point; `ts/elements/filter-tree/fixtures.canonical.json` is written.

Note: vitest/Vite imports JSON natively, so `import fixtures from "./fixtures.json"` needs no import attribute. If a future vitest requires `with { type: "json" }`, add it.

- [ ] **Step 4: Gitignore the generated artifact**

The canonical artifact is build output (regenerated by `make test-ts`), not source. Append to `.gitignore`:

```
ts/elements/filter-tree/fixtures.canonical.json
```

- [ ] **Step 5: Write the Python contract test**

Create `tests/test_filter_tree_contract.py`. It reads the original fixtures **and** the
TS-emitted canonical artifact, and asserts that the TS serializer's actual output is
`to_q()`-equivalent to the original source filter — the real cross-language lock. It is
skipped (not failed) when the artifact is absent, so a bare `pytest` without a prior
`make test-ts` does not spuriously fail; `make check` runs `test-ts` before `test`, so
the gate always evaluates it against fresh output.

```python
"""Cross-language contract for the filter-tree serializer (issue #188).

The TS vitest suite emits fixtures.canonical.json = serialize(deserialize(x)) for every
shared fixture. This test asserts the TS serializer's ACTUAL output parses via the
backend and is to_q()-equivalent to the original source filter — locking the TS
canonical form to backend semantics (the OR / NOT / relation / presence cases most
likely to diverge). Skipped if the artifact is missing (run `make test-ts` first);
`make check` orders test-ts before this so the gate always sees fresh output.
"""

import json
from pathlib import Path

import pytest

from common.criteria import filter_from_json
from games.filters import GameFilter, SessionFilter

FILTER_TREE_DIR = Path(__file__).resolve().parent.parent / "ts" / "elements" / "filter-tree"
FIXTURES = json.loads((FILTER_TREE_DIR / "fixtures.json").read_text())
CANONICAL_PATH = FILTER_TREE_DIR / "fixtures.canonical.json"

FILTER_FOR_MODEL = {"game": GameFilter, "session": SessionFilter}

# Map each original fixture to its TS-emitted canonical form, by description.
if CANONICAL_PATH.exists():
    _canonical_by_description = {
        case["description"]: case for case in json.loads(CANONICAL_PATH.read_text())["cases"]
    }
else:
    _canonical_by_description = {}


def _q_str(filter_object) -> str:
    # str(Q) is a stable structural rendering; equal structures compare equal.
    return str(filter_object.to_q())


@pytest.mark.skipif(
    not CANONICAL_PATH.exists(),
    reason="fixtures.canonical.json missing — run `make test-ts` first",
)
@pytest.mark.parametrize("case", FIXTURES["cases"], ids=[c["description"] for c in FIXTURES["cases"]])
def test_ts_canonical_output_is_to_q_equivalent(case):
    filter_cls = FILTER_FOR_MODEL[case["model"]]

    original = filter_from_json(filter_cls, json.dumps(case["filter"]))
    assert original is not None, f"fixture did not parse: {case['description']}"

    ts_canonical = _canonical_by_description[case["description"]]
    reparsed = filter_from_json(filter_cls, json.dumps(ts_canonical["filter"]))
    assert reparsed is not None, f"TS canonical did not parse: {case['description']}"

    assert _q_str(reparsed) == _q_str(original), case["description"]
```

- [ ] **Step 6: Run the Python contract test**

Run: `make test-ts && uv run --with pytest-django pytest tests/test_filter_tree_contract.py -v`
Expected: PASS — the TS serializer's actual output is `to_q()`-equivalent to every source fixture.

- [ ] **Step 7: Run the whole check suite**

Run: `make check`
Expected: PASS — lint, format, mypy, ts-check, icons, `test-ts` (vitest), pytest all green.

- [ ] **Step 8: Commit**

```bash
git add ts/elements/filter-tree/fixtures.json ts/elements/filter-tree/serializer.test.ts tests/test_filter_tree_contract.py .gitignore
git commit -m "test(filters): cross-language contract fixtures for the tree serializer (#188)"
```

---

## Notes for the implementer

- **`.js` import specifiers resolve to `.ts`** under vitest/Vite — that is intentional and required for the `tsc`/dist build to emit valid ESM. Do not drop the `.js` extension.
- **Never touch `filter-bar.ts`** — the flat glue stays until #197/#201.
- If the Python contract's `str(Q())` comparison proves too brittle for a future
  case (operator ordering), switch to comparing query results against a small set
  of ORM fixtures; for the current fixtures the structural string is stable.
- The `field_comparisons`-with-OR precedence case (the A1 finding) is covered by the
  TS unit test in Task 4; if you later add a PurchaseFilter fixture, assert
  `(C | O) & K`, not `(C & K) | O`.
