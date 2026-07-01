# Issue #194 — Natural-language filter summary

**Status:** Design approved 2026-07-01.
**Parent:** #168 (nested filter builder), phase 2c, component 7 ("independent, decorative").
**Related design:** `docs/superpowers/specs/2026-06-28-nested-filter-builder-design.md`.

## Goal

A read-only English readout of the current filter tree, shown at the top of the
nested builder and recomputed on every edit by a **pure client-side tree walk**
(no server call). Example:

> Games where status is Finished and any sessions where device is Handheld and duration is at least 2h.

## Scope

**This issue ships one pure TS module + its tests. It does NOT wire the summary
into any page.** Mounting the readout into the builder (reading the live
`<filter-group>` tree, calling `summarize`, rendering the string) is component 10
(2d assembly), a separate issue. This mirrors the `serializer.ts` precedent: the
pure, fixture-tested module lands before the page shell that consumes it.

Two files:

- `ts/elements/filter-tree/summary.ts` — the walker.
- `ts/elements/filter-tree/summary.test.ts` — vitest string assertions.
- `tests/test_summary_modifier_contract.py` — Python contract (modifier keys are real).

No backend endpoint, no page route, no `<filter-group>` change.

## Module API

```ts
import type { FieldMeta, GroupNode } from "./types.js";

interface SummaryModel {
  fields: Map<string, FieldMeta>; // field name -> metadata (label, kind, choices, relations)
}

interface SummaryContext {
  modelKey: string;                       // root model key, e.g. "game"
  modelLabel: string;                     // root display noun, e.g. "Games"
  models: Record<string, SummaryModel>;   // every reachable model key -> its fields
}

export function summarize(tree: GroupNode, ctx: SummaryContext): string;
```

- **Pure, DOM-free.** Consumes the in-memory `GroupNode` tree and static metadata
  only. Reads each criterion leaf's payload directly off `node.criterion` (the
  stored `{ value, value2?, modifier, excludes? }` shapes the leaf widgets
  produce), never from a live widget.
- **Metadata source.** `models` reuses the per-model `FieldMeta` bundle that
  `<filter-group>` already parses from its `models` prop (`parseModels`). Tests
  build a small stub. Component 10 passes the live bundle.
- **Filled-tree contract.** `summarize` reads `node.criterion` / `node.comparison`
  as given. Mid-edit the widget DOM is the tree's source of truth, so the caller
  (component 10) passes a **filled** tree — the `fillCriteria` output that already
  reads each live widget — not the raw `getTree()`. This module never touches the
  DOM; supplying current payloads is the wiring's responsibility.
- **Relation target resolution** mirrors `filter-group.ts` `targetModel`:
  the target model key = `fields.get(relationField).relations[0].model.toLowerCase()`,
  falling back to the current model key when unknown. The walk switches the active
  model at each relation descent so a relation child group's fields resolve against
  the target model, never the root.

## Behaviour

### Sentence frame

- Non-empty root: `"<modelLabel> where <group-body>."`
- Empty root (no children): `"<modelLabel> (all)."` — echoes the builder's
  "No conditions. This will match all items." state.

### Groups, connectives, negation

- Join a group's rendered children with `" and "` (AND) or `" or "` (OR).
- Parenthesize a **child group** — wrap its body in `( … )` — when it has more than
  one child **or** its connective differs from its parent's. A single-child,
  same-connective group renders bare (no redundant parens).
- `negate` on any node renders as a `"not (…)"` prefix; the negated body is always
  parenthesized so the scope of `not` is unambiguous at any depth.

### Leaf phrasing — modifier → phrase map

Field name renders as `FieldMeta.label`. The modifier maps to a natural phrase:

| Modifier | Phrase |
|---|---|
| `EQUALS` | `is <v>` |
| `NOT_EQUALS` | `is not <v>` |
| `GREATER_THAN` | `is more than <v>` |
| `LESS_THAN` | `is less than <v>` |
| `GREATER_THAN_OR_EQUAL` | `is at least <v>` |
| `LESS_THAN_OR_EQUAL` | `is at most <v>` |
| `BETWEEN` | `is between <v> and <v2>` |
| `NOT_BETWEEN` | `is not between <v> and <v2>` |
| `IS_NULL` | `is empty` (no value) |
| `NOT_NULL` | `is set` (no value) |
| `MATCHES_REGEX` | `matches <v>` |
| `NOT_MATCHES_REGEX` | `does not match <v>` |
| `INCLUDES` | `is <v>` (1 value) / `is one of <v…>` (n) |
| `EXCLUDES` | `is not <v>` (1 value) / `is none of <v…>` (n) |
| `INCLUDES_ALL` | `has all of <v…>` |
| `INCLUDES_ONLY` | `is exactly <v…>` |

