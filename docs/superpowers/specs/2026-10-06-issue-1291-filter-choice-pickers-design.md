# Filter controls in a SearchSelect

Issue #1291, part of #481 (workstream 3).

## Goal

Every native `<select>` that the filter builder and the quick bar render
becomes a single-select `<search-select>`. Every TypeScript reader and
writer of those controls goes through one accessor, `ChoiceControl`, and
never through `select.value`.

## The controls

| Control | Marker | Choices | Where it is built |
|---|---|---|---|
| String match mode | `data-string-modifier-select` | the field's string modifiers | `StringFilter` |
| Number comparison | `data-number-modifier-select` | the field's number modifiers | `NumberFilter` |
| Comparison operator | `data-fc-op` | set by the client from the left column | `_field_comparison_row` |
| Comparison quantifier | `data-fc-quantifier` | ANY, NONE, ALL | `_field_comparison_row` |
| Relation match | `data-relation-match` | ANY, NONE, ALL | new server template |
| Relation field | `data-relation-field` | the model's relation fields | new server template, one per model |

The marker sits on the `<search-select>` element through `host_data`. The
two comparison controls keep a wrapper `<div>` with the marker instead,
like the comparison operands (`data-fc-left`, `data-fc-right`), because
the client hides the quantifier and disables the operator as a whole.

Each picker is built by one Python helper, `ChoicePicker`, in
`common/components/filters.py`. It calls `SearchSelect` with:

- `clearable=False`. A filter control always holds a choice; no none row.
- `revert_on_leave=True`. A keystroke drops the held choice; leaving
  without a pick restores it.
- `search_aria_label`, the name `FilterSelect` already uses, now also a
  `SearchSelect` parameter: it writes `aria-label` on the search box. The
  native selects had no accessible name but the quantifier's
  ("Quantifier"). The labels: "Match mode", "Comparison", "Operator",
  "Quantifier", "Relation match", "Relation".
