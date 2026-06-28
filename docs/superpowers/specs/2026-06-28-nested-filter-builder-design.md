# Nested Filter Builder — UX Design

**Issue:** #172 (phase 2a of #168, roadmap epic #171)
**Status:** Design approved; output feeds 2b plan (#173) and 2c component issues.
**Date:** 2026-06-28

## Context

The flat filter bar can only express a single AND-row of single-model criteria. The
`OperatorFilter` algebra (`common/criteria.py`) **already** supports arbitrary nesting —
n-ary `AND`/`OR`/`NOT` lists, typed cross-entity sub-filter fields (`session_filter`,
`purchase_filter`, `playevent_filter`, `platform_filter`) each carrying a `match`
quantifier (ANY/NONE/ALL via `relation_to_q`), and `field_comparisons`. What's missing is
the **UI + a recursive serializer**. This is #168 (a phased sub-program); #172 is its
brainstorm, whose output is this design doc **plus** a concrete prereq-component list
(filed as 2c child issues). No code is written under #172.

Research already done (#175): `docs/qui-filter-builder-case-study.md`,
`docs/filter-forge-prototype-case-study.md`. This design borrows Qui's robust foundation
(explicit schemas, discrete boundary states, no fragile nested-tree DnD) and Filter-Forge's
relational model + UX (explicit relation-descent nodes, natural-language readout).

## Two-tier filtering model

Single source of truth is the `?filter=` JSON; both tiers read/write it and hit the same
backend.

1. **Quick bar** (per-list, single-model) — GitHub-style facet dropdowns
   (`status: [▾] platform: [▾] …`), flat AND of a few leaf criteria. When the active
   `?filter=` is too complex to round-trip losslessly (any OR/NOT, nesting, or relation
   descent) it **degrades** to a read-only "Advanced filter active · [Edit in builder] ·
   [Clear]" pill rather than mis-rendering controls.
   → **Out of scope for #172**; filed as its own issue (single-model, no tree, ships
   independently).
2. **Advanced builder** (this spec) — the nested cross-model tree on a dedicated per-model
   route (`/games/filter`, `/sessions/filter`, `/purchases/filter`, `/playevents/filter` —
   one per list that has an `OperatorFilter` subclass). Apply navigates back to the list
   with `?filter=`. Shareable URL state.

## Node model & serialization contract

The UI is a **homogeneous tree** of three node kinds. The serializer always emits canonical
form, which kills the transitional OR-isolation wrapper and the flat `field-comparison`
special-case (the #167 `TODO(nested-builder)` debt).

- **Group** — connective ∈ {`AND`, `OR`} + optional `¬` negate flag + ordered children (groups
  / leaves / relations). → `{CONNECTIVE: [child_json, …]}`, wrapped in `{NOT:[…]}` when `¬` is
  set; each child its own single-key dict.
- **Leaf (criterion)** — field + criterion (modifier + value[/value2]) + optional `¬` flag. →
  `{field: {value, modifier, value2?}}`, wrapped in `{NOT:[…]}` when `¬` is set.
- **Leaf (field comparison)** — left/right column + modifier + optional `¬` (reuses the existing
  single `field-comparison` row). → `{field_comparisons: [{left, right, modifier, granularity}]}`.
- **Relation descent** — relation field + quantifier + one child group + optional `¬`. →
  `{rel_field: {match: Q?, …child-group-serialized}}`; `match` omitted when ANY (default).

**Negation (toggle model):** negation is **not** a connective — connectives are only `AND`/`OR`.
Every node carries an independent **`¬` toggle** that inverts it (Qui's model). `¬` on a group
inverts the whole group; `¬` on a leaf inverts that condition. This avoids the multi-child-NOT
ambiguity entirely (there is no NOT *group*, so no "is it `~a∧~b` or `~(a∧b)`?" question) and
spends **zero extra nesting depth** per negation — important against the depth cap, since a
NOT-as-connective would burn a level for every negated group. On export, a node with `¬` set
serializes wrapped as `{NOT:[node]}` (e.g. `¬OR[a,b]` → `{NOT:[{OR:[a,b]}]}` = `~a ∧ ~b`,
verified). Leaf-level "is-not" via the criterion's own modifier (`NOT_EQUALS`, `EXCLUDES`, …)
remains available too — `¬` and the modifier are two harmless routes to the same result;
guidance favors the modifier for a single criterion, `¬` for groups.

**Canonical export (verified correct):** each group exports to exactly one connective key
(`{AND:[…]}` / `{OR:[…]}`), each child a single-key dict; a leaf → `{field:{…}}`; a relation →
`{rel_field:{match?, <one canonical group>}}`; any `¬`-set node is wrapped in `{NOT:[…]}`. The
builder **never emits a mixed node** (keyed fields + operator lists at one level). A live
`to_q()` check confirmed canonical top-level `OR` evaluates identically to the old
OR-isolation-wrapper form (empty `Q()` is absorbed in Django ORs — no match-all poisoning), so
the transitional wrapper is genuinely droppable. Empty operator lists are dropped on export
(`{AND:[]}`→`{}`); round-trip is **logical equivalence**, not byte equality.

**Import normalization (prefill from arbitrary/legacy JSON):** an `OperatorFilter` dict may mix
keyed criterion fields + `AND`/`OR`/`NOT` lists + `field_comparisons` + sub-filter fields at one
level, and the backend evaluates these in a fixed left-to-right order — `criteria &= …`, then
`&= each AND`, then `|= each OR`, then `&= ~each NOT` (`_apply_operators`, criteria.py:1080).
The importer must **reproduce that precedence faithfully**, not assume an implicit AND:
1. Build the `&`-part `P` = an AND group of [each keyed criterion leaf, each `field_comparisons`
   entry as its own comparison leaf, each sub-filter field as a relation node, each `AND`
   sub-filter imported recursively].
2. If `OR` present: `P` becomes `OR[ P, …each OR sub-filter imported ]`.
3. If `NOT` present: result becomes `AND[ (P-or-OR), …(each NOT sub-filter imported as a node
   with its `¬` flag set) ]` (each `&= ~`). A single-child `AND[…]` collapses to its child, so
   `{NOT:[{OR:[a,b]}]}` imports as an `OR[a,b]` node with `¬` set; a multi-child `{NOT:[a,b]}`
   imports as `AND[ a¬, b¬ ]`.

So `{name, OR:[x]}` correctly imports as `OR[name, x]` (= `name OR x`), **not** `AND(name, x)`.
Re-export canonicalizes the shape; the tree's `to_q()` equals the original's. Reuse server
metadata — `resolve_path_kind()`, `_criterion_class_for()`, `comparable_columns()` — so the
client never duplicates per-field type tables.

**Relation / sub-filter notes:** a relation node's child is exactly **one** canonical group, so
its sub-filter dict carries `match` + one connective key (or a `{NOT:[…]}` wrapper when the child
group is negated) — no ambiguity. An **empty**
relation child is a feature: `ANY`+empty = "has ≥1 related row", `NONE`+empty = "has 0 related
rows". Cross-model relation fields can cycle (`game→session→game`), and the backend has **no
recursion guard** today (see Open items) — a hand-edited cyclic `?filter=` would infinite-loop,
so a parse-time depth guard is a prerequisite.

## UX / visual spec

- **Group rendering:** nested bordered cards; header carries an `AND`/`OR` connective chip
  plus a `¬` negate toggle (lit = whole group inverted); nesting = cards-within-cards with
  **alternating depth background** (Qui pattern, ~3–4 shade cycle). Leaves carry the same `¬`
  toggle.
- **Relation descent:** inline **accent block** among the group's children —
  `↳ [ANY ▾] of [sessions ▾] where` header (relation pick + quantifier) wrapping a nested
  group built from the **target model's** fields (makes the Game→Session model switch
  explicit, Filter-Forge `↳ INTO` pattern).
- **Restructuring: buttons only, no drag-and-drop.** Per-node: `remove`, `duplicate`,
  `wrap in group` (new wrapper defaults to the parent's connective), `unwrap/flatten` (dissolve
  a group, splice its children into the parent); reorder within a group via `↑`/`↓`; group
  footer: `[+ condition] [+ group] [+ relation]`; connective changed in place. **Accepted
  limitation:** moving a leaf to a non-sibling group two levels away is done via remove + re-add,
  not a cross-branch move (vanilla DOM, robust on touch; both case studies warned nested-tree DnD
  is fragile).
- **Depth: soft cap at 5.** The cap counts **group-nesting depth**; a relation-descent's child
  group is **+1 level**; a criterion leaf is depth-0 (terminates); a `¬` toggle costs **0 levels**
  (it's a flag, not a wrapper node). `Add group`/`Add relation` disabled past depth 5 with a
  "max nesting reached" hint. (The backend recursion guard — Open items — is set higher and is the
  real safety bound.)
- **Add-condition / leaf flow:** `+ condition` inserts a row `[field ▾ searchable, grouped]
  [modifier ▾ valid-for-type] [value widget]`. Field-first; on field pick the modifier list +
  value widget derive from the criterion class. **On field change:** reset modifier to the first
  valid one for the new type, **clear** the value (no silent type-coercion), mark the leaf
  incomplete until filled; replacing the value widget flushes old DOM. Reuse existing leaf
  widgets: `DateRangeFilter` + bool radio drop in clean; `FilterSelect` needs a **self-serialize**
  rework (today it depends on a global `readSearchSelect` preprocessing pass — see components);
  the single `field-comparison` row needs a **leaf variant** embedding its own `columns` and
  dropping the AND/OR mode toggle (the enclosing group owns the connective).
- **Empty / initial state:** root is always an `AND` group, pre-seeded with one empty leaf
  row (field picker open) + footer buttons.
- **Validation:** client pre-validates (no field chosen, missing value, incomplete BETWEEN
  bounds) → mark leaf **incomplete** (faded + badge), **exclude it from both the count query and
  Apply**, and disable Apply while any leaf is incomplete. Backend `apply_structured_filter`
  fail-open on parse error remains the safety net.
- **Natural-language summary:** read-only English readout at top, recomputed on every edit by
  a pure client-side tree walk (no server call). e.g. "Games where status is Finished and any
  session has device Handheld and duration ≥ 2h."
- **Live result count:** debounced + cancellable **top-level total** count badge
  ("≈ 142 games"). One count query per settled edit via a small per-model count endpoint (new —
  `parse_*_filter` → `to_q().count()`). Badge shows **"counting…"** while debounced/in-flight and
  **"count unavailable"** on endpoint error (never a bare 0). Incomplete leaves are excluded from
  the query. Per-group counts are NOT built (Filter-Forge faked them) — possible later
  enhancement.
- **Presets:** toolbar `[Load preset ▾]` (prefills tree from a `FilterPreset`'s JSON — same
  code path as loading any `?filter=`) and `[Save as preset…]` (serializes the tree). Reuse
  existing `preset_list_url` / `preset_save_url`.
- **Mobile:** cards stack; reduced left padding per depth; accent relation block full-width;
  no horizontal scroll; buttons-only model works on touch.

## Prereq components → 2c child issues (the required #172 output)

The adversarial review corrected the naive "all built in isolation" framing: **two are
foundational** and the rest depend on them. Build order: **0 → 9 → 6 → (1–5 in parallel) → 7,8 →
10.**

0. **Backend recursion/cycle guard** (NEW prereq) — relation fields cycle
   (`game→session→game`) and `OperatorFilter.from_json`/`to_q` enforce no depth limit today, so a
   hand-edited cyclic `?filter=` infinite-loops the server. Add a parse-time depth guard in
   `from_json` (raise `FilterError` past a max depth, e.g. 10). Independent of the UI but a
   security prerequisite the shareable-URL builder makes reachable. **File as a backend issue.**
9. **Server field-metadata registry** (foundational) — a per-model field list returning
   `{name, label, kind, nullable, choices, relations}`. `resolve_path_kind` /
   `_criterion_class_for` / `comparable_columns` exist (~40%); the **label / choices / nullable /
   relation enumeration is missing and must be built**. This is the field-metadata registry the
   #168 comment flagged; cross-ref #161 (FilterField) + #157 (criterion types); later feeds #152.
6. **Recursive serializer/deserializer** (foundational — blocks 1–5,7,8) — node tree ↔
   `OperatorFilter` JSON: canonical export + the faithful import normalization (above). Replaces
   the flat `filter-bar.ts` `setPath`/`appendAnd`/`data-kind`-switch glue. Must serialize a tree
   recursively (per-group, not one global form pass). TS module, contract-tested against backend
   round-trip (`to_q()` equality across OR / `¬`-negated group + leaf / relation×quantifier / field
   comparison / mixed-shape import).
1. **Recursive group shell** custom element — group card, connective chip, ordered children,
   footer buttons, depth coloring, soft cap 5, buttons-only restructuring
   (remove/duplicate/wrap/**unwrap**/↑/↓). Recursion is the core.
2. **Connective selector + negate toggle** — `AND`/`OR` chip dropdown plus a per-node `¬` toggle
   (groups and leaves); `¬` serializes as a `{NOT:[…]}` wrapper.
3. **Add-criterion field picker** — searchable/grouped field combobox reading component 9's
   metadata; inserts a leaf row; defines on-field-change reset behavior.
4. **Leaf row + leaf widgets** — field/modifier/value; derives modifier list + value widget from
   criterion class. `DateRange` + bool reuse clean; **`FilterSelect` reworked to self-serialize**
   (drop the global `readSearchSelect` preprocessing dependency); **new single-row
   `field-comparison` leaf** embedding its own `columns`, no mode toggle.
5. **Relation-descent + quantifier picker** — relation select (component 9's relation list) +
   quantifier (ANY/NONE/ALL) + nested child group, rendered as the accent block.
7. **Natural-language summary** — client-side tree → English walker (independent; decorative).
8. **Live count** — NEW per-model count endpoint + debounced/cancellable badge with
   counting/unavailable states.
10. **Builder page shell** — per-model `/…/filter` route + `render_page` view; toolbar
    (presets, Apply, Clear); mounts root group + NL summary + count; reads/writes `?filter=`.

Exact split may merge/refine during 2b (#173) planning, but this is the component set.

## Open items / follow-up issues to file

- **Backend recursion/cycle guard** (component 0) — file as a backend issue; prerequisite to
  shipping the builder (DoS via cyclic hand-edited `?filter=`).
- **GitHub-style quick bar** (single-model facet dropdowns + degrade-to-"Advanced active"). Its
  degrade predicate must account for canonicalization (a quick-bar filter, exported and reloaded,
  must round-trip back to editable, not flip to "advanced") — pin in that issue.
- **Per-group live count** (deferred enhancement on the advanced builder).
- The #168-comment **field-metadata registry** is folded into component 9 (decided here, not
  deferred).

## Verification (of the eventual build, for 2b/2d — not #172)

- Round-trip property test: arbitrary nested `?filter=` JSON → import → export ≡ logically
  equivalent (`to_q()` produces identical results); cover OR, `¬`-negated nodes, relation +
  each quantifier, field comparison, mixed-shape import normalization.
- Component unit tests per 2c item (render + serialize in isolation).
- e2e (Playwright, `e2e/`): build a cross-model filter on `/games/filter`, Apply, assert the
  list narrows; load a preset; confirm NL summary + count update; confirm quick bar degrades
  to "Advanced active" for a complex filter.
