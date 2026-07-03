# Cross-model field-to-field comparison + comparison spaces (issue #169)

**Date:** 2026-07-03 (rev 2, after 3-agent adversarial review)
**Issue:** [#169](https://github.com/KucharczykL/timetracker/issues/169)

## Problem

Field-to-field comparison (`FieldComparisonCriterion`, issues #167/#160) is single-model
only: each filter bar pins one `_comparison_model()` and `comparable_columns(model)`
enumerates only that model's own columns. The compelling comparisons are cross-entity.

Adversarial review of rev 1 established that cross-model paths *alone* carry almost no
payload: `Game` has no `DateField` at all, so with the same-group rule kept, the issue's
headline example (`Session.timestamp_start` vs `Game.year_released`, datetime vs number)
and every "purchase date vs game date" pairing are inexpressible. This design therefore
ships two coupled capabilities:

1. **Cross-model operands** — an operand may traverse one forward to-one FK
   (`game__year_released`).
2. **Comparison spaces** — a row compares in a declared space: `raw`, `date`, or `year`.
   `year` projects temporal operands to their year (a number), making
   datetime/date-vs-number pairs valid; `date` projects datetimes to dates, making
   date-vs-datetime pairs valid (today impossible).

Together they make the headline example work on day one.

## Decisions (from design interview + adversarial review)

| Question | Decision |
|---|---|
| Relation kinds | Forward to-one FKs only. No M2M, no reverse relations. |
| Traversal depth | One hop per comparison row (`relation__column`), no chains. |
| Operand sides | Symmetric — either or both operands may be a relation path. |
| JSON shape | Flat ORM path strings in existing `left`/`right` fields; `granularity` gains `"year"`. |
| Relation allowlist | Introspected: concrete forward to-one FKs from `model._meta`, no per-bar config. |
| Cross-group pairs | Via comparison spaces (row-level `granularity`), not per-side transforms. |
| NULL policy | Strict two-valued: a row matches only if **both operands are non-NULL** and the predicate holds — every modifier, every side. Replaces the raw-ORM asymmetry *and* the previous same-model NOT_EQUALS special case. |
| Picker UI | Left/right selects gain per-source `<optgroup>`s; the **operator dropdown packs (modifier × space)** — no separate granularity control. |

## Operand grammar

```
operand := column | relation "__" column
```

- `column` — a comparable column on the row's model (unchanged; saved presets stay valid).
- `relation` — a concrete forward to-one FK (`ForeignKey`/`OneToOneField`) on the row's
  model; `column` then names a comparable column on the related model.

New named types (PEP 695, per repo convention), in `common/criteria.py`:

```python
type ComparisonOperand = str  # own column "playtime" or one-hop FK path "game__year_released"
```

Relations by model, **actually derived** (verified against `games/models.py`):

- `Session` → `game` (Game, null=True), `device` (Device, null=True)
- `Game` → `platform` (Platform, null=True)
- `Purchase` → `platform` (Platform, null=True), `related_game` (Game, null=True)
- `PlayEvent` → `game` (Game, non-null)
- `Platform`, `Device` → none (their bars gain only the space mechanics)

Note `Purchase` has **two** FKs (rev 1 missed `platform`); note **every** FK except
`PlayEvent.game` is nullable at the schema level — the sentinel Platform/Device objects
are applied only in `save()`, and `on_delete=SET_DEFAULT` with `default=None` NULLs the
column. NULL operands are therefore the normal case, not an edge case; see NULL policy.

There is no self-FK in the schema, column names cannot contain `__` (Django system check
E002), and FK attnames (`game_id`) fail `_meta.get_field` — the grammar is unambiguous.

**Relation to the builder's descent vocabulary.** The nested builder's relation *descent*
(sub-filter groups) is a different, declared vocabulary (`field_metadata` `kind="relation"`,
including M2M like `Purchase.games`). Comparison operands deliberately use a narrower set
(to-one only) because `F()` across a multi-valued relation has fan-out semantics. The two
sets coexist on the builder page; the spec accepts that "Game" appears both as a descent
target (via M2M `games`) and as a comparison source (via `related_game`) on the Purchase
bar — mitigated by FK-derived optgroup labels (below). Inside a descended sub-filter
group (e.g. Session→game_filter), comparison rows are `GameFilter` rows and offer *Game's*
relations (`platform__…`) — one hop **per row's model**, so the tree composes hops. This
is intended.

## Comparison spaces

`granularity` (row-level, existing field) becomes the **space** the row compares in:

| Space | Operand groups accepted | Projection |
|---|---|---|
| `raw` | any single group (both operands same group) | none |
| `date` | `date`, `datetime` | datetime → `TruncDate`/`__date` |
| `year` | `date`, `datetime`, `number` | temporal → `ExtractYear`/`__year`; numbers pass through |

Validation rule: *both operands' groups must be accepted by the space, and after
projection the operands are same-typed by construction.* This generalizes the current
`granularity="date"` gate (which required both sides datetime) — `date` space now also
admits date-vs-datetime. `raw` keeps today's same-group rule exactly.

Modifier vocabulary per space: `date`/`year` spaces use the ordered vocabulary
(EQUALS/NOT_EQUALS/GT/LT/GTE/LTE); `raw` keeps each group's existing vocabulary
(`_allowed_comparison_modifiers`).

`ComparisonGranularity` widens to `Literal["raw", "date", "year"]`; `from_json` accepts
the new value, rejects others (unchanged mechanism, `common/criteria.py:803-811`).

## Criterion layer (`common/criteria.py`)

**`FieldComparisonCriterion`** — fields unchanged: `left`/`right`
(`ComparisonOperand`), `modifier`, `granularity`.

**Path resolution.** Reuse, don't duplicate: `_resolve_model_field(model, lookup)`
(`common/criteria.py:1956`) already walks `__` paths. Comparison-operand resolution is a
strict wrapper over it (or a parameterization — implementer's choice, but **one** path
walker): exactly 0 or 1 relation hops, hop must be a concrete forward to-one FK (M2M and
reverse accessors rejected), terminal field must classify via `_maybe_group_for` /
`_comparison_group_for` **against the related model** — both already take
`(model, column)` and need no change. `FilterError` messages must name the full operand
path and which side (`left`/`right`) failed; the bare related-model message
("Game has no field 'xyz'") must be wrapped to say `game__xyz`.

**Q construction** (`_field_comparison_to_q`). Two changes:

1. *Projection*: in `year` space, temporal operands become `__year` (lookup side) /
   `ExtractYear(F(...))` (expression side); `date` space keeps the existing
   `__date`/`TruncDate` pattern, now applied only to datetime operands (date operands
   pass through).
2. *Strict NULL guards*: every generated Q is
   `Q(<predicate>) & Q(left-path __isnull=False) & Q(right-path __isnull=False)`
   (guards on the full operand paths — a NULL FK NULLs the joined column, so one guard
   per operand suffices). For negated modifiers the predicate is built so Django's
   automatic declared-nullability guards cannot reintroduce asymmetry — the explicit
   guards make the result independent of operand side and of declared `null=` flags.
   The criterion docstring's current NULL truth-table (NOT_EQUALS treats NULL as
   "not equal") is **superseded**: this is a deliberate behavior change to the shipped
   same-model criterion, chosen for uniformity (one sentence covers all modifiers ×
   sides × spaces). Complement semantics ("differs or has no value") remain expressible
   via the filter tree's NOT group.

Both operands on one relation (`game__x` vs `game__y`) share a single join (verified
empirically in review). To-one hops cannot fan out rows.

**Validation** (in `_apply_operators`, `common/criteria.py:1349-1378`, path-aware now):
`left != right` (string comparison stays sound — no self-FKs, so equal strings ⟺ same
column); space accepts both operand groups; modifier allowed for space; resolution
errors as above. `MAX_FIELD_COMPARISONS` stays enforced in `from_json` (parse-time), as
today.

## Column enumeration (`comparable_columns`)

`ComparableColumn` (a TypedDict, `common/criteria.py:1839`) gains one field:

```python
source: str  # optgroup label, from the FK: "" for own columns, else the FK's verbose name, e.g. "Base game"
```

The discriminator is **per-FK, not per-model**: `Purchase.related_game` renders as its
field verbose name ("Related game" / whatever the model declares), so two FKs to the
same model stay distinguishable and the label says what the *relation* means, not just
the target type. (FK `verbose_name`s should be audited/set so the labels read well —
part of this change.)

`comparable_columns(model)` emits own columns (bare values, `source=""`) first, then per
forward FK (in `_meta` order) the related model's comparable columns as
`value=f"{fk.name}__{column}"`. Sorting: today's single flat
`label.lower()` sort becomes per-source-group alphabetical (a real change to the sort,
not a no-op). Existing inclusion rules apply unchanged on the related model
(GeneratedFields with output types included, pk/JSON/relations excluded).

Junk-pair note: cross-model expansion multiplies same-group pairs that are technically
valid but semantically silly (`price` vs `related_game__year_released`,
`note` CONTAINS `game__status` choice codes). Accepted — same philosophy as the existing
own-model picker; type-group gating is the only curation layer. The INCLUDES-empty-string
foot-gun (`right=""` matches everything, documented at `criteria.py:764-766`) gets more
reachable via ""-defaulted related columns (`game__wikidata`, `platform__group`); it stays
documented-not-special-cased, but gains a widget test pinning the behavior.

## UI

**Operator dropdown packs (modifier × space).** The current day-granular checkbox is
removed. The operator `<select>` lists, grouped by space via `<optgroup>`:

- *Exact*: the raw-space vocabulary for the left operand's group (unchanged labels);
- *By date* (when left is temporal): "on same date as", "before (date)", …;
- *By year* (when left is temporal or number): "in same year as", "before (year)", ….

Option value encodes the pair (e.g. `"lt:year"`); reading a row splits it back into
`modifier` + `granularity` — the JSON leaf shape is untouched. Picking an operator
recomputes the right list for `(left group, space)`.

**Column selects gain `<optgroup>` per source.** `_fc_column_options`
(`common/components/filters.py:796`) renders own columns under the bar model's verbose
name, then one optgroup per FK (`source` label). `<optgroup>` has no builder yet — add
`Optgroup` to the `primitives.py` whitelist and export it (per CLAUDE.md convention).
Because optgroup headers aren't visible in a collapsed select, related option *labels*
are self-qualifying: "Base game: Year released" as the option text, bare labels for own
columns.

**TS (`ts/elements/field-comparison-set.ts`).** `fillSelect` (currently flat
`[value,label][]`) is reshaped to emit optgroups and to omit source groups that filter
to empty; `refreshRow` filters by `(left group, space)` from the packed operator value;
`readComparisonRow` splits the operator value. Values stay opaque path strings —
`game__year_released` vs `year_released` are distinct values, so same-named columns
across models pair fine.

**Codegen.** The `ComparableColumn` mirror is codegen'd into
`ts/generated/filter-metadata.ts` (producer `common/components/ts_codegen.py`) — **not**
`props.ts`; `FieldComparisonSetProps` itself is unchanged (`columns` is an opaque JSON
`str` prop). Run `make gen-element-types`.

**Nested builder.** `comparison_row_template` and the per-model bundles
(`model_field_registry` → `FilterGroupProps.models`) consume the same
`comparable_columns` output, so the builder page gets everything automatically —
verified plumbing in review. Payload grows (each model's columns now include FK targets'
columns; Session: 9 own + ~10 Game + ~3 Device entries); accepted, noted, not optimized.

**Summary chips.** Two files, not one: `ts/elements/filter-summary.ts` builds the
value→label map (`parseModels`) and must compose the qualified label from `source`
("Base game: Year released"); `ts/elements/filter-tree/summary.ts` `renderComparison`
consumes it and additionally renders the space ("… in same year as …"). Without the
qualified labels, duplicate `created_at` labels across models produce tautological chips.

## Serialization / cross-language contract / compat

JSON leaf shape unchanged: `{left, right, modifier, granularity?}`; `granularity`
emitted when ≠ `"raw"`. The TS serializer passes operands through opaquely (verified) —
no serializer change.

Contract fixtures: new cases in `ts/elements/filter-tree/fixtures.json` covering path
operands and `year` space, including a **Purchase** case — which requires adding
`"purchase"` to `FILTER_FOR_MODEL` in `tests/test_filter_tree_contract.py:26` and to the
fixtures `registry`. Fixtures land in the same change as the Python backend (the pytest
side runs real `to_q()`).

**Compat story (stated, not versioned):** presets saved before this change load
unchanged (bare operands, `raw`/`date` spaces). A preset saved *with* new operands/spaces
and loaded by older code fails `from_json`/`_apply_operators` → `FilterError` →
warn-and-ignore of the whole filter (view contract, `criteria.py:36-50`) — the saved view
degrades to "all rows" with a warning toast. Accepted for a single-user app in
development; no version field added. The same failure mode applies if a FK/column is
later removed while referenced by a preset.

## Testing

- **Python** (`tests/test_filters.py`):
  - Path resolution: unknown relation; M2M (`games__…`) rejected; reverse accessor
    rejected; two-hop rejected; unknown column on related model; error messages name the
    full path and side.
  - Spaces: raw same-group rule intact; `date` admits date-vs-datetime; `year` admits
    each temporal-vs-number combination; invalid space/group combos rejected; modifier
    vocabulary per space.
  - NULL policy: for **each modifier**, and for path-on-left vs path-on-right, rows with
    NULL FK are excluded; `A≠B` ≡ `B≠A` (the rev-1 asymmetry as a regression test);
    same-model NOT_EQUALS on a nullable column now also excludes NULL rows (behavior
    change pinned).
  - `to_q` SQL-level: shared join for both-sides-one-relation; `year` projection on
    lookup and expression sides; end-to-end querysets incl. the headline example.
  - `comparable_columns`: `source` values, per-FK optgroups incl. **both** Purchase FKs,
    bare own values (preset compat), per-group sort.
- **Widget** (`tests/test_filter_bars.py`): optgroup rendering (columns + operator),
  self-qualified related labels, prefill of a saved cross-model + year-space row,
  INCLUDES-empty-string pin.
- **vitest**: packed operator split/join, refreshRow filtering per (group, space),
  optgroup fillSelect incl. empty-group omission, summary chip labels, serializer
  fixtures.
- **e2e**: `e2e/test_field_comparison_e2e.py` (existing — **will need updating** for the
  restructured selects) and a new builder-page case in `e2e/test_filter_builder_e2e.py`:
  build Session-timestamp-year vs Game-release-year in the browser, apply, assert rows.

## Performance note

Cross-relation comparison adds a JOIN and remains unindexable in the general case — same
standing concern as #165; no action. Markup/prop payload grows roughly 2-3× on
comparison-bearing widgets; accepted.

## Follow-up issues to file

1. **Multi-valued relation operands** — M2M (`Purchase.games`) and reverse relations
   (Session→game→playevents "finish date") via `Exists()`/subquery semantics. Carries
   the issue's second motivating example; explicitly out of scope here.
2. **FK `verbose_name` audit** — if not fully handled inline, ensure every FK's verbose
   name reads well as an optgroup/label source.
