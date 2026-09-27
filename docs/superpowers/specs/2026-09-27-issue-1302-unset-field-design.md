# The unset field

A bulk form states three things for each field:

| State | The person | The form posts |
|---|---|---|
| keep | leaves the field empty | an empty or absent field key |
| a value | fills the field | the field key with the value |
| none | presses ⊘ | `<name>-unset=1` |

The caller sets the placeholder of an empty field to the value that stays.
`<name>-unset` has priority over a value that the field also posts.

## Why not the picker's none row

With `none_label`, the picker × holds none. Then keep has no one-tap path.
A textarea has no none row, so ⊘ is the one way to state none. Therefore
`UnsetWidget` refuses a picker that also pins a none row.

## The element

`<unset-field>` joins one field and one ⊘ toggle through `SegmentedField`.
Its checkbox, `<name>-unset`, holds the pressed state.

The control is the first visible `input`, `textarea` or `select` in the
field: for a `SearchSelect`, the search box.

A press:

1. Keeps the value and the placeholder of the control.
2. Empties the control. Sets the placeholder to the none label.
3. Disables the control, and records if it was enabled. The hidden input of
   a picker stays enabled. The picker × ignores a press while its box is
   disabled.
4. Checks the checkbox. Sets `aria-pressed="true"`.
5. Sends `unset-field:change` with `{ name, unset }`.

A second press restores each item. A field without a control logs an error
and does not press. At connect, a checked box applies the
press and sends no event. The checkbox has `autocomplete="off"`.

A ⊘ field must not be a `params` source. `UnsetFieldsForm` refuses a picker
whose `params` name one.

## Look and access

The toggle is a segmented gray `ControlButton`. Its name is the none label;
`aria-describedby` points to the field label. When pressed, it has the brand
fill, also under `dark:`, where the hover text is stronger.

Without scripting, the element is not defined. `:defined` variants then hide
the toggle and show the checkbox in its place.

## The widget

`UnsetWidget(widget, *, none_label)` wraps one single-value `SearchSelect`
adapter or one text, number, textarea or single select control. It refuses a picker
with `params` or `commit_sole_option`, because search-select changes such a
value while the box is disabled.

- `render` gives the inner widget its shape and the field attrs.
- A posted `<name>-unset=1` makes `value_from_datadict` return `None`.
- A write on the wrapper to a name it does not own raises `AttributeError`.
  Write to `.widget`.
- Outside an `UnsetFieldsForm`, `value_from_datadict` and `render` raise
  `TypeError`, because there keep and none clean alike.

`UnsetFieldsForm` checks its ⊘ fields at each read, late fields included.
It refuses a required field and a none row. A bound form shows a press
again. `clean()` skips a field with errors. It gives each other ⊘ field one
value:

| Posted | `cleaned_data[name]` |
|---|---|
| `-unset` | the empty value of the field: `None` or `""` |
| an empty field | `KEEP` |
| a value | the cleaned value |

## Shape and media

`SearchSelect` and `native_control_class()` take a `ButtonShape`.

A widget can declare `component_media` (`MediaWidget`). `FormFields`
attaches it on the row and on the embedded path.

## Composite fields

A composite field keeps state in its own script. The native path cannot
empty it safely. Thus a composite element implements `UnsetTarget`:

- `unsetValue()` keeps the value, empties it, and disables its own controls.
- `restoreValue()` enables only the controls it disabled, then sets the kept
  value again.

`freezeControls(root)` in `ts/elements/unset-target.ts` disables each enabled
`input`, `select`, `textarea` and `button` in `root`, and returns the function
that enables them again.

`<unset-field>` uses the first element in the field that implements
`UnsetTarget`. It waits for each custom element in the field to be defined
before it applies a checked box at connect. Without a target, it uses the
native path: it empties and disables each visible `input`, `textarea` and
`select`, and sets the none label as the placeholder of the first.

| Widget | Path | Toggle |
|---|---|---|
| `SearchSelect` adapter | native, the search box | joined |
| text-like `Input`, `Textarea`, `Select` | native | joined |
| `HoursMinutesWidget` | native, both inputs | beside |
| `DatePickerWidget` | `<date-picker>` | beside |
| `DateTimeFieldWidget` | `<date-time-field>` | beside |
| `TemporalWidget` | `<temporal-field>` | beside |

A composite draws its own box, so its toggle stands beside it at the full
shape. `UnsetWidget` refuses every other widget: a checkbox, a radio list, a
file input, a hidden input and the time zone row, whose empty value is
already a state.
