# Recursive Tree Serializer/Deserializer — Design

**Issue:** #188 (component 6, phase 2c of #168, roadmap epic #171)
**Status:** Design — adversarial-reviewed (3 agents vs. real backend), corrections folded.
**Date:** 2026-06-29
**Parent design:** `2026-06-28-nested-filter-builder-design.md`; review:
`2026-06-28-nested-filter-builder-adversarial-review.md`.

## Context

Component 6 is the **foundational** TS module of the nested filter builder: a node
tree ↔ `OperatorFilter` JSON serializer/deserializer. It blocks components 1–5, 7, 8
(group shell #189, connective/negate, field picker, leaf widgets, relation picker, NL
summary, live count). The `OperatorFilter` algebra (`common/criteria.py`) already
supports arbitrary nesting; what is missing is the client-side tree model plus a
recursive serializer that produces canonical JSON and a deserializer that imports
arbitrary/legacy JSON faithfully.

This module is built and unit-tested **in isolation**. It does **not** touch
`ts/elements/filter-bar.ts`; see Scope / non-goals.

## Scope / non-goals

**In scope:** `filter-tree/types.ts` (node union + metadata interface),
`filter-tree/serializer.ts` (`serialize`/`deserialize`), vitest unit tests, a shared
`fixtures.json`, a Python contract test, and the build wiring (vitest + a `make
test-ts` target).

**Out of scope (tracked elsewhere):**

- Ripping out the flat `filter-bar.ts` `setPath`/`appendAnd`/`readWidget` glue. The
  advanced builder is a **separate** `/…/filter` page; the flat list-page bar survives
  this PR. Its removal is owned by **#197** (quick filter bar replaces it) and **#201**
  (remove the `TODO(nested-builder, #168)` scaffolding at `filter-bar.ts:265`,
  `common/components/filters.py:604/676`).
- Leaf **widget** rendering / value editing — component 4 (leaf widgets). This module
  treats criterion/comparison payloads as **opaque** dicts (below).
- The group-shell UI, NL summary, live count — their own 2c issues. They `import` the
  node types defined here.

## Module layout

```
ts/elements/filter-tree/
  types.ts           # node union + metadata interface (the dependency hub for #189+)
  serializer.ts      # serialize() / deserialize()
  serializer.test.ts # vitest unit tests (NOT compiled into dist — see Build wiring)
  fixtures.json      # shared canonical cases (vitest + Python both read)
tests/test_filter_tree_contract.py   # Python: feeds fixtures through filter_from_json → to_q
```

Types live in their own module (not inside `serializer.ts`): every downstream component
imports `types.ts`; nothing imports another component's logic. The discriminated union
is the contract the whole builder switches on.

## Node model (`types.ts`)

```ts
export type Connective = "AND" | "OR";
export type RelationMatch = "ANY" | "NONE" | "ALL";

// Opaque to the serializer: whatever the leaf widget produced
// ({value, modifier, value2?} | {modifier} presence | set shape | bool | …).
export type CriterionPayload = Record<string, unknown>;

export interface GroupNode {
  kind: "group";
  connective: Connective;        // negation is NOT a connective — see Negation
  negate: boolean;
  children: FilterNode[];
}
export interface CriterionLeaf {
  kind: "criterion";
  field: string;                 // e.g. "status", "year_released", "search"
  criterion: CriterionPayload;
  negate: boolean;
}
export interface ComparisonLeaf {
  kind: "comparison";
  comparison: Record<string, unknown>;  // {left, right, modifier, granularity?}
  negate: boolean;
}
export interface RelationNode {
  kind: "relation";
  field: string;                 // e.g. "session_filter"
  match: RelationMatch;
  child: GroupNode;              // exactly one canonical group (invariant)
  negate: boolean;
}
export type FilterNode = GroupNode | CriterionLeaf | ComparisonLeaf | RelationNode;
```

The **root is always a `GroupNode`** (the builder seeds an `AND` root).

### Payloads are opaque — and client-origin

