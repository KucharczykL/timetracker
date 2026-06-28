# Filter-bar UI for field-to-field comparisons

**Issue:** [#167](https://github.com/KucharczykL/timetracker/issues/167) (follow-up from #129, #164)
**Date:** 2026-06-28
**Status:** Design approved

## Background

The filter algebra already supports field-to-field comparison: `FieldComparisonCriterion`
(`common/criteria.py`) compares two model columns via `F()` expressions. It lives in
`field_comparisons: list[FieldComparisonCriterion]` on every `OperatorFilter`, serializes
to/from `{"field_comparisons": [{"left": "...", "right": "...", "modifier": "..."}]}`, and is
validated in `OperatorFilter._apply_operators` (self-compare rejected, cross-group rejected,
per-group modifier set enforced via `_comparison_group_for` / `_allowed_comparison_modifiers`).

Today this is reachable **only by hand-editing the `?filter=` JSON**. There is no UI.

## Goal

Add a filter-bar control that builds field comparisons without editing JSON: pick left column,
operator, right column, with the pickers and operator list restricted to compatible comparison
groups, and self-compare / cross-group rejected at the UI level (already rejected server-side).

## Decisions (from design interview)

- **Cardinality:** multiple stacked comparison rows (add/remove), matching the list data model.
- **Boolean model:** a single group **AND/OR mode toggle** (all rows ANDed, or all rows ORed).
  Mixed per-row precedence and nested groups are out of scope. Full nested AND/OR builder is
  filed as a follow-up issue (§10).
- **Column source:** auto-enumerate comparable columns per model via introspection (zero
  maintenance), labelled by `verbose_name`.
- **Picker control:** native styled `<select>` elements (bounded short lists; trivial dynamic
  dependent filtering), not the SearchSelect combobox.

## UX

A new **"Field comparisons"** section in the filter bar:

```
Field comparisons          [ AND | OR ]
  [ left column ▾ ] [ op ▾ ] [ right column ▾ ]  [✕]
  [ left column ▾ ] [ op ▾ ] [ right column ▾ ]  [✕]
  [ + Add comparison ]
```

Dependent behaviour (client-side, mirroring server validation):

- Left column empty → operator and right pickers disabled.
- On left column chosen:
  - operator list = `_allowed_comparison_modifiers(group_of_left)`;
  - right list = only columns of the **same exact comparison group** (note `datetime`, `date`,
    `duration`, `number` are distinct groups and only compare within group);
  - the chosen left column is removed from the right list (no self-compare).
- Operator labels: `=` (EQUALS), `≠` (NOT_EQUALS), `>` (GREATER_THAN), `<` (LESS_THAN),
  `contains` (INCLUDES), `doesn't contain` (EXCLUDES). String group offers all six; numeric/date
  groups offer the first four; bool offers only `=` / `≠`.

## Architecture

### 1. Server — column introspection (`common/criteria.py`)

New named type and helper:

```python
class ComparableColumn(TypedDict):
    value: str               # column name, e.g. "timestamp_end"
    label: str               # verbose_name, title-cased
    group: ComparisonGroup   # "date" | "datetime" | "duration" | "number" | "string" | "bool"

def comparable_columns(model: type[models.Model]) -> list[ComparableColumn]:
    """Every column of `model` that has a comparison group, labelled + grouped, sorted by label."""
```

Implementation iterates `model._meta.get_fields()` and keeps the columns that classify into a
group. To avoid driving enumeration off exceptions, refactor the existing
`_comparison_group_for` so its body delegates to a new internal
`_maybe_group_for(model, column) -> ComparisonGroup | None` (returns `None` instead of raising
for non-comparable columns); `_comparison_group_for` keeps its raising contract by wrapping
`_maybe_group_for` and raising `FilterError` on `None`. `comparable_columns` uses
`_maybe_group_for`. This keeps a single classification source of truth.

Relations, generated fields with no resolvable output type, pk/AutoField, and JSONField are
excluded (they already have no group).

### 2. Python component — `FieldComparisonSet` (`common/components/filters.py`)

A new custom element `<field-comparison-set>`, registered in
`common/components/custom_elements.py` via `register_element` with a Props TypedDict (codegen
target `ts/generated/props.ts` via `make gen-element-types`):

```python
class FieldComparisonSetProps(TypedDict):
    columns: str   # JSON of list[ComparableColumn] for the bar's model
    mode: str      # "AND" | "OR" (initial)
```

The component:

- carries the filter-widget self-describe contract:
  `data-filter-widget`, `data-path = ["field_comparisons"]`, `data-kind = "field-comparison"`
  (the kind already registered in `LeafWidgetKind` but until now unreachable — it becomes
  reachable here);
- server-renders the current rows from prefill (§6);
- includes a hidden `<template>` row the client clones for "+ Add comparison";
- uses native `<select>` styled with the shared `SELECT_CLASS` from `primitives.py`;
- declares its `Media` (compiled `dist/elements/field-comparison-set.js`) via the
  `custom_element_builder` factory, so `Page()` emits the script automatically.

### 3. Client — `ts/elements/field-comparison-set.ts`

Vanilla custom element (`customElements.define`, native `connectedCallback`), no Alpine. Reads
props with the generated `readFieldComparisonSetProps`. Responsibilities:

- add row (clone template) / remove row;
- on left-column change, repopulate the operator and right-column `<select>`s from the
  `columns` data filtered to the left column's group (and excluding the left column itself);
  disable operator/right while left is empty;
- mode toggle state.

Registered behaviour follows the project's custom-element convention (native lifecycle, not
`onSwap`).

