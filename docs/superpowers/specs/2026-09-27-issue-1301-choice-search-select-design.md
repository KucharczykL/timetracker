# A SearchSelect over a field's fixed choices

`ChoiceSearchSelectWidget` in `games/forms.py` shows a `ChoiceField` or a
`TypedChoiceField` as a single-select `SearchSelect`. The options are the
field's `choices`. The widget has no search URL, no create row and no
prefetch. The client filters the options on the page.

`SearchSelectWidget` is a different class. It searches a server endpoint. The
two classes share one base. The base gives the id, the label link of ×,
`host_dropdown=True` and `value_from_datadict`.

## The empty choice

The empty choice is the entry whose key is `""`. It can be at any position.

| Field | Empty choice | Result |
|---|---|---|
| optional | present | Its label is the none row. None posts `""`. |
| optional | absent | No none row. × leaves nothing picked. The key is not posted. |
| required | present | The widget drops it and shows its placeholder. |
| required | absent | A plain picker. |

The default placeholder is "Choose…". A settings field keeps its
`("", "Use site default (X)")` entry as its none row. A bulk field has no
empty choice. Its empty state is "leave as it is", and its placeholder shows
what the rows keep.

## Hosting

Django writes `choices` and `is_required` onto the widget only while it builds
the field. Give the widget to the field constructor. If you set the widget
later, or change `required`, call `host_choices(field, widget)`.

The widget renders to text, so its `Media` does not bubble. The page loads
`dist/elements/search-select.js`. A page without the navbar also loads
`dist/elements/drop-down.js`.

## Selected value

The widget compares `str(value)` with each key. `None` is `""`. A value that
no key names shows none, or nothing picked when there is no none row.

A yes/no field uses the keys `"True"` and `"False"` and
`coerce=lambda value: value == "True"`. Do not use `coerce=bool`, because
`bool("False")` is `True`. Set `empty_value=None`.

## Refusals

The widget raises `ValueError` when it renders:

- a field with no `choices`, for example a `CharField`.
- grouped choices.
- a `ModelChoiceIterator`. The widget checks this before it iterates, because
  iteration runs the queryset. Use `SearchSelectWidget` for a model field.

## Out of scope

- Multi-select over fixed choices.
- Scripting off: #1290.
- The ⊘ toggle of bulk forms: #1302.