`serialize`/`deserialize` never inspect a criterion/comparison payload; they pass the
dict through. This keeps the module independent of per-type criterion shapes. The
correctness contract is **`to_q()` equivalence**, and a payload's ids — not its labels
— determine `to_q`, so opacity is sound for querying.

**Constraint (adversarial finding B-D1):** the backend's own `to_json` does **not**
reproduce the widget payload — `_SetCriterion.from_json` strips `{id,label}` pills to
bare ids and re-types them to int (`criteria.py:194-202,564-576`), and the base
`to_json` drops a field whose value equals its default (`criteria.py:263`). So the
builder must replay **client-origin** JSON (the `save_preset` path stores raw client
JSON verbatim, `filter_presets.py:137`), and must **not** ingest a
`filter_to_json`-produced filter (stat links, programmatic) without a server-side
label/id re-resolution step. That re-resolution is a **builder/#196 concern**, not this
module's: `to_q` is unaffected because labels do not change the query.

## Metadata interface (import dependency)

Import must classify each dict key. Reserved keys (`AND`, `OR`, `NOT`, `match`,
`field_comparisons`) are handled structurally. For the rest, the deserializer needs to
know, **per model**, which names are relation sub-filters (and their target model) and
which are valid criterion fields:

```ts
export interface ModelMeta {
  fields: ReadonlySet<string>;           // valid criterion field names (incl. "search")
  relations: Record<string, string>;    // relationField -> targetModelKey
}
export type MetadataRegistry = Record<string, ModelMeta>;  // modelKey -> meta
```

`deserialize(dict, modelKey, registry)` uses `registry[modelKey]`. A relation key
recurses into `registry[relations[key]]`. **Including `fields` is required** (finding
C-D4): the backend `from_json` iterates only declared dataclass fields and **silently
drops unknown keys** (`criteria.py:1233-1234`); the importer mirrors this **fail-drop**
(a typo or a registry-missing relation is dropped, not promoted to a phantom leaf) so
the tree matches exactly what the backend will evaluate.

**Data source (decision, finding C-D9 + repo norm):** this registry must be
**codegen'd from the server `field_metadata()`** registry (#187, `criteria.py:1729`),
exposed to TS as part of **#152** — never hand-maintained (it would drift from the six
filter classes in `games/filters.py`). #188 defines the TS **interface** and injects
**fixture** registries in tests; #196 (builder page) wires the real codegen'd registry.
The full `field_metadata` (`{label, kind, nullable, choices}`) is consumed by the leaf
**widgets** (component 4); the serializer needs only `fields` + `relations`.

## Export — `serialize(root: GroupNode): dict`

Canonical, recursive per node. Each node serializes to a **single-key dict** (never a
mixed node), so a group's children are always single-key dicts.

- **group** → `inner = {[connective]: children.map(serialize).filter(nonEmpty)}`; if the
  filtered child list is empty, `inner = {}`. A `negate` group wraps to `{NOT:[inner]}`
  **unless** `inner` is `{}` (an empty group is identity regardless of negate → stays
  `{}`). Empty children are dropped from the parent's list by `filter(nonEmpty)`.
- **criterion leaf** → `{[field]: criterion}`; `negate` → `{NOT:[{[field]: criterion}]}`.
- **comparison leaf** → `{field_comparisons: [comparison]}`; `negate` wraps it.
- **relation node** → `relDict = {…(match≠ANY ? {match} : {}), …serialize(child)}`, then
  `{[field]: relDict}`; `negate` wraps the whole `{[field]: relDict}`.

**Empty-group drop is scoped to operator groups only (finding C-D3 / A-LOW).** A
relation node always serializes to a non-empty `{[field]: relDict}` and is **never**
dropped — even when its child group is empty. An empty relation child is a *feature*:
`{session_filter:{}}` (ANY) = "has ≥1 related row"; `{session_filter:{match:"NONE"}}` =
"has 0 related rows" (`relation_to_q`, `criteria.py:1986-1995`). The empty-drop rule
only removes empty-dict **children from a group's child list**; it never reaches inside
a relation node.