- a placeholder: "Choose…" (#1292's word) on the four controls that always
  hold a choice; "—" on the operator, which holds nothing until a left
  column is picked; "a relation…" on the relation field, which holds
  nothing until a person picks.
- a width: the native selects sized to their content inside the
  comparison grid's `auto` column and the relation header's `flex-wrap`
  row. A picker's box has no content width, so each states one on its
  wrapper: `w-full` for the two modifiers (as `SELECT_CLASS` had), a fixed
  `w-*` for the operator, the quantifier and both relation pickers, chosen
  on a screenshot of the running builder.

One source names each choice list. `RELATION_MATCH_CHOICES` (Python:
ANY "any", NONE "none", ALL "all") feeds both the quantifier and the
relation match; the client's `RELATION_MATCH_LABELS` goes. The relation
field rows render from the same `FieldMeta` the `models` prop carries, and
a pytest pins that each model's template offers exactly the relation keys
of its bundle.

## The accessor

`ts/elements/choice-control.ts` exports:

- `choiceOf(picker): ChoiceControl` — the accessor over one
  `<search-select>`.
- `choiceControl(root, marker): ChoiceControl | null` — the picker that
  carries `marker`, or sits inside an element that carries it, under
  `root`.
- `isChoicePick(event, marker): boolean` — the event is a
  `search-select:change` from such a picker and states a pick
  (`detail.last` is not null). A keystroke drop is no pick.

`ChoiceControl` has these members:

| Member | Wired element | Element not yet wired |
|---|---|---|
| `read()` | the held value; `null` when nothing is held | the same, read from markup |
| `write(value)` | `holdValue(value)` | rewrites the hidden input and the box text from the row that offers `value` |
| `setChoices(groups)` | replaces the rows | throws |
| `setDisabled(disabled)` | the search box | the search box |

The wired path delegates to the element (`holdValue`, `offers`,
`setOptionGroups`) and reads through `heldValue` (`search-select.ts`), the
reader the operands' `operandValue` also moves onto. A `<search-select>`
without `[data-search-select-pills]` reads `null` and writes nothing,
reported once through `reportClientError`. `ts/setting-control.ts` keeps
its own class: its snapshots and none semantics are a setting's.

"Wired" means `element instanceof SearchSelectElement && element.wired`. A
node cloned from `template.content` is not upgraded until it connects, so
the not-wired path touches markup only, never the element's methods.

`write` is silent. It answers `false` and changes nothing when no row
offers `value`; on a wired element it asks `offers(value)` first, because
`holdValue` clears an unoffered value. The not-wired path exists because
the builder hydrates a value cell on a detached clone (`buildValueCell` →
`writeLeafWidget`) and builds relation rows detached. It writes one
`<input type="hidden">` in `[data-search-select-pills]`, named by the
host's current `name` (after `uniquify`), with no
`data-search-select-none`, and sets the box's `value` attribute and
property to the row's `data-label`. Initialisation reads that input as the
held value and the box text as its label (`initWidget`), so a markup write
before connection is the held state after it.

`setChoices` takes groups (`{label, options}`). A group with an empty label
renders no header, on the client and in `_grouped_option_rows` alike;
`search-select.grouped.test.ts` gains that case. `SearchSelect` gains this as `setOptionGroups`, the
grouped sibling of `setOptions`; with `dynamic_options` the server ships a
header `<template>` beside the row template. The comparison operator keeps
its three groups: Exact, By date, By year.

## Readers

- `filter-widgets.ts`: `readStringWidget`, `readNumberWidget` and their
  writers read the modifier through the accessor. A picker that holds
  nothing (mid-edit) makes the leaf incomplete: the reader answers `null`.
  `setupModifierToggles` reacts to `isChoicePick`, and the toggles find
  their inputs under `[data-filter-widget]`, not `.flex-col`.
- The string value input carries `data-string-value`. The picker's search
  box is also `<input type="text">` and renders first, so no reader,
  writer or toggle selects `input[type="text"]` any more.
- `field-comparison-set.ts`: operator and quantifier go through the
  accessor. `fillSelect` and its `<option>` building go away; the operator
  is set through `setChoices`. The `data-selected` seed stays: the seed is
  written on a detached row and `refreshRow` adopts it after connection.
  The operator's native `change` listener goes: a search box fires
  `change` on blur after typing. The row's `search-select:change` handler
  routes an operator pick (`isChoicePick(event, "data-fc-op")`) to the
  right-operand and quantifier refresh.
- `filter-group.ts`: relation rows clone the per-model templates, write the
  held value through the accessor, and route `isChoicePick` to
  `handleRelationField` and `handleRelationMatch`. The bare
  `element("select")` fallback goes; a missing template is a defect,
  reported, and the row renders without the picker.
- `filter-group.ts` also refreshes completeness on `focusout` inside a
  value cell. A keystroke drop emits a change with no pick and marks the
  row incomplete; `revert_on_leave` restores the choice silently on
  `focusout` (the picker's own listener runs first), so the row would
  stay incomplete until the next edit. The restore stays silent, because
  `<live-setting-fields>` would save on a restore that emitted.
- `quick-filter-bar.ts` already reads through `readLeafWidget`.

## The facet panel

A quick-bar facet is a `<drop-down behavior="combobox">`. On open the
behavior refetches and focuses the panel's first `<search-select>`. A
number or string facet now holds a picker nested in its own
`<drop-down>`, and focusing its box opens its list. The behavior therefore
acts only on the panel's own picker, `search-select[always-visible="true"]`
(the `FilterSelect` panel and `PresetSelect`). A number or string facet
focuses nothing on open, as before.

Nesting is sound: `pushSurface` keeps an open surface that contains the
new one, and a facet moved into ⋯ carries its inner `<drop-down>`.

## Cloned prototypes

The builder clones each picker from a `<template>` and `uniquify` suffixes
its `name`. A picker assigns its listbox id, status id, `aria-controls`
and `aria-describedby` at initialisation, from a counter. A test clones one
prototype twice, connects both, and asserts that every id differs and that
each reference resolves inside its own clone.

## Out of scope

- `games/views/settings_kit_preview.py` renders a native select. It is a
  DEBUG-only preview page.
- The epic's workstream 4 audit (#481).

## Tests

- vitest: one shared fixture builder renders a full single-select picker
  (box, pills, rows, row and header templates), in
  `ts/elements/test-support/`; every converted fixture uses it.
- vitest: the accessor, wired and not wired; cloned prototypes;
  `setOptionGroups`; the converted reader, writer and toggle cases in
  `filter-widgets`, `field-comparison-set`, `filter-group` and
  `quick-filter-bar`.
- pytest: the six controls render `<search-select>`; the builder page and a
  quick bar render no native `<select>`.
- e2e: the string, number, widgets, quick filter and builder suites pick
  through the picker; `tests/test_filter_tree_contract.py` stays green
  unchanged. New cases: opening a number facet opens no inner list; a
  facet in ⋯ picks a modifier and applies; a relation-field pick by
  keyboard and by click leaves the builder usable; a dropped and restored
  modifier leaves the row complete. Tab inside a facet panel closes the
  facet (pre-existing; `combobox` sets no `keepOpenOnTab`), so these
  cases pick by click.
- A screenshot of the comparison row and a relation row checks the widths.
- `tests/test_filter_widgets.py` pins one relation-field template per
  model and one relation-match template.

## Sweep

`ts/elements/search-field.ts`'s header, the relation template comment in
`common/components/custom_elements.py`, and CLAUDE.md name the native
selects; each is rewritten.
