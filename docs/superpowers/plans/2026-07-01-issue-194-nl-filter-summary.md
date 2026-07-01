# NL Filter Summary (#194) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A pure client-side `summarize(tree, ctx)` that turns a filter `GroupNode` tree into a natural-language sentence, plus its vitest suite and a Python modifier contract.

**Architecture:** One DOM-free TS module `ts/elements/filter-tree/summary.ts` walks the immutable `GroupNode` tree (the same tree the serializer consumes), resolves human labels from per-model `FieldMeta` metadata passed in explicitly, and returns a string. No page wiring, no backend — mounting into the builder is component 10 (a later issue). A Python contract test guards the modifier→phrase map against `common.criteria.Modifier` drift, mirroring `test_filter_tokens_contract.py`.

**Tech Stack:** TypeScript (NodeNext ESM, `.js` import specifiers resolving to sibling `.ts`), vitest, pytest.

## Global Constraints

- Run every command inside the Nix dev shell: prefix with `direnv exec .` (e.g. `direnv exec . pnpm exec vitest run`). A bare `pnpm`/`pytest` has no toolchain on PATH.
- The module is **pure and DOM-free**: it reads only `node.*` payloads + the passed metadata. Never touch `document`/widgets.
- Import behavioral token helpers from `../filter-tokens.js`; import completeness predicates from `./operations.js`; import types from `./types.js`. Use `.js` specifiers (NodeNext).
- Name variables with complete words (`element` not `el`, `value`/`item` not single letters). New TS files are excluded from the emit build but type-checked by `tsconfig.check.json`.
- Relation noun = the relation field's `FieldMeta.label`, **lowercased as-is** (no singularization).
- Incomplete nodes are **kept in the sentence as placeholders**, never pruned.
- Final gate before "done": full `direnv exec . make check` green (includes e2e).

---

## File structure

- `ts/elements/filter-tree/summary.ts` — the walker (created across Tasks 1–6).
- `ts/elements/filter-tree/summary.test.ts` — vitest suite + canonical-artifact emitter (grown across tasks; artifact write added Task 7).
- `ts/elements/filter-tree/summary-modifiers.canonical.json` — gitignored artifact (Task 7).
- `tests/test_summary_modifier_contract.py` — Python contract (Task 7).
- `.gitignore` — add the canonical artifact path (Task 7).

---

### Task 1: Module scaffold — frame, single scalar leaf, incomplete placeholders

**Files:**
- Create: `ts/elements/filter-tree/summary.ts`
- Test: `ts/elements/filter-tree/summary.test.ts`

**Interfaces:**
- Consumes: `GroupNode`, `CriterionLeaf`, `FieldMeta` from `./types.js`; `isCriterionComplete` from `./operations.js`.
- Produces:
  - `interface SummaryModel { fields: Map<string, FieldMeta>; columns?: Map<string, string> }`
  - `interface SummaryContext { modelKey: string; modelLabel: string; models: Record<string, SummaryModel> }`
  - `export const MODIFIER_PHRASES: Record<string, string>`
  - `export function summarize(tree: GroupNode, ctx: SummaryContext): string`

- [ ] **Step 1: Write the failing test**

Create `ts/elements/filter-tree/summary.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import { summarize, type SummaryContext } from "./summary.js";
import type { FieldMeta, GroupNode } from "./types.js";

// Minimal FieldMeta stub: only the fields summary reads.
function field(partial: Partial<FieldMeta> & { name: string }): FieldMeta {
  return {
    name: partial.name,
    label: partial.label ?? partial.name,
    kind: partial.kind ?? "string",
    nullable: partial.nullable ?? false,
    choices: partial.choices ?? [],
    modifiers: partial.modifiers ?? [],
    relations: partial.relations ?? [],
    search_url: partial.search_url ?? "",
    is_m2m: partial.is_m2m ?? false,
  };
}

const GAME: SummaryContext = {
  modelKey: "game",
  modelLabel: "Games",
  models: {
    game: {
      fields: new Map([
        ["name", field({ name: "name", label: "Name", kind: "string" })],
        [
          "status",
          field({
            name: "status",
            label: "Status",
            kind: "set",
            choices: [
              { value: "f", label: "Finished" },
              { value: "p", label: "Playing" },
            ],
          }),
        ],
      ]),
    },
  },
};

function root(...children: GroupNode["children"]): GroupNode {
  return { kind: "group", id: "g", connective: "AND", negate: false, children };
}

describe("summarize — frame + scalar leaf", () => {
  it("renders the empty root as the all-items frame", () => {
    expect(summarize(root(), GAME)).toBe("Games (all).");
  });

  it("renders a single choice-valued leaf with its label", () => {
    const tree = root({
      kind: "criterion",
      id: "c",
      field: "status",
      criterion: { value: ["f"], modifier: "INCLUDES" },
      negate: false,
    });
    expect(summarize(tree, GAME)).toBe("Games where Status is Finished.");
  });

  it("renders a leaf with no field chosen as a placeholder", () => {
    const tree = root({ kind: "criterion", id: "c", field: "", criterion: {}, negate: false });
    expect(summarize(tree, GAME)).toBe("Games where ….");
  });

  it("renders a field chosen but no value yet as label + placeholder", () => {
    const tree = root({
      kind: "criterion",
      id: "c",
      field: "name",
      criterion: {},
      negate: false,
    });
    expect(summarize(tree, GAME)).toBe("Games where Name ….");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `direnv exec . pnpm exec vitest run ts/elements/filter-tree/summary.test.ts`
Expected: FAIL — cannot find module `./summary.js`.

- [ ] **Step 3: Write minimal implementation**

Create `ts/elements/filter-tree/summary.ts`:

```ts
/**
 * Natural-language filter summary (issue #194, phase 2c component 7 of #168).
 *
 * A pure, DOM-free tree → English walker: `summarize(tree, ctx)` turns a
 * `GroupNode` filter tree into a read-only sentence, recomputed by the builder on
 * every edit. Reads node payloads + explicit per-model `FieldMeta` metadata only;
 * the caller passes a *filled* tree (leaf payloads already read from live widgets —
 * see filter-group's fillCriteria). Mounting is component 10; this module is
 * standalone and fixture-tested, mirroring serializer.ts.
 */
