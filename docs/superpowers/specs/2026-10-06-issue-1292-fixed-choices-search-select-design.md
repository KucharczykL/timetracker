# Fixed choices render the picker

Parent: #481. Issue: #1292.

## The rule

A fixed-choice field renders `ChoiceSearchSelectWidget`. The form
framework applies the rule. Each declaration does not.

`apply_primitive_widget_classes` (`games/forms.py`) replaces a widget
when all of these are true:

- The field is a `ChoiceField`.
- The field is not a `ModelChoiceField` or a `MultipleChoiceField`.
- The widget is exactly `forms.Select`. A subclass stays.

The replacement takes a copy of the old widget's `attrs`.
`host_choices` then gives it the field's choices and `required`. The
adapter refuses an attr that has no home, so a lost attr fails at
render.

The replacement takes `clearable=WITH_NONE_ROW`: it shows × only when
the field is optional and its choices hold `""`, decided at render. A
native select without a none row cannot be emptied, so the picker
cannot be emptied either. The replacement sets `revert_on_leave`: a
keystroke drops the held value, and focus that leaves without a pick
puts the value back. Enter in the search box never submits the form.

A form that changes `required` after the build calls `host_choices`
again.

## Required

`SearchSelect(required=True)` writes `aria-required="true"` on the
search box. The adapter forwards the `required` attr Django renders, so
a form with `use_required_attribute = False` marks nothing. The browser
does not block the submit. The server refusal is the only check.

## Forms

- `EntryEndForm` seeds `way` with `EndWay.UNSTATED`. A picker holds
  nothing until a person picks.
- `BulkAccessEndForm` offers no empty row. The placeholder says
  "Choose…".

## Readers

- `<game-addon>` reads the kind `<search-select>`. It listens on that
  element, so the parent picker's events do not reach it. A change with
  no value is a keystroke, not a pick, and moves nothing.
- `ts/setting-control.ts` reads inputs, textareas and the picker. It
  refuses a native select, which only a `MODEL` setting would render.

## The temporal shape

When the segments can hold the value, `<temporal-field>` derives the
shape. The shape is then a hidden input with
`data-temporal-input="kind"`, and a dated value needs the element.

When the segments cannot hold the value, no element runs. The shape is
then a `SearchSelect` over `TEMPORAL_DRAFT_KIND_LABELS`, with no × and
with `revert_on_leave`. A refused shape is one more row.
`TemporalWidget.component_media` carries the picker's modules.

## Out of scope

- The release row's platform: #1222.
- The filter builder and the quick bar: #1291.

## Tests

- `tests/test_choice_search_select.py`: the swap, ×, `required`, attrs,
  and the widgets the swap leaves alone.
- `tests/test_html_validity.py`: the listed form pages render no native
  select but the release platform.
- `tests/pickers.py` reads a picker's held value from markup.
- e2e: cloned edition kinds, a keystroke in Kind, and a refused date's
  shape picker.
