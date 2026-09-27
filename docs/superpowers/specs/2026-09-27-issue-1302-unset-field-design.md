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

A plain field takes the native path. Its controls are the visible `input`,
`textarea` and `select` elements in it: for a `SearchSelect`, the search box.

A press:

1. Keeps the value and the placeholder of each control.
2. Empties each control. Sets the none label as the placeholder of the
   first.
3. Disables each control, and records if it was enabled. The hidden input of
   a picker stays enabled. The picker × ignores a press while its box is
   disabled.
4. Checks the checkbox. Sets `aria-pressed="true"`.
5. Sends `unset-field:change` with `{ name, unset }`.

A second press restores each item. A field without a control logs an error
and does not press. The toggle stays disabled until each custom element in
the field is defined; then a checked box applies the press, with no event.
The checkbox has `autocomplete="off"`.

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
attaches it on the row and on the embedded path. The pickers and the three
composites declare it, and `UnsetWidget` adds the media of its inner
widget.

## Composite fields

A composite field keeps state in its own script. The native path cannot
empty it safely. Thus a composite element implements `UnsetTarget`:

- `unsetValue()` keeps the value, empties it, and disables its own controls.
- `restoreValue()` enables only the controls it disabled, then sets the kept
  value again.

`freezeControls(root)` in `ts/elements/unset-target.ts` disables each enabled
`input`, `select`, `textarea` and `button` in `root` and makes `root` inert.
Inert also holds a control that a script enables again, such as the temporal
copy button. The returned function reverses exactly this. A restore commits
after it thaws, so each control computes its state again.

`<unset-field>` uses the first element in the field that implements
`UnsetTarget`, else the native path.

- A frozen date-time field ignores `setValue`, so a copy arrow cannot write
  into it. Its restore writes the exact kept wire value.
- The temporal field clears its announcement on unset.
- A composite shows no placeholder. Only the pressed ⊘ tells none from keep.

| Widget | Path | Toggle |
|---|---|---|
| `SearchSelect` adapter | native, the search box | joined |
| text-like `Input`, `Textarea`, `Select` | native | joined |
| `DatePickerWidget` | `<date-picker>` | beside |
| `DateTimeFieldWidget` | `<date-time-field>` | beside |
| `TemporalWidget` | `<temporal-field>` | beside |

A composite draws its own box, so its toggle stands beside it at the full
shape. `UnsetWidget` refuses every other widget: a checkbox, a radio list, a
file or hidden input, a `NullBooleanSelect`, a `MultiWidget` and the time
zone row, where empty is already a state or no value.

`UnsetFieldsForm` also refuses a field whose empty input does not clean to an
empty value. `HoursMinutesField` is such a field: empty is zero.