An empty root serializes to `{}` (not `{AND:[]}`), matching the backend's `to_json`
omission of empty operator lists (`criteria.py:1340-1342`).

Each comparison is its **own leaf** and exports as its own `{field_comparisons:[c]}`
sibling under the enclosing group — never collapsed into one N-element array (decision
C-D7; both are `to_q`-equivalent, the homogeneous tree models one comparison per leaf).

## Import — `deserialize(dict, modelKey, registry): GroupNode`

Reproduces the backend's **exact left-to-right fold**, which is *not* a clean boolean
tree. `to_q` (`criteria.py:1205-1211`) folds own criteria + `_extra_q()` (relations,
M2M, `search`) with `&`, then `_apply_operators` (`criteria.py:1159-1194`) applies, in
fixed order: each `AND` (`&=`), each `OR` (`|=`), each `NOT` (`&= ~`), then
**`field_comparisons` last as an outermost `&=`**.

So the true precedence is **criteria → AND → OR → NOT → field_comparisons** — and
field_comparisons sit at a *different precedence than own criteria* (finding A1, HIGH).
For a node with own/relation/AND part `C`, OR-subs `O`, NOT-subs `N`, comparisons `K`:
the meaning is **`((C | O) & ~N) & K`** — not `(C & K) | O`.

### Algorithm

For a dict `D` at model `M`, depth `d`:

1. **Base `C`** = `AND[`
   - each non-reserved key in `M.fields` → `CriterionLeaf`,
   - each non-reserved key in `M.relations` → `RelationNode{field, match: D[key].match ?? ANY,
     child: asGroup(deserialize(D[key] minus match, targetModel, registry, d+1))}`,
   - each `AND`-sub → `deserialize(sub, M, registry, d+1)`,
   - *(unknown keys dropped)* `]`.
2. **OR**: if `D.OR` non-empty → `afterOr = OR[ C (if non-empty), …D.OR.map(deserialize @ d+1) ]`;
   else `afterOr = C`.
3. **Tail**: `tail = D.NOT.map(n => withNegateToggled(deserialize(n, M, registry, d+1)))
   ++ D.field_comparisons.map(c => ComparisonLeaf{c})`. If `tail` non-empty →
   `result = AND[ afterOr (if non-empty), …tail ]`; else `result = afterOr`.
4. **Collapse**: a single-child `AND`/`OR` group → its child (the child keeps its own
   `negate`). An empty group is identity and is dropped from any parent list / OR set
   (relies on the verified Django absorption `Q() | Q(x) == Q(x)`).
5. **Root/child wrap** (`asGroup`): if `result` is a bare leaf/relation, wrap it in an
   `AND` `GroupNode`. The top-level `deserialize` and every relation child use `asGroup`
   so `RelationNode.child: GroupNode` and "root is a group" both hold.

`match` is read from the sub-filter dict (where the backend reads it,
`criteria.py:1238-1243`), never the parent; at the top level any `match` key is ignored.

### Negation is a composable node property (finding A2)

`negate` is a flag on the **returned node**, toggled (not pushed down as a De-Morgan
parameter). `withNegateToggled(node) = {…node, negate: !node.negate}`. Because `serialize`
wraps any `negate` node's whole dict in `{NOT:[…]}`, toggling the returned node's flag is
exactly "negate this node". This makes `~~x = x` cancel and needs **no De Morgan**:
`{NOT:[{OR:[a,b]}]}` → an `OR[a,b]` node with `negate` set → exports `{NOT:[{OR:[a,b]}]}`
= `~(a∨b)`. A leaf "is-not" via the criterion modifier (`NOT_EQUALS`, `EXCLUDES`) remains
a second, harmless route; "canonical" here means **structural** (one connective key per
group, single-key children, no mixed nodes) — it does **not** unify modifier-vs-`¬`
(decision C-D8).

### Depth/breadth guard (finding C-D6)