import type {
  CriterionLeaf,
  FieldMeta,
  FilterNode,
  GroupNode,
} from "./types.js";
import { isCriterionComplete } from "./operations.js";

export interface SummaryModel {
  fields: Map<string, FieldMeta>;
  // Comparison column value -> label (issue #246 leaf); optional — only models that
  // admit a field comparison supply it.
  columns?: Map<string, string>;
}

export interface SummaryContext {
  modelKey: string; // root model key, e.g. "game"
  modelLabel: string; // root display noun, e.g. "Games"
  models: Record<string, SummaryModel>; // every reachable model key -> its metadata
}

// modifier token -> natural phrase. The SINGLE source the Python contract validates
// (Task 7): every key must be a real common.criteria.Modifier value.
export const MODIFIER_PHRASES: Record<string, string> = {
  EQUALS: "is",
  NOT_EQUALS: "is not",
  GREATER_THAN: "is more than",
  LESS_THAN: "is less than",
  GREATER_THAN_OR_EQUAL: "is at least",
  LESS_THAN_OR_EQUAL: "is at most",
  BETWEEN: "is between",
  NOT_BETWEEN: "is not between",
  IS_NULL: "is empty",
  NOT_NULL: "is set",
  MATCHES_REGEX: "matches",
  NOT_MATCHES_REGEX: "does not match",
  INCLUDES: "is",
  EXCLUDES: "is not",
  INCLUDES_ALL: "has all of",
  INCLUDES_ONLY: "is exactly",
};

const PLACEHOLDER = "…";

export function summarize(tree: GroupNode, ctx: SummaryContext): string {
  const model = ctx.models[ctx.modelKey];
  const body = tree.children.length ? joinChildren(tree, model, ctx) : "";
  if (!body) return `${ctx.modelLabel} (all).`;
  return `${ctx.modelLabel} where ${body}.`;
}

// Join a group's children with the group's connective word. Empty renders (empty
// nested groups) drop out.
function joinChildren(node: GroupNode, model: SummaryModel | undefined, ctx: SummaryContext): string {
  const word = node.connective === "AND" ? "and" : "or";
  const parts = node.children
    .map((child) => renderNode(child, model, ctx))
    .filter((part) => part.length > 0);
  return parts.join(` ${word} `);
}

function renderNode(node: FilterNode, model: SummaryModel | undefined, ctx: SummaryContext): string {
  switch (node.kind) {
    case "group":
      return joinChildren(node, model, ctx);
    case "criterion":
      return renderCriterion(node, model);
    default:
      return ""; // comparison + relation handled in later tasks
  }
}

function renderCriterion(leaf: CriterionLeaf, model: SummaryModel | undefined): string {
  if (!leaf.field) return PLACEHOLDER;
  const meta = model?.fields.get(leaf.field);
  const label = meta?.label ?? leaf.field;
  if (!isCriterionComplete(leaf)) return `${label} ${PLACEHOLDER}`;
  const modifier = String(leaf.criterion["modifier"]);
  const phrase = MODIFIER_PHRASES[modifier] ?? modifier;
  const value = renderValue(leaf.criterion["value"], meta);
  return `${label} ${phrase} ${value}`;
}

// Render one stored value to its display form: a choice value maps to its label; a
// {label} object (search-select set entry) uses its label; otherwise the value's
// string form. Arrays render their first item here — multi-value phrasing arrives
// with the set/list tasks.
function renderValue(value: unknown, meta: FieldMeta | undefined): string {
  const first = Array.isArray(value) ? value[0] : value;
  return renderItem(first, meta);
}