### 4. Serialization contract (`ts/elements/filter-bar.ts`)

**This requires NEW code, not the generic path.** The current serializer's `readWidget()` switch
has no `field-comparison` case (unknown kinds hit `default` → `null` → the widget is silently
skipped), and `setPath()` only assigns a single value at a single key — it cannot build a
top-level array nor the nested `AND`/`OR` tree. So a new branch is added, **modelled on the
existing `relation-bool` special-case** (which already sidesteps the generic path and calls
`appendAnd(filter, …)`):

- Add a `readFieldComparisonSet(element)` reader that returns the rows (`{left, right, modifier}`)
  plus the mode.
- Add an explicit branch in the per-widget loop (before the generic `readWidget` fallback, like
  the `kind === "relation-bool"` early-return) that emits:
  - **AND mode** → assign `filter["field_comparisons"] = [ {left, right, modifier}, … ]` (build
    the array directly; do not route through `setPath`'s scalar assignment). Each entry is
    AND-combined by the existing `field_comparisons` loop in `_apply_operators`.
  - **OR mode** → `appendAnd(filter, …)` a single isolated wrapper:
    ```json
    { "AND": [ { "OR": [ {"field_comparisons": [c1]}, {"field_comparisons": [c2]}, … ] } ] }
    ```
    Each comparison sits alone in its own node under one `OR` list, wrapped in a single `AND`
    sub-filter. This is required because top-level `OR` uses `q |= sub.to_q()` in
    `_apply_operators` and would otherwise OR the comparison group against every other top-level
    criterion (platform, status, …). The AND-wrapper isolates the OR group so it composes as
    `(other filters) AND (c1 OR c2 OR …)`.

Rows with any of left / operator / right unset are dropped silently (incomplete, not an error).

**Path note:** `data-path=["field_comparisons"]` is informational only for this widget (kept for
consistency with the self-describe contract). The field-comparison branch is handled entirely by
the special-case above and does **not** go through `resolve_path_kind` / `_criterion_class_for`,
which cannot resolve a list field (`field_comparisons` is `list[FieldComparisonCriterion]`, not a
single `_Criterion`) and would raise. No change to the path-resolution machinery is needed.

### 5. Validation parity

No new server validation. The UI prevents self-compare, cross-group, and out-of-group operators
by construction; `_apply_operators` remains the authority and still rejects hand-edited bad JSON.

### 6. Prefill / round-trip

The set reads from the bar's already-parsed `self.existing` (the canonicalized filter), and
recognizes both shapes it can emit:

- top-level `field_comparisons` (non-empty) → render those rows in **AND** mode;
- the `AND: [ { OR: [ {field_comparisons:[…]}, … ] } ]` wrapper of single-comparison nodes →
  render those rows in **OR** mode.

This round-trips losslessly (parse → render → serialize yields an equivalent filter). If both
shapes are somehow present (only via hand-edited JSON), AND mode takes precedence and the rows
are merged; this is a degenerate case, not a supported authoring path.

### 7. Wiring into the bars

Render the set from the shared `_FilterBarBase` so it appears uniformly in every bar whose
filter declares a `_comparison_model()` and whose model has **≥2 comparable columns within at
least one group** (the same-exact-group rule means two columns in different groups can never be
compared; all six models satisfy this today). Each bar
subclass declares its model (a class attribute) so the base can call `comparable_columns(model)`.
This covers `FilterBar` (Game), `SessionFilterBar`, `PurchaseFilterBar`, `DeviceFilterBar`,
`PlatformFilterBar`, `PlayEventFilterBar` in one place. Widget `Media` bubbles up the node tree
automatically; no view changes (`scripts=`) needed.

## Testing

- **`tests/test_filters.py`** — `comparable_columns()` per model: correct groups and labels;
  excludes relations, generated-without-output, pk/AutoField, JSONField. `_maybe_group_for`
  returns `None` where `_comparison_group_for` raises.
- **`tests/test_filter_bars.py`** — the set renders in each applicable bar; AND-mode and OR-mode
  **round-trip**: a filter JSON parses, the bar renders, and re-serializing produces the expected
  shape (`field_comparisons` for AND; `AND:[{OR:[…]}]` for OR).
- **`tests/test_components.py`** — `FieldComparisonSet` render and prefill from both shapes.
- **`e2e/test_widgets_e2e.py`** — pick left column → operator and right lists repopulate by
  group and exclude the left column; add/remove rows; mode toggle; Apply yields the expected
  `?filter=`. Concrete cases from the issue:
  - `Session.timestamp_end` `<` `timestamp_start`
  - `Purchase.date_refunded` `<` `date_purchased`
  - `Game.name` `contains` `sort_name`

## Out of scope / follow-ups to file

- **Nested AND/OR groups (full boolean query builder)** — generalize the single mode toggle into
  parenthesizable AND/OR groups, i.e. the app's general filter-tree UI. File as a GitHub issue.
- Independent of #162 (numeric/date `>=` / `<=` operators).
