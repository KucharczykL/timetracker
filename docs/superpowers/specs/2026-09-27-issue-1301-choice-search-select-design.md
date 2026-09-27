# A SearchSelect over a field's fixed choices

`ChoiceSearchSelectWidget` renders a `ChoiceField` or `TypedChoiceField` as a
single-select `SearchSelect`. The options are the field's `choices`. The
widget has no search URL, no create row and no prefetch. The client filters
the options that the page holds.

Parent: #481. First consumer: the Emulated field of bulk Edit (#1211).

## Why a sibling class

`SearchSelectWidget` keeps its contract: a search URL and a resolver. The new
widget is a sibling. The two share one base, which holds the common half of
`render` (the id, `clear_description_id`, `host_dropdown=True`) and
`value_from_datadict`.

The constructor admits only what fixed choices use:

```text
ChoiceSearchSelectWidget(*, placeholder=None, clearable=True,
                         autofocus=False, attrs=None)
```

`placeholder=None` renders "Choose…". A single class with an optional
`search_url` would admit pairs that mean nothing, for example `create_url`
without `search_url`.

Django's `ChoiceField.choices` setter writes `widget.choices` on the widget.
`ModelChoiceField` writes a `ModelChoiceIterator` there, also on today's search
widgets. `SearchSelectWidget` never reads `choices`, so a search field never
iterates its queryset.

## Hosting the widget

The widget reads `self.choices` and `self.is_required`. Django writes both only
while the field is built: `Field.__init__` stamps `is_required`, and the
`choices` setter writes `choices`. A widget assigned later has neither. The
repo swaps widgets after construction in several forms, and
`RegistrySettingsForm._build_field` builds its fields with a plain `Select`.

- Pass the widget to the field constructor. A caller that swaps the widget, or
  that changes `required` later, calls `host_choices(field, widget)`. The
  helper assigns the widget, then writes `widget.choices` and
  `widget.is_required` from the field.
- Assign `choices`; never change the list in place. `Widget.__deepcopy__` is
  shallow for a widget that is not a `ChoiceWidget`, so every form instance
  shares the list.

The widget renders to text, so its `Media` never bubbles. The hosting view
threads `dist/elements/search-select.js`, as `SESSION_FORM_SCRIPTS` does.
`host_dropdown=True` also needs `dist/elements/drop-down.js`. `Page()` loads it
through the navbar for a signed-in person only, so an anonymous page threads
it too.

## The empty choice

The field's `choices` state what the empty choice means: the entry whose key
is `""`, at any position. The widget has no `none_label` parameter.

| Field | Empty choice | Result |
|---|---|---|
| optional | present | `none_label=label`. The pinned row holds none, which posts `""`. |
| optional | absent | No none row. × leaves nothing picked, and the key is absent. |
| required | present | Dropped. The widget's placeholder shows. |
| required | absent | Plain picker. |

- A settings field keeps its `("", "Use site default (X)")` row as the none
  row. The settings adapter (#1289) reads it.
- A bulk field declares no empty choice. An empty field is "leave as it is",
  and the field's `placeholder` names what the rows keep ("Keep: mixed").
- A required field reads the empty choice as Django's "pick one" prompt, for
  example the `("", "---------")` choice that a model field without a default
  gives. The widget drops it and shows its own placeholder, so "---------"
  never shows. A required field cannot hold none.

An optional field with no empty choice cleans both `""` and an absent key to
its `empty_value`. A probe against Django confirmed this. `empty_value`
defaults to `""`; the settings fields and bulk Emulated pass `None`.

A re-rendered bound form whose key was absent shows none again where a none
row exists. Its next post sends `""`. Both clean to `empty_value`.

## Selected value

The widget compares `str(value)` with each choice key, as Django's `Select`
does. `None` reads as `""`, so it matches the empty choice. The consumer picks
keys that equal the `str()` of its initial values.

A bool field is a `TypedChoiceField` with keys `"True"` and `"False"` and
`coerce=lambda value: value == "True"`. `coerce=bool` is wrong, because
`bool("False")` is `True`. `NullBooleanField` is not a host: it has no
`choices`, and `apply_primitive_widget_classes` replaces its widget.

If no key matches, the widget follows #1288. A field with a none row shows
none. A field without one shows nothing picked.

## Refusals

The widget raises `ValueError` at render for:

- no `choices` attribute, for example under a `CharField`, or a widget
  swapped in without `host_choices`.
- grouped choices (`[("Group", [(value, label), …])]`). `option_groups` exists
  in the component, but no consumer needs it, and no test covers groups with
  a none row.
- a `ModelChoiceIterator` in `choices`. The check runs before any iteration,
  because iteration runs the queryset. A model field uses
  `SearchSelectWidget`.

A refusal surfaces when the page renders, not when the form is built.

`apply_primitive_widget_classes` skips the shared base, so the native classes
never reach either widget.

## Wire

No change from #1288. None posts the key with `""`. Nothing picked leaves the
key out. `value_from_datadict` returns `data.get(name)`.

## Tests

- `tests/test_choice_search_select.py`: the four rows of the table, a
  selected match and a miss, `None` as the empty choice, the three refusals
  rendered through `FormFields`, `host_choices` after a swap and after a change
  to `required`, and a `FormFields` round trip through `is_valid()` for a
  picked value, `""` and an absent key.
- `e2e/test_choice_search_select_e2e.py`: a synthetic page, in the pattern of
  `e2e/test_temporal_field_e2e.py` (`render_page`, `@csrf_exempt`,
  `ROOT_URLCONF` override), renders a real Django form through `FormFields`,
  threads both scripts, and posts to a view that echoes `cleaned_data`. It
  covers a pick by click, a pick by ↓ and Enter, a typed filter, and × on a
  field with a none row and on a field without one. It asserts the posted
  value.

No real field converts here. The settings fields need #1289. Emulated lands
with #1211. #1292 decides the small enums.

## Out of scope

- Multi-select over fixed choices.
- Scripting off: #1290.
- The ⊘ toggle of bulk forms: #1302.
