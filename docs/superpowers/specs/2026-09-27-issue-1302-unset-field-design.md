# The unset field

A bulk form states three things for each field:

| State | The person | The form posts |
|---|---|---|
| keep | leaves the field empty | an empty or absent key |
| a value | fills the field | the key with the value |
| none | presses ⊘ | `<name>-unset=1` |

`<name>-unset` has priority over a value that the field also posts. The
caller sets the placeholder to the value that stays.

A picker's none row (`none_label`) is refused. With it, × holds none, and
keep has no one-tap path.

## Which fields

| Widget | Path | Toggle |
|---|---|---|
| single-value `SearchSelect` adapter | native | joined |
| `Input` of an emptyable type, `Textarea`, `Select` | native | joined |
| `DatePickerWidget`, `DateTimeFieldWidget`, `TemporalWidget` | `UnsetTarget` | beside |

`UnsetWidget` refuses all other widgets: checkbox, radio, range, color, file
and hidden inputs, `NullBooleanSelect`, `MultiWidget`, multi-selects, the
time zone row, and pickers with `params` or `commit_sole_option`.

## The native path

A press empties and disables each visible `input`, `textarea` and `select`
in the field, and sets the none label as the first placeholder. A picker's
hidden input stays enabled. Its × does nothing while its box is disabled.
The press checks the checkbox, sets `aria-pressed`, and sends
`unset-field:change`. A second press restores each item.

## Composite fields

A composite implements `unsetValue()` and `restoreValue()` through
`UnsetHold`. Unset keeps the value, empties it, disables each control and
makes the element inert. A second unset does nothing. Restore thaws, then
commits the kept value. A date-time field keeps the exact wire, but
re-encodes it if its zone changed.

Limits: a pressed composite shows no none label, and inert hides it from
assistive technology. Partly typed segments are lost.

## Connect

Until each custom element in the field is defined, the toggle is disabled
and a checked field is inert. Then a checked box applies the press, with no
event. A press that finds no control keeps the box checked. After five
seconds, the element reports and uses the native path. Failures go to
`reportClientError`.

Without scripting, `:defined` variants show the checkbox in place of the
toggle.

## The form

`UnsetFieldsForm` checks its ⊘ fields at each read. It refuses a required
field and a field whose empty input is refused or cleans to a value.
`clean()` gives each ⊘ field one value:

| Posted | `cleaned_data[name]` |
|---|---|
| `-unset` | the empty value of the field |
| an empty field | `KEEP` |
| a value | the cleaned value |

An `UnsetWidget` outside this form raises `TypeError`. A write on the
wrapper to a name it does not own raises `AttributeError`.

## Media

A widget declares `component_media`. `FormFields` attaches it. A view adds
a script only for a field that `FormFields` does not render.