`deserialize` mirrors the backend caps: `MAX_FILTER_DEPTH = 10` (raise past it),
`MAX_FILTER_BREADTH = 100` per operator list, `MAX_FIELD_COMPARISONS = 100`
(`criteria.py:786-803`). Depth increments at the two recursion sites the backend
increments — the `AND`/`OR`/`NOT` operator lists and the relation descent (relation child
= **+1**). JSON is finite so a cyclic `game→session→game` relation cannot infinite-loop
(a depth counter, not a visited set, suffices); the cap prevents a JS-stack blow and
keeps builder/backend validity in agreement.

### Worked import cases (become fixtures)

| input dict | normalized tree | `to_q` meaning |
|---|---|---|
| `{name, OR:[o1,o2]}` | `OR[name, o1, o2]` | `name ∨ o1 ∨ o2` |
| `{OR:[o1], NOT:[n1]}` | `AND[o1, n1¬]` | `o1 ∧ ¬n1` |
| `{name, OR:[a], field_comparisons:[K]}` | `AND[ OR[name,a], Kcmp ]` | `(name ∨ a) ∧ K` |
| `{year_released, search, AND:[{session_filter:{…}}]}` | `AND[year_released, search, rel(session)]` | all three `&` |
| `{NOT:[{OR:[a,b]}]}` | `OR[a,b]` w/ `negate` | `¬(a ∨ b)` |
| `{NOT:[{NOT:[x]}]}` | `x` | `x` |
| `{NOT:[a,b]}` | `AND[a¬, b¬]` | `¬a ∧ ¬b` |
| `{session_filter:{}}` | `rel(session, ANY, empty)` | has ≥1 session |

Round-trip guarantee is **logical (`to_q`) equivalence**, not byte equality
(empty operator lists drop; structure canonicalizes).

## Testing

- **vitest** (`serializer.test.ts`): export cases (each node kind, negate wrap, empty
  group → `{}`, relation non-empty preservation), import cases (the worked table incl.
  the A1 precedence case and the double/group NOT cases), and
  `serialize(deserialize(x))` structural round-trip on `fixtures.json`.
- **Python contract** (`tests/test_filter_tree_contract.py`): reads the same
  `fixtures.json`; for each case asserts it parses via `filter_from_json` and that the
  canonical re-export is **`to_q()`-equal** to the original — locking TS canonical
  output to backend semantics across OR / `¬`-group+leaf / relation × quantifier / field
  comparison (incl. the `(C|O)&K` precedence case) / mixed-import normalization. Set
  criteria use the **client** shape `{value:[{id,label}],excludes,modifier}` (labels
  don't affect `to_q`, so the contract holds).

## Build wiring (finding C-D5)

The current `tsconfig.json` is `include: ["ts/**/*.ts"]`, `noEmitOnError: true`, emits to
`games/static/js/dist/`; `make ts`/`make ts-check`/`make check`/`make test` all run
`tsc`. Dropping `*.test.ts` under `ts/` unguarded would emit test JS into the served/
Docker bundle and fail the whole build on `import … from "vitest"`. Plan:

- Build `tsconfig.json` gets `exclude: ["ts/**/*.test.ts"]` so tests never compile into
  `dist` and never break `tsc`/`ts-check`.
- A separate `tsconfig.vitest.json` (or vitest's own `types`) wires `vitest/globals`.
- `vitest` added as a devDependency (pnpm); a new **`make test-ts`** target runs it, and
  `make check` gains a `test-ts` step so the suite actually runs in CI.

## Follow-up issues to file

- **Backend `to_json` drops `value == default` criteria** (e.g. `price`/`days_to_finish`
  `EQUALS 0`) — a latent lossy round-trip on any `filter_to_json` path (finding B-D2).
  File as a backend issue.
- **Set-criterion label rehydration** when the builder ingests a backend-`to_json`
  filter (stat links) — server-side id→label resolution. Owned by #196/#197 (note on
  those issues; finding B-D1).
- **Field-metadata → TS codegen** for the `MetadataRegistry` feed — already #152; this
  module's interface is the consumer contract.
- **Builder guard against an accidental empty relation node** (would inject a real
  EXISTS) — UI concern for #189/#196 (finding A-LOW).
