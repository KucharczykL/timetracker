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

- **Group** — connective ∈ {`AND`, `OR`, `NOT`} + ordered children (groups / leaves /
  relations). → `{CONNECTIVE: [child_json, …]}`, each child its own single-key dict.
- **Leaf (criterion)** — field + criterion (modifier + value[/value2]). →
  `{field: {value, modifier, value2?}}`.
- **Leaf (field comparison)** — left/right column + modifier (reuses the existing single
  `field-comparison` row). → `{field_comparisons: [{left, right, modifier, granularity}]}`.
- **Relation descent** — relation field + quantifier + one child group. →
  `{rel_field: {match: Q?, …child-group-serialized}}`; `match` omitted when ANY (default).

**Negation:** `NOT` is a third group connective, not a per-node toggle. A `NOT` group with
multiple children means "none of these" (`~a AND ~b`, backend's existing list semantics);
`NOT(a AND b)` is a `NOT` group wrapping one `AND` group. Leaf-level "is-not" stays on each
criterion's own modifier (orthogonal).

**Import normalization (the crux of prefill round-trip):** an `OperatorFilter` dict may mix
keyed criterion fields + `AND`/`OR`/`NOT` lists + `field_comparisons` + sub-filter fields at
one level. The importer treats each dict as an **implicit AND group** whose children are:
each keyed criterion → a criterion leaf; each `field_comparisons` entry → a comparison leaf;
each sub-filter field → a relation node (recurse into its child); the `AND` list → merged as
sibling children; the `OR` list → an `OR` group child; the `NOT` list → a `NOT` group child.
Export re-emits canonical form. Round-trip is logically equivalent (may canonicalize shape).
Reuse server metadata — `resolve_path_kind()`, `_criterion_class_for()`,
`comparable_columns()` — so the client never duplicates per-field type tables.

## UX / visual spec

- **Group rendering:** nested bordered cards; connective chip (`[AND ▾]`) in each card
  header; nesting = cards-within-cards with **alternating depth background** (Qui pattern,
  ~3–4 shade cycle).
- **Relation descent:** inline **accent block** among the group's children —
  `↳ [ANY ▾] of [sessions ▾] where` header (relation pick + quantifier) wrapping a nested
  group built from the **target model's** fields (makes the Game→Session model switch
  explicit, Filter-Forge `↳ INTO` pattern).
- **Restructuring: buttons only, no drag-and-drop.** Per-node: `remove`, `duplicate`,
  `wrap in group`; reorder within a group via `↑`/`↓`; group footer:
  `[+ condition] [+ group] [+ relation]`; connective changed in place. Covers all real
  restructuring with vanilla DOM, robust on touch (both case studies warned nested-tree DnD
  is fragile).
- **Depth: soft cap at 5.** `Add group`/`Add relation` disabled past depth 5 with a
  "max nesting reached" hint.
- **Add-condition / leaf flow:** `+ condition` inserts a row `[field ▾ searchable, grouped]
  [modifier ▾ valid-for-type] [value widget]`. Field-first; on field pick the modifier list
  + value widget derive from the criterion class. Reuse existing leaf widgets: `FilterSelect`
  (id/enum sets), `DateRangeFilter`, number input, bool radio, single `field-comparison` row.
- **Empty / initial state:** root is always an `AND` group, pre-seeded with one empty leaf
  row (field picker open) + footer buttons.
- **Validation:** client pre-validates (no field chosen, missing value, incomplete BETWEEN
  bounds) → mark leaf invalid + disable Apply. Backend `apply_structured_filter` fail-open on
  parse error remains the safety net.
- **Natural-language summary:** read-only English readout at top, recomputed on every edit by
  a pure client-side tree walk (no server call). e.g. "Games where status is Finished and any
  session has device Handheld and duration ≥ 2h."
- **Live result count:** debounced + cancellable **top-level total** count badge
  ("≈ 142 games"). One count query per settled edit via a small per-model count endpoint
  (`parse_*_filter` → `to_q().count()`). Per-group counts are NOT built (Filter-Forge faked
  them) — possible later enhancement.
- **Presets:** toolbar `[Load preset ▾]` (prefills tree from a `FilterPreset`'s JSON — same
  code path as loading any `?filter=`) and `[Save as preset…]` (serializes the tree). Reuse
  existing `preset_list_url` / `preset_save_url`.
- **Mobile:** cards stack; reduced left padding per depth; accent relation block full-width;
  no horizontal scroll; buttons-only model works on touch.

## Prereq components → 2c child issues (the required #172 output)

Each built + unit-tested in isolation:

1. **Recursive group shell** custom element — group card, connective chip, ordered children,
   footer buttons, depth coloring, soft cap 5, buttons-only restructuring
   (remove/duplicate/wrap/unwrap/↑/↓). Recursion is the core.
2. **Connective selector** — AND/OR/NOT chip dropdown.
3. **Add-criterion field picker** — searchable/grouped field combobox reading per-model field
   metadata (name, label, criterion kind, choices); inserts a leaf row.
4. **Leaf row** — field/modifier/value; derives modifier list + value widget from criterion
   class; mounts existing `FilterSelect` / date / number / bool / single `field-comparison`
   widgets.
5. **Relation-descent + quantifier picker** — relation select (typed sub-filter fields of the
   model) + quantifier (ANY/NONE/ALL) + nested child group, rendered as the accent block.
6. **Recursive serializer/deserializer** — node tree ↔ `OperatorFilter` JSON: canonical
   export + import normalization (above). TS module, contract-tested against backend
   round-trip.
7. **Natural-language summary** — client-side tree → English walker.
8. **Live count** — per-model count endpoint + debounced/cancellable badge.
9. **Server field-metadata exposure** — per-model field list (name, label, criterion kind,
   choices, available relations) for the picker, from `resolve_path_kind` /
   `_criterion_class_for` / `comparable_columns` (#161 + #157 feed this; possibly the
   field-metadata registry the #168 comment flagged).
10. **Builder page shell** — per-model `/…/filter` route + `render_page` view; toolbar
    (presets, Apply, Clear); mounts root group + NL summary + count.

Exact split may merge/refine during 2b (#173) planning, but this is the component set.

## Follow-up issues to file

- **GitHub-style quick bar** (single-model facet dropdowns + degrade-to-"Advanced active").
- **Per-group live count** (deferred enhancement on the advanced builder).
- Confirm whether the #168-comment **field-metadata registry** is folded into component 9 or
  filed separately — decide in 2b.

## Verification (of the eventual build, for 2b/2d — not #172)

- Round-trip property test: arbitrary nested `?filter=` JSON → import → export ≡ logically
  equivalent (`to_q()` produces identical results); cover OR, NOT-as-none-of, relation +
  each quantifier, field comparison, mixed-shape import normalization.
- Component unit tests per 2c item (render + serialize in isolation).
- e2e (Playwright, `e2e/`): build a cross-model filter on `/games/filter`, Apply, assert the
  list narrows; load a preset; confirm NL summary + count update; confirm quick bar degrades
  to "Advanced active" for a complex filter.