function renderItem(item: unknown, meta: FieldMeta | undefined): string {
  if (item && typeof item === "object" && "label" in item) {
    return String((item as { label: unknown }).label);
  }
  const raw = String(item);
  const choice = meta?.choices.find((candidate) => candidate.value === raw);
  return choice ? choice.label : raw;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `direnv exec . pnpm exec vitest run ts/elements/filter-tree/summary.test.ts`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add ts/elements/filter-tree/summary.ts ts/elements/filter-tree/summary.test.ts
git commit -m "feat(filters): NL summary scaffold — frame + scalar leaf (#194)"
```

---

### Task 2: All scalar modifier families + bool

**Files:**
- Modify: `ts/elements/filter-tree/summary.ts` (extend `renderCriterion`)
- Test: `ts/elements/filter-tree/summary.test.ts`

**Interfaces:**
- Consumes: `MODIFIER_PHRASES`, `renderItem` (Task 1); `isPresenceModifier`, `isRangeModifier` from `../filter-tokens.js`.
- Produces: no new exports; `renderCriterion` now handles presence (no value), range (two bounds), and bool (`kind==="bool"` → yes/no or choice labels).

- [ ] **Step 1: Write the failing test**

Append to `summary.test.ts` inside a new `describe`:

```ts
describe("summarize — modifier families", () => {
  const CTX: SummaryContext = {
    modelKey: "game",
    modelLabel: "Games",
    models: {
      game: {
        fields: new Map([
          ["name", field({ name: "name", label: "Name", kind: "string" })],
          ["playtime", field({ name: "playtime", label: "Playtime", kind: "number" })],
          ["mastered", field({ name: "mastered", label: "Mastered", kind: "bool" })],
        ]),
      },
    },
  };
  function one(field: string, criterion: Record<string, unknown>): string {
    return summarize(
      root({ kind: "criterion", id: "c", field, criterion, negate: false }),
      CTX,
    );
  }

  it("phrases NOT_EQUALS", () => {
    expect(one("name", { value: "zelda", modifier: "NOT_EQUALS" })).toBe(
      "Games where Name is not zelda.",
    );
  });
  it("phrases comparators", () => {
    expect(one("playtime", { value: "2", modifier: "GREATER_THAN_OR_EQUAL" })).toBe(
      "Games where Playtime is at least 2.",
    );
    expect(one("playtime", { value: "5", modifier: "LESS_THAN" })).toBe(
      "Games where Playtime is less than 5.",
    );
  });
  it("phrases BETWEEN with both bounds", () => {
    expect(one("playtime", { value: "2", value2: "5", modifier: "BETWEEN" })).toBe(
      "Games where Playtime is between 2 and 5.",
    );
  });
  it("phrases presence modifiers with no value", () => {
    expect(one("name", { modifier: "IS_NULL" })).toBe("Games where Name is empty.");
    expect(one("name", { modifier: "NOT_NULL" })).toBe("Games where Name is set.");
  });
  it("phrases regex modifiers", () => {
    expect(one("name", { value: "^z", modifier: "MATCHES_REGEX" })).toBe(
      "Games where Name matches ^z.",
    );
  });
  it("phrases a bool as yes/no", () => {
    expect(one("mastered", { value: true, modifier: "EQUALS" })).toBe(
      "Games where Mastered is yes.",
    );
    expect(one("mastered", { value: false, modifier: "EQUALS" })).toBe(
      "Games where Mastered is no.",
    );
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `direnv exec . pnpm exec vitest run ts/elements/filter-tree/summary.test.ts`
Expected: FAIL — BETWEEN shows only "2", presence shows a trailing value, bool shows "true"/"false".

- [ ] **Step 3: Write minimal implementation**

In `summary.ts`, add the import and replace `renderCriterion`:

```ts
import { isPresenceModifier, isRangeModifier } from "../filter-tokens.js";
```

```ts
function renderCriterion(leaf: CriterionLeaf, model: SummaryModel | undefined): string {
  if (!leaf.field) return PLACEHOLDER;
  const meta = model?.fields.get(leaf.field);
  const label = meta?.label ?? leaf.field;
  if (!isCriterionComplete(leaf)) return `${label} ${PLACEHOLDER}`;
  const modifier = String(leaf.criterion["modifier"]);
  const phrase = MODIFIER_PHRASES[modifier] ?? modifier;
  // Presence modifiers carry no value: the phrase ("is empty"/"is set") is the whole clause.
  if (isPresenceModifier(modifier)) return `${label} ${phrase}`;
  if (meta?.kind === "bool") {
    return `${label} ${phrase} ${renderBool(leaf.criterion["value"], meta)}`;
  }
  if (isRangeModifier(modifier)) {
    const lower = renderItem(leaf.criterion["value"], meta);
    const upper = renderItem(leaf.criterion["value2"], meta);
    return `${label} ${phrase} ${lower} and ${upper}`;
  }
  return `${label} ${phrase} ${renderValue(leaf.criterion["value"], meta)}`;
}

// A bool value's display: the field's matching choice label if present, else yes/no.
function renderBool(value: unknown, meta: FieldMeta | undefined): string {
  const raw = String(value);
  const choice = meta?.choices.find((candidate) => candidate.value === raw);
  if (choice) return choice.label;
  return value === true ? "yes" : "no";
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `direnv exec . pnpm exec vitest run ts/elements/filter-tree/summary.test.ts`
Expected: PASS (all Task 1 + Task 2 tests).

- [ ] **Step 5: Commit**

```bash
git add ts/elements/filter-tree/summary.ts ts/elements/filter-tree/summary.test.ts
git commit -m "feat(filters): NL summary scalar modifiers + bool (#194)"
```

---

### Task 3: Set values — include / exclude lists

**Files:**
- Modify: `ts/elements/filter-tree/summary.ts`
- Test: `ts/elements/filter-tree/summary.test.ts`

**Interfaces:**
- Consumes: `renderItem` (Task 1).
- Produces: `renderCriterion` handles `kind==="set"` payloads: `value` (included) + optional `excludes`, with one-vs-many phrasing and an appended "and not …" clause. New helper `renderList(items, meta)`.

- [ ] **Step 1: Write the failing test**

Append a `describe`:

```ts
describe("summarize — set values", () => {
  const CTX: SummaryContext = {
    modelKey: "game",
    modelLabel: "Games",
    models: {
      game: {
        fields: new Map([
          [
            "status",
            field({
              name: "status",
              label: "Status",
              kind: "set",
              choices: [
                { value: "f", label: "Finished" },
                { value: "p", label: "Playing" },
                { value: "a", label: "Abandoned" },
              ],
            }),
          ],
          ["device", field({ name: "device", label: "Device", kind: "set" })],
        ]),
      },
    },
  };
  function one(field: string, criterion: Record<string, unknown>): string {
    return summarize(root({ kind: "criterion", id: "c", field, criterion, negate: false }), CTX);
  }

  it("phrases a single-value INCLUDES as 'is'", () => {
    expect(one("status", { value: ["f"], modifier: "INCLUDES" })).toBe(
      "Games where Status is Finished.",
    );
  });
  it("phrases a multi-value INCLUDES as 'is one of'", () => {
    expect(one("status", { value: ["f", "p"], modifier: "INCLUDES" })).toBe(
      "Games where Status is one of Finished or Playing.",
    );
  });
  it("phrases EXCLUDES", () => {
    expect(one("status", { value: ["a"], modifier: "EXCLUDES" })).toBe(
      "Games where Status is not Abandoned.",
    );
  });
  it("phrases INCLUDES_ALL and INCLUDES_ONLY", () => {
    expect(one("status", { value: ["f", "p"], modifier: "INCLUDES_ALL" })).toBe(
      "Games where Status has all of Finished and Playing.",
    );
    expect(one("status", { value: ["f", "p"], modifier: "INCLUDES_ONLY" })).toBe(
      "Games where Status is exactly Finished and Playing.",
    );
  });
  it("appends an excludes clause when both present (search-select {id,label} entries)", () => {
    expect(
      one("device", {
        value: [{ id: "1", label: "Steam Deck" }],
        excludes: [{ id: "2", label: "Switch" }],
        modifier: "INCLUDES",
      }),
    ).toBe("Games where Device is Steam Deck and not Switch.");
  });
  it("phrases an excludes-only set as 'is not'", () => {
    expect(
      one("device", { value: [], excludes: [{ id: "2", label: "Switch" }], modifier: "INCLUDES" }),
    ).toBe("Games where Device is not Switch.");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `direnv exec . pnpm exec vitest run ts/elements/filter-tree/summary.test.ts`
Expected: FAIL — multi-value renders only the first item; excludes ignored.

- [ ] **Step 3: Write minimal implementation**

Sets need a completeness gate distinct from `isCriterionComplete`: an **excludes-only** set has `value: []` (which `isValuePresent` rejects) yet is a meaningful filter. So handle the set kind *before* the scalar `isCriterionComplete` gate, with its own `setHasSelection` check. Replace `renderCriterion` in `summary.ts`:

```ts
function renderCriterion(leaf: CriterionLeaf, model: SummaryModel | undefined): string {
  if (!leaf.field) return PLACEHOLDER;
  const meta = model?.fields.get(leaf.field);
  const label = meta?.label ?? leaf.field;
  const modifier = String(leaf.criterion["modifier"] ?? "");
  // Sets gate on include-OR-exclude presence, not isCriterionComplete (which only
  // inspects `value` and would call an excludes-only set incomplete).
  if (meta?.kind === "set") {
    if (!setHasSelection(leaf.criterion, modifier)) return `${label} ${PLACEHOLDER}`;
    if (isPresenceModifier(modifier)) return `${label} ${MODIFIER_PHRASES[modifier] ?? modifier}`;
    return `${label} ${renderSet(leaf.criterion, meta, modifier)}`;
  }
  if (!isCriterionComplete(leaf)) return `${label} ${PLACEHOLDER}`;
  const phrase = MODIFIER_PHRASES[modifier] ?? modifier;
  if (isPresenceModifier(modifier)) return `${label} ${phrase}`;
  if (meta?.kind === "bool") {
    return `${label} ${phrase} ${renderBool(leaf.criterion["value"], meta)}`;
  }
  if (isRangeModifier(modifier)) {
    const lower = renderItem(leaf.criterion["value"], meta);
    const upper = renderItem(leaf.criterion["value2"], meta);
    return `${label} ${phrase} ${lower} and ${upper}`;
  }
  return `${label} ${phrase} ${renderValue(leaf.criterion["value"], meta)}`;
}

// A set is worth rendering once it has a modifier and any selection (included,
// excluded, or a presence test). Mirrors buildSetCriterion's "included OR excluded"
// non-null condition rather than isCriterionComplete's value-only check.
function setHasSelection(criterion: CriterionLeaf["criterion"], modifier: string): boolean {
  if (!modifier) return false;
  if (isPresenceModifier(modifier)) return true;
  const value = criterion["value"];
  const excludes = criterion["excludes"];
  return (
    (Array.isArray(value) && value.length > 0) ||
    (Array.isArray(excludes) && excludes.length > 0)
  );
}
```

Add helpers. `*_ALL`/`*_ONLY` join their values with "and" (all required); `INCLUDES`/`EXCLUDES` join with "or" (any allowed), so the conjunction is chosen per modifier and threaded into `joinWords`:

```ts
// Render a set criterion's predicate (everything after the field label): the
// included values phrased per modifier, with an appended "and not …" for excludes.
function renderSet(
  criterion: CriterionLeaf["criterion"],
  meta: FieldMeta,
  modifier: string,
): string {
  const conjunction = modifier === "INCLUDES_ALL" || modifier === "INCLUDES_ONLY" ? "and" : "or";
  const included = renderList(criterion["value"], meta, conjunction);
  const excluded = renderList(criterion["excludes"], meta, "or");
  const clauses: string[] = [];
  if (included.items.length) {
    clauses.push(`${includePhrase(modifier, included.items.length)} ${included.text}`);
  }
  if (excluded.items.length) {
    // "is not X" on its own when there is no include clause; else "and not X".
    clauses.push(clauses.length ? `and not ${excluded.text}` : `is not ${excluded.text}`);
  }
  return clauses.join(" ");
}

// The verb for an included list: INCLUDES → is / is one of; the *_ALL/_ONLY forms
// keep their MODIFIER_PHRASES phrasing; EXCLUDES on the include slot → is not / is none of.
function includePhrase(modifier: string, count: number): string {
  if (modifier === "INCLUDES") return count > 1 ? "is one of" : "is";
  if (modifier === "EXCLUDES") return count > 1 ? "is none of" : "is not";
  return MODIFIER_PHRASES[modifier] ?? modifier;
}

interface RenderedList {
  items: string[];
  text: string; // items joined "a, b <conjunction> c"
}

function renderList(value: unknown, meta: FieldMeta, conjunction: string): RenderedList {
  const raw = Array.isArray(value) ? value : value == null ? [] : [value];
  const items = raw.map((item) => renderItem(item, meta));
  return { items, text: joinWords(items, conjunction) };
}

// Join a display list: "a", "a and b", "a, b or c" — final conjunction chosen by
// the caller ("or" for a disjunction of allowed values, "and" for required sets).
function joinWords(items: string[], conjunction: string): string {
  if (items.length <= 1) return items.join("");
  if (items.length === 2) return `${items[0]} ${conjunction} ${items[1]}`;
  return `${items.slice(0, -1).join(", ")} ${conjunction} ${items[items.length - 1]}`;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `direnv exec . pnpm exec vitest run ts/elements/filter-tree/summary.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ts/elements/filter-tree/summary.ts ts/elements/filter-tree/summary.test.ts
git commit -m "feat(filters): NL summary set include/exclude phrasing (#194)"
```

---

### Task 4: Connectives, parenthesization, NOT

**Files:**
- Modify: `ts/elements/filter-tree/summary.ts` (`joinChildren`, `renderNode`)
- Test: `ts/elements/filter-tree/summary.test.ts`

**Interfaces:**
- Produces: nested groups parenthesized when they have >1 child or a differing connective; `negate` on any node renders `not (…)`. New helper `renderChildForGroup`.

- [ ] **Step 1: Write the failing test**

Append a `describe`. Reuse the two-field `GAME`-style context (define a local one with `status` + `platform`):

```ts
describe("summarize — connectives, parens, NOT", () => {
  const CTX: SummaryContext = {
    modelKey: "game",
    modelLabel: "Games",
    models: {
      game: {
        fields: new Map([
          [
            "status",
            field({
              name: "status",
              label: "Status",
              kind: "set",
              choices: [
                { value: "f", label: "Finished" },
                { value: "p", label: "Playing" },
              ],
            }),
          ],
          [
            "platform",
            field({
              name: "platform",
              label: "Platform",
              kind: "set",
              choices: [
                { value: "pc", label: "PC" },
                { value: "sw", label: "Switch" },
              ],
            }),
          ],
        ]),
      },
    },
  };
  const finished = { kind: "criterion", id: "a", field: "status", criterion: { value: ["f"], modifier: "INCLUDES" }, negate: false } as const;
  const pc = { kind: "criterion", id: "b", field: "platform", criterion: { value: ["pc"], modifier: "INCLUDES" }, negate: false } as const;
  const sw = { kind: "criterion", id: "c", field: "platform", criterion: { value: ["sw"], modifier: "INCLUDES" }, negate: false } as const;

  it("joins two AND leaves", () => {
    expect(summarize(root(finished, pc), CTX)).toBe(
      "Games where Status is Finished and Platform is PC.",
    );
  });
  it("parenthesizes a differing-connective child group", () => {
    const orGroup: GroupNode = { kind: "group", id: "or", connective: "OR", negate: false, children: [pc, sw] };
    expect(summarize(root(finished, orGroup), CTX)).toBe(
      "Games where Status is Finished and (Platform is PC or Platform is Switch).",
    );
  });
  it("does not parenthesize a same-connective single-child group", () => {
    const andGroup: GroupNode = { kind: "group", id: "in", connective: "AND", negate: false, children: [pc] };
    expect(summarize(root(finished, andGroup), CTX)).toBe(
      "Games where Status is Finished and Platform is PC.",
    );
  });
  it("prefixes a negated leaf with not (…)", () => {
    expect(summarize(root({ ...finished, negate: true }), CTX)).toBe(
      "Games where not (Status is Finished).",
    );
  });
  it("prefixes a negated group with not (…)", () => {
    const orGroup: GroupNode = { kind: "group", id: "or", connective: "OR", negate: true, children: [pc, sw] };
    expect(summarize(root(orGroup), CTX)).toBe(
      "Games where not (Platform is PC or Platform is Switch).",
    );
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `direnv exec . pnpm exec vitest run ts/elements/filter-tree/summary.test.ts`
Expected: FAIL — no parens, no `not (…)`.

- [ ] **Step 3: Write minimal implementation**

Replace `joinChildren` and `renderNode` in `summary.ts`:

```ts
function joinChildren(node: GroupNode, model: SummaryModel | undefined, ctx: SummaryContext): string {
  const word = node.connective === "AND" ? "and" : "or";
  const parts = node.children
    .map((child) => renderChildForGroup(child, node.connective, model, ctx))
    .filter((part) => part.length > 0);
  return parts.join(` ${word} `);
}

// A child rendered for placement inside a group: wrap a non-negated nested group in
// parens when it has >1 child or a connective differing from its parent's (a
// negated group already parenthesizes itself via renderNode).
function renderChildForGroup(
  child: FilterNode,
  parentConnective: GroupNode["connective"],
  model: SummaryModel | undefined,
  ctx: SummaryContext,
): string {
  const rendered = renderNode(child, model, ctx);
  if (child.kind === "group" && !child.negate && rendered.length > 0) {
    const needsParens = child.children.length > 1 || child.connective !== parentConnective;
    if (needsParens) return `(${rendered})`;
  }
  return rendered;
}

function renderNode(node: FilterNode, model: SummaryModel | undefined, ctx: SummaryContext): string {
  const inner = renderInner(node, model, ctx);
  if (!inner) return "";
  return node.negate ? `not (${inner})` : inner;
}

function renderInner(node: FilterNode, model: SummaryModel | undefined, ctx: SummaryContext): string {
  switch (node.kind) {
    case "group":
      return joinChildren(node, model, ctx);
    case "criterion":
      return renderCriterion(node, model);
    default:
      return ""; // comparison + relation handled in later tasks
  }
}
```

Note: `renderCriterion` no longer applies negate itself (it never did) — `renderNode` owns it. Confirm `renderCriterion` returns just the clause.

- [ ] **Step 4: Run test to verify it passes**

Run: `direnv exec . pnpm exec vitest run ts/elements/filter-tree/summary.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ts/elements/filter-tree/summary.ts ts/elements/filter-tree/summary.test.ts
git commit -m "feat(filters): NL summary connectives, parens, NOT (#194)"
```

---

### Task 5: Relation descent

**Files:**
- Modify: `ts/elements/filter-tree/summary.ts` (`renderInner`, add `renderRelation`)
- Test: `ts/elements/filter-tree/summary.test.ts`

**Interfaces:**
- Consumes: `RelationNode`, `RelationMatch` from `./types.js`.
- Produces: `renderInner` handles `kind==="relation"` — quantifier + relation label + "where <child-body>", switching to the target model's fields; empty child → per-quantifier presence phrasing; unset relation field → placeholder. New helpers `renderRelation`, `targetModelKey`, `emptyRelationPhrase`.

- [ ] **Step 1: Write the failing test**

Append a `describe`:

```ts
describe("summarize — relation descent", () => {
  const CTX: SummaryContext = {
    modelKey: "game",
    modelLabel: "Games",
    models: {
      game: {
        fields: new Map([
          [
            "session_filter",
            field({
              name: "session_filter",
              label: "Sessions",
              kind: "relation",
              relations: [{ field: "session_filter", filter: "SessionFilter", model: "Session" }],
            }),
          ],
        ]),
      },
      session: {
        fields: new Map([
          ["device", field({ name: "device", label: "Device", kind: "set" })],
        ]),
      },
    },
  };
  function relation(match: "ANY" | "NONE" | "ALL", childChildren: GroupNode["children"], negate = false): GroupNode {
    return root({
      kind: "relation",
      id: "r",
      field: "session_filter",
      match,
      negate,
      child: { kind: "group", id: "rc", connective: "AND", negate: false, children: childChildren },
    });
  }
  const deviceHandheld = { kind: "criterion", id: "d", field: "device", criterion: { value: [{ id: "1", label: "Handheld" }], modifier: "INCLUDES" }, negate: false } as const;

  it("phrases ANY with a child body under the target model", () => {
    expect(summarize(relation("ANY", [deviceHandheld]), CTX)).toBe(
      "Games where any sessions where Device is Handheld.",
    );
  });
  it("phrases NONE and ALL quantifiers", () => {
    expect(summarize(relation("NONE", [deviceHandheld]), CTX)).toBe(
      "Games where no sessions where Device is Handheld.",
    );
    expect(summarize(relation("ALL", [deviceHandheld]), CTX)).toBe(
      "Games where every sessions where Device is Handheld.",
    );
  });
  it("phrases an empty ANY child as a presence test", () => {
    expect(summarize(relation("ANY", []), CTX)).toBe(
      "Games where has related sessions.",
    );
  });
  it("phrases an empty NONE child as a no-related test", () => {
    expect(summarize(relation("NONE", []), CTX)).toBe(
      "Games where has no related sessions.",
    );
  });
  it("negates a relation descent", () => {
    expect(summarize(relation("ANY", [deviceHandheld], true), CTX)).toBe(
      "Games where not (any sessions where Device is Handheld).",
    );
  });
  it("renders an unset relation field as a placeholder", () => {
    const tree = root({
      kind: "relation",
      id: "r",
      field: "",
      match: "ANY",
      negate: false,
      child: { kind: "group", id: "rc", connective: "AND", negate: false, children: [] },
    });
    expect(summarize(tree, CTX)).toBe("Games where ….");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `direnv exec . pnpm exec vitest run ts/elements/filter-tree/summary.test.ts`
Expected: FAIL — relation renders "" so the frame collapses to "(all)".

- [ ] **Step 3: Write minimal implementation**

Add the import and a `RelationNode` case. Update the import line:

```ts
import type {
  CriterionLeaf,
  FieldMeta,
  FilterNode,
  GroupNode,
  RelationMatch,
  RelationNode,
} from "./types.js";
```

In `renderInner`, replace the `default` with explicit cases:

```ts
    case "relation":
      return renderRelation(node, model, ctx);
    default:
      return ""; // comparison handled in Task 6
```

Add helpers:

```ts
const QUANTIFIERS: Record<RelationMatch, string> = { ANY: "any", NONE: "no", ALL: "every" };

function renderRelation(node: RelationNode, model: SummaryModel | undefined, ctx: SummaryContext): string {
  if (!node.field) return PLACEHOLDER;
  const meta = model?.fields.get(node.field);
  const noun = (meta?.label ?? node.field).toLowerCase();
  const targetKey = targetModelKey(meta, ctx);
  const targetModel = ctx.models[targetKey];
  const body = node.child.children.length ? joinChildren(node.child, targetModel, ctx) : "";
  if (!body) return emptyRelationPhrase(node.match, noun);
  return `${QUANTIFIERS[node.match]} ${noun} where ${body}`;
}

// The model key a relation descends into — its RelationTarget.model lower-cased,
// mirroring filter-group's targetModel. Falls back to the root when unknown.
function targetModelKey(meta: FieldMeta | undefined, ctx: SummaryContext): string {
  return meta?.relations[0]?.model?.toLowerCase() ?? ctx.modelKey;
}

// What an empty relation child matches, per quantifier — the presence test (#225),
// model-agnostic beyond the relation noun.
function emptyRelationPhrase(match: RelationMatch, noun: string): string {
  switch (match) {
    case "ANY":
      return `has related ${noun}`;
    case "NONE":
      return `has no related ${noun}`;
    case "ALL":
      return "matches all";
  }
  const unreachable: never = match;
  return unreachable;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `direnv exec . pnpm exec vitest run ts/elements/filter-tree/summary.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ts/elements/filter-tree/summary.ts ts/elements/filter-tree/summary.test.ts
git commit -m "feat(filters): NL summary relation descent (#194)"
```

---

### Task 6: Field-comparison leaf

**Files:**
- Modify: `ts/elements/filter-tree/summary.ts` (`renderInner`, add `renderComparison`)
- Test: `ts/elements/filter-tree/summary.test.ts`

**Interfaces:**
- Consumes: `ComparisonLeaf` from `./types.js`; `isComparisonComplete` from `./operations.js`; `SummaryModel.columns`.
- Produces: `renderInner` handles `kind==="comparison"` — `"<leftLabel> <phrase> <rightLabel>"` with an optional "(by day)" when `granularity==="date"`; incomplete → placeholder.

- [ ] **Step 1: Write the failing test**

Append a `describe`:

```ts
describe("summarize — field comparison", () => {
  const CTX: SummaryContext = {
    modelKey: "game",
    modelLabel: "Games",
    models: {
      game: {
        fields: new Map(),
        columns: new Map([
          ["year_released", "Release year"],
          ["original_year_released", "Original release year"],
        ]),
      },
    },
  };
  function comparison(payload: Record<string, unknown>): string {
    return summarize(
      root({ kind: "comparison", id: "cmp", comparison: payload, negate: false }),
      CTX,
    );
  }

  it("phrases a complete comparison with column labels", () => {
    expect(
      comparison({ left: "original_year_released", right: "year_released", modifier: "LESS_THAN" }),
    ).toBe("Games where Original release year is less than Release year.");
  });
  it("appends (by day) for date granularity", () => {
    expect(
      comparison({ left: "year_released", right: "original_year_released", modifier: "EQUALS", granularity: "date" }),
    ).toBe("Games where Release year is Original release year (by day).");
  });
  it("renders an incomplete comparison as a placeholder", () => {
    expect(comparison({ left: "year_released" })).toBe("Games where ….");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `direnv exec . pnpm exec vitest run ts/elements/filter-tree/summary.test.ts`
Expected: FAIL — comparison renders "".

- [ ] **Step 3: Write minimal implementation**

Update the import and add the case + helper:

```ts
import type {
  ComparisonLeaf,
  CriterionLeaf,
  FieldMeta,
  FilterNode,
  GroupNode,
  RelationMatch,
  RelationNode,
} from "./types.js";
import { isComparisonComplete, isCriterionComplete } from "./operations.js";
```

In `renderInner`, add before the `default`:

```ts
    case "comparison":
      return renderComparison(node, model);
```

Add:

```ts
function renderComparison(leaf: ComparisonLeaf, model: SummaryModel | undefined): string {
  if (!isComparisonComplete(leaf)) return PLACEHOLDER;
  const { left, right, modifier, granularity } = leaf.comparison;
  const leftLabel = model?.columns?.get(left as string) ?? String(left);
  const rightLabel = model?.columns?.get(right as string) ?? String(right);
  const phrase = MODIFIER_PHRASES[modifier as string] ?? String(modifier);
  const suffix = granularity === "date" ? " (by day)" : "";
  return `${leftLabel} ${phrase} ${rightLabel}${suffix}`;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `direnv exec . pnpm exec vitest run ts/elements/filter-tree/summary.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ts/elements/filter-tree/summary.ts ts/elements/filter-tree/summary.test.ts
git commit -m "feat(filters): NL summary field-comparison leaf (#194)"
```

---

### Task 7: Canonical artifact + Python modifier contract

**Files:**
- Modify: `ts/elements/filter-tree/summary.test.ts` (emit the artifact)
- Modify: `.gitignore`
- Create: `tests/test_summary_modifier_contract.py`

**Interfaces:**
- Consumes: `MODIFIER_PHRASES` (Task 1); `common.criteria.Modifier`.
- Produces: `ts/elements/filter-tree/summary-modifiers.canonical.json` = the sorted list of `MODIFIER_PHRASES` keys; a pytest asserting each is a real `Modifier`.

- [ ] **Step 1: Add the .gitignore entry**

Add to `.gitignore` (near the existing `filter-tokens.canonical.json` line):

```
/ts/elements/filter-tree/summary-modifiers.canonical.json
```

- [ ] **Step 2: Add the artifact-emitting vitest case**

Append to `summary.test.ts`:

```ts
import { writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { MODIFIER_PHRASES } from "./summary.js";

describe("summary modifier contract artifact", () => {
  it("writes the canonical modifier list for the Python contract", () => {
    const keys = Object.keys(MODIFIER_PHRASES).sort();
    const canonicalPath = fileURLToPath(
      new URL("./summary-modifiers.canonical.json", import.meta.url),
    );
    writeFileSync(canonicalPath, JSON.stringify(keys, null, 2));
    expect(keys.length).toBeGreaterThan(0);
  });
});
```

(Adjust the existing top-of-file `import { summarize, type SummaryContext } from "./summary.js";` to also import `MODIFIER_PHRASES`, or keep this separate import — both resolve.)

- [ ] **Step 3: Run vitest to emit the artifact**

Run: `direnv exec . pnpm exec vitest run ts/elements/filter-tree/summary.test.ts`
Expected: PASS; `ts/elements/filter-tree/summary-modifiers.canonical.json` now exists.

- [ ] **Step 4: Write the failing Python contract**

Create `tests/test_summary_modifier_contract.py`:

```python
"""Cross-language contract for the NL filter summary's modifier phrasing (#194).

The vitest suite emits summary-modifiers.canonical.json = the keys of the
``MODIFIER_PHRASES`` map in ts/elements/filter-tree/summary.ts. This test asserts
every key is a real ``common.criteria.Modifier`` value, so a renamed/removed Python
modifier fails CI instead of orphaning a phrase (the #141 failure mode). Mirrors
tests/test_filter_tokens_contract.py.

Skipped if the artifact is missing (run ``make test-ts`` first); ``make check``
orders test-ts before pytest so the gate always sees fresh output.
"""

import json
import os
from pathlib import Path

import pytest

from common.criteria import Modifier

CANONICAL_PATH = (
    Path(__file__).resolve().parent.parent
    / "ts"
    / "elements"
    / "filter-tree"
    / "summary-modifiers.canonical.json"
)

MODIFIER_VALUES = {modifier.value for modifier in Modifier}


def test_canonical_artifact_present_under_ci():
    if os.environ.get("CI"):
        assert CANONICAL_PATH.exists(), (
            "summary-modifiers.canonical.json missing under CI — `make test-ts` "
            "must run before pytest"
        )


@pytest.mark.skipif(
    not CANONICAL_PATH.exists(),
    reason="summary-modifiers.canonical.json missing — run `make test-ts` first",
)
def test_summary_modifier_keys_are_real_modifiers():
    keys = json.loads(CANONICAL_PATH.read_text())
    assert keys, "no modifier keys emitted — the TS artifact is empty"
    for key in keys:
        assert key in MODIFIER_VALUES, (
            f"MODIFIER_PHRASES key {key!r} is not a common.criteria.Modifier value "
            "— the summary phrase map drifted from the Python enum (#194)"
        )
```

- [ ] **Step 5: Run the contract test**

Run: `direnv exec . uv run pytest tests/test_summary_modifier_contract.py -v`
Expected: PASS (both tests; the artifact exists from Step 3).

- [ ] **Step 6: Commit**

```bash
git add .gitignore ts/elements/filter-tree/summary.test.ts tests/test_summary_modifier_contract.py
git commit -m "test(filters): NL summary modifier contract (#194)"
```

---

### Task 8: Full verification gate

**Files:** none (verification only).

- [ ] **Step 1: Run the full check suite**

Run: `direnv exec . make check`
Expected: PASS — lint, format-check, mypy, ts-check (type-checks `summary.ts` + `summary.test.ts` via `tsconfig.check.json`), icon drift, vitest (all `summary.test.ts` cases + artifact emit), and the full pytest suite incl. `tests/test_summary_modifier_contract.py` and `e2e/`.

- [ ] **Step 2: If anything fails, fix and re-run**

Common failures and fixes:
- `ts-check` unused-import / `never` exhaustiveness → remove unused imports; ensure the `emptyRelationPhrase` switch covers every `RelationMatch`.
- `format-check` → run `direnv exec . uv run ruff format` for the Python test; TS formatting is handled by the repo's formatter if configured (match surrounding style).
- pytest contract skipped (artifact absent) → ensure Step 3/Task 7 ran; `make check` orders `test-ts` before `test`, so a full `make check` regenerates it.

- [ ] **Step 3: Commit any fixes**

```bash
git add -A
git commit -m "chore(filters): satisfy check gate for NL summary (#194)"
```

---

## Self-review notes

- **Spec coverage:** frame (T1) · scalar modifiers + bool (T2) · sets (T3) · connectives/parens/NOT (T4) · relations + empty-child presence (T5) · comparison (T6, a small documented superset — spec omitted comparison phrasing; added with `SummaryModel.columns`) · incomplete placeholders (folded into T1/T5/T6) · contract (T7) · pure/DOM-free (all) · no page wiring (none).
- **Deviation flagged:** `SummaryModel.columns` (comparison labels) is not in the spec's API block; it is the minimal addition needed to render field-comparison leaves readably. If undesired, drop Task 6 and render comparisons as "" — but the tree can contain them, so rendering them is the correct call.
- **Type consistency:** `SummaryModel`/`SummaryContext`/`summarize`/`MODIFIER_PHRASES` names are stable across all tasks; `renderNode` owns negation, `renderInner` dispatches by kind, `renderCriterion`/`renderSet`/`renderRelation`/`renderComparison` return the bare clause.
