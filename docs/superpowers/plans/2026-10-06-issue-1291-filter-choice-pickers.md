# Plan: filter controls in a SearchSelect (#1291)

Spec: `docs/superpowers/specs/2026-10-06-issue-1291-filter-choice-pickers-design.md`.

Iterate with `make test-ts TS_ARGS=…` and focused `make test ARGS=…` /
`make test-e2e ARGS=…`, each under the shared `flock`. Run `make ts` after
TS edits before e2e.

## Task 1 — SearchSelect gains what the pickers need

Files: `common/components/search_select.py`, `ts/elements/search-select.ts`,
`ts/elements/search-select.grouped.test.ts`, `tests/test_search_select.py`.

- `SearchSelect(search_aria_label="")` → `aria-label` on the box.
- `_grouped_option_rows`: no header for an empty label.
- `dynamic_options` also ships `<template data-search-select-template="header">`
  (a `_group_header("")`).
- Client `_searchSelectSetOptionGroups(groups)` and
  `SearchSelectElement.setOptionGroups(groups: SearchSelectOptionGroup[])`;
  `setOptions(items)` becomes `setOptionGroups([{label: "", options: items}])`.
  Headers clone from the header template; an empty label clones none.
- Export `SearchSelectOptionGroup` type.
- Tests: grouped empty label (vitest + pytest), header template present with
  `dynamic_options`, aria-label rendered.

## Task 2 — The accessor

Files: new `ts/elements/choice-control.ts`, `ts/elements/choice-control.test.ts`,
new `ts/elements/test-support/choice-picker.ts` (fixture builder: full
single-select markup incl. row/header templates, options, held value, marker).

- `ChoiceControl { element; read(); write(value): boolean; setChoices(groups); setDisabled(b) }`.
- `choiceOf(picker)`, `choiceControl(root, marker)`, `isChoicePick(event, marker)`.
- Wired test: `instanceof SearchSelectElement && wired`.
- Not wired write: row lookup by `data-value`; replace pills content with one
  hidden input named by host `name`; box `value` attr + property = `data-label`.
- Tests: read/write wired; write unoffered → false, held unchanged (wired and
  not); not-wired write then connect → held + label; part-less element →
  null/false, reported once; `isChoicePick` ignores `last=null`;
  cloned prototype twice → distinct listbox/status ids, `aria-controls` and
  `aria-describedby` resolve inside own clone.

## Task 3 — String and number widgets

Files: `common/components/filters.py` (`ChoicePicker`, `StringFilter`,
`NumberFilter`), `ts/elements/filter-widgets.ts`, `ts/elements/search-field.ts`
(header comment), `tests/test_filter_widgets.py`, `tests/test_field_widget.py`
if it pins `<select`, `ts/elements/quick-filter-bar.test.ts`,
`ts/elements/filter-group.test.ts` string/number fixtures.

- `ChoicePicker(marker, name, choices, selected, *, aria_label, placeholder, width_class, wrapper=False)`.
- String value input gets `data-string-value`; every `input[type="text"]` query in
  filter-widgets goes.
- Readers/writers via `choiceControl(element, marker)`; `null` modifier → reader
  answers `null` (string and number).
- Toggles take the widget root (`closest("[data-filter-widget]")`); signature
  `toggleStringFilterInput(root: HTMLElement, modifier: string | null)`.
- `setupModifierToggles` listens to `search-select:change` with `isChoicePick`.
- Gotcha: writer on a detached clone must call the toggle with the written
  modifier (not re-read through `select.value`).

## Task 4 — Facet panel behavior

Files: `ts/elements/behaviors/combobox.ts`, its test.

- Query `search-select[always-visible="true"]` and its box only.
- Test: a panel holding a nested non-always-visible picker focuses nothing.

## Task 5 — Comparison row

Files: `common/components/filters.py` (`RELATION_MATCH_CHOICES`,
`_field_comparison_row`), `ts/elements/field-comparison-set.ts`, its test,
`filter-group.test.ts` comparison fixtures, `tests/test_control_button_size.py`
if affected.

- Operator: wrapper `[data-fc-op]` + picker, `dynamic_options=True`, keeps
  `data-selected` on the wrapper. Quantifier: wrapper `[data-fc-quantifier]`
  (hidden toggle) + picker with `RELATION_MATCH_CHOICES`.
- `refreshRow`: `setChoices` groups Exact / By date / By year; disabled via
  `setDisabled`; adopt `data-selected` with `write`.
- `refreshQuantifier`: `write(saved)`; hidden → `write("ANY")`.
- `wireComparisonRowListeners`: drop native `change`; route
  `isChoicePick(event, "data-fc-op")` to right-options + quantifier refresh.
- `readComparisonRow` through the accessor.

## Task 6 — Relation rows

Files: `common/components/filters.py` (`relation_match_template()`,
`relation_field_template(filter_cls, model)` replacing
`relation_select_template`), `common/components/custom_elements.py`,
`ts/elements/filter-group.ts`, `filter-group.test.ts`, `tests/test_filter_widgets.py`.

- Templates `data-relation-match-template` (one) and `data-relation-field-template`
  + `data-model` (per reachable model), rows from the filter class's relation
  `FieldMeta` (same source as `model_field_registry`).
- Client: capture into `relationMatchTemplate` / `bundle.relationFieldTemplate`;
  clone, `uniquify`, `choiceOf(...).write(value)`; missing template → report,
  no picker. Drop `RELATION_MATCHES`/`RELATION_MATCH_LABELS` if unused.
- `onValueEvent`: `isChoicePick` for the two markers before the value-cell path.
- `focusout` inside a value cell → `refreshCompleteness`.
- pytest: per-model template rows == bundle relation keys; one match template.

## Task 7 — e2e

Files: `e2e/helpers.py` (`pick_in(picker_locator, value)`),
`e2e/test_string_filter_e2e.py`, `e2e/test_number_filter_e2e.py`,
`e2e/test_widgets_e2e.py`, `e2e/test_quick_filter_e2e.py`,
`e2e/test_filter_builder_e2e.py`.

- Replace `select_option` / `to_have_value` / `to_be_disabled` on the six
  markers with picker steps (disabled → the inner box).
- New: number facet open → no inner panel open; facet in ⋯ picks + applies;
  relation-field pick by Enter and by click; drop + leave → row complete.
- `tests/test_html_validity.py`: builder page and a list page render no
  `<select`.

## Task 8 — Visual check and sweep

- Dev server, screenshot builder comparison row, relation row, a number and
  a string facet; set widths; user spot check.
- Comments: `search-field.ts`, `custom_elements.py`, CLAUDE.md filter notes.
