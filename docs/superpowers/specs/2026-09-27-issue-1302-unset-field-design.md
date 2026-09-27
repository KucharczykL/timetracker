# The unset field

A bulk form states three things for each field:

| State | The person | The form posts |
|---|---|---|
| keep | leaves the field empty | an empty or absent field key |
| a value | fills the field | the field key with the value |
| none | presses ⊘ | `<name>-unset=1` |

The placeholder of an empty field names the value that stays. `<name>-unset`
wins over a value that the field also posts.

## Why not the picker's none row

With `none_label`, the picker × holds none. Then keep has no one-tap path.
A textarea has no none row. Thus `UnsetWidget` refuses a picker that pins a
none row.

## The element

`<unset-field>` joins one field and one ⊘ toggle through `SegmentedField`.
Its checkbox, `<name>-unset`, holds the pressed state.

The control is the first `input:not([type=hidden])`, `textarea` or `select`
in the field. For a `SearchSelect`, it is the search box.

A press:

1. Keeps the value and the placeholder of the control.
2. Empties the control. Sets the placeholder to the none label.
3. Disables the control if it is enabled. The hidden input of a picker stays
   enabled.
4. Checks the checkbox. Sets `aria-pressed="true"`.
5. Sends `unset-field:change` with `{ name, unset }`.

A second press puts back each item. At connect, a checked box applies the
press and sends no event. The checkbox has `autocomplete="off"`.

A disabled control is not in `FormData`. Thus a ⊘ field cannot be a `params`
source of a picker.

## Look and access

The toggle is a segmented gray `ControlButton`. Its name is the none label,
and `aria-describedby` points to the field label. The pressed toggle has the
brand fill. `dark:aria-pressed:solid-brand` is necessary, because the dark
hover text is stronger than a bare pressed fill.

Without scripting, the element is not defined. `:defined` variants then hide
the toggle and show the checkbox in its place.

## The widget

`UnsetWidget(widget, *, none_label)` wraps one single-value `SearchSelect`
adapter or one text, number, textarea or select control. It refuses a picker
with `params` or `commit_sole_option`, because search-select changes such a
value while the box is disabled.

- `render` gives the inner widget its shape and the field attrs.
- A posted `<name>-unset` makes `value_from_datadict` return `None`.
- A write to an attribute of the inner widget raises `AttributeError`. Write
  to `.widget`.
- At render, a required field and a none row are refused.

`UnsetFieldsForm` reads the prefixed `-unset` key at construction. A bound
form shows a press again. `clean()` skips a field with errors. It gives each
other ⊘ field one value:

| Posted | `cleaned_data[name]` |
|---|---|
| `-unset` | the empty value of the field: `None` or `""` |
| an empty field | `KEEP` |
| a value | the cleaned value |

## Shape and media

`SearchSelect` and `native_control_class()` take a `ButtonShape`.

A widget can declare `component_media`. `FormFields` attaches it. A widget
can also declare `requires_form`. `FormFields` then refuses a form of a
different class.