The map is the single source the contract test validates. Every key must be a
real `common.criteria.Modifier` value.

### Value rendering

- **enum/choice** (`string` kind whose `FieldMeta.choices` is non-empty): map the
  stored value to its choice label (`"f"` → `"Finished"`). Unknown value → render
  the raw value.
- **set** (`set` kind): the payload carries its own `{ id, label }` entries — render
  the `value` list's labels. If `excludes` is also present, append
  `" and not <excluded labels>"`. Presence modifier (`{ modifier }` only) → "is
  empty"/"is set", no list.
- **bool**: `true` → the field's true-choice label if present else `"yes"`; `false`
  → false-choice label else `"no"`.
- **number / date**: render the raw stored value; `BETWEEN`/`NOT_BETWEEN` render
  both bounds. (No unit formatting — the stored value string is shown verbatim.)
- A list of values joins with `", "` and a final `" or "` for the last item
  (`INCLUDES` n) / `" and "` for `INCLUDES_ALL`/`INCLUDES_ONLY`.

### Relation descent

`"<quantifier> <relationLabel> where <child-body>"`:

- Quantifier: `ANY` → "any", `NONE` → "no", `ALL` → "every".
- Relation noun = the relation field's `FieldMeta.label`, **lowercased as-is**
  (no singularization — e.g. "any sessions where"). A `negate` on the relation node
  still uses the `"not (…)"` prefix around the whole descent.
- **Empty child group** (quantifier-only presence test, #225): render the
  per-quantifier presence phrasing instead of "where …", model-agnostic and echoing
  `relationEmptyText` in `filter-group.ts`:
  - `ANY` → "has related <relationLabel>"
  - `NONE` → "has no related <relationLabel>"
  - `ALL` → (vacuously true) "matches all"

### Incomplete nodes

The summary recomputes mid-construction, so it must render partial trees.

- A criterion leaf with **no field chosen** → `"…"`.
- A leaf **with a field but no usable value** (empty widget payload / half-filled
  BETWEEN) → `"<label> …"`.
- A relation node with **no field chosen** → `"… where <child-body>"` (or just
  `"…"` if child empty).

Incomplete nodes are **kept in the sentence** (placeholder), not pruned — pruning
is `serializeForQuery`'s separate concern (the query excludes them; the summary
shows where you are). Completeness is judged from the stored payload with the same
predicates the tree already uses (`isCriterionComplete` semantics), re-expressed
locally over the payload rather than the live DOM.

## Testing

- **`ts/elements/filter-tree/summary.test.ts`** (vitest): exact-string assertions.
  Cases: single leaf per modifier family; nested AND inside OR (parenthesization);
  `NOT` on a leaf and on a group; each relation quantifier (ANY/NONE/ALL) with a
  non-empty and an empty child; set include-only, include+exclude, presence; a
  choice-label lookup; an incomplete leaf (no field, and field-without-value); the
  empty-root "(all)" frame. Reuses `fixtures.json` shapes where they map cleanly,
  plus hand-built trees for the prose-specific cases. A small `FieldMeta` stub
  supplies labels/choices/relations.
- **`tests/test_summary_modifier_contract.py`**: parse the modifier keys out of
  `summary.ts`'s phrase map (or a small exported list mirrored the way
  `filter-tokens` exposes its constants) and assert each is a member of
  `common.criteria.Modifier`. Mirrors `tests/test_filter_tokens_contract.py` so a
  renamed/removed Python modifier fails CI instead of silently orphaning a phrase.

## Non-goals

- No page mount / live wiring (component 10).
- No server round-trip or count.
- No i18n / pluralization engine (relation noun is the label as-is).
- No unit-aware value formatting (durations/prices shown as stored).
