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

## Which fields

| Widget | Path | Toggle |
|---|---|---|
| `SearchSelect` adapter, single value | native: the search box | joined |
| `Input` of an emptyable type, `Textarea`, `Select` | native | joined |
| `DatePickerWidget`, `DateTimeFieldWidget`, `TemporalWidget` | `UnsetTarget` | beside |

Emptyable input types are text, search, email, URL, tel, password, number,
date, time, datetime-local, month and week. A composite states
`draws_own_box`, so its toggle stands beside it at the full shape. A joined
toggle and field share one `SegmentedField`.

`UnsetWidget` refuses every other widget: a checkbox, radio, range, color,
file or hidden input, a `NullBooleanSelect`, a `MultiWidget`, a multi-select
and the time zone row. A picker with `params` or `commit_sole_option` is also
refused, because search-select changes its value while the box is disabled.

## The native path

A press:

1. Keeps the value and placeholder of each visible `input`, `textarea` and
   `select` in the field.
2. Empties each one. Sets the none label as the placeholder of the first.
3. Disables each one that is enabled. The hidden input of a picker stays
   enabled. The picker × ignores a press while its box is disabled.
4. Checks the checkbox. Sets `aria-pressed="true"`.
5. Sends `unset-field:change` with `{ name, unset }`.

A second press restores each item.

## Composite fields

A composite element implements `UnsetTarget`. `UnsetHold` in
`ts/elements/unset-target.ts` does the work for each one:

- `unsetValue()` keeps the value, empties it, and freezes the element. A
  second call does nothing.
- `restoreValue()` thaws, then commits the kept value. The commit makes each
  control compute its state again.

`freezeControls` disables each enabled control and makes the element inert,
because a script can enable a control again. Its undo reverses exactly this.

- A frozen date-time field ignores `setValue`. Its restore writes the exact
  kept wire value, but re-encodes it if its zone changed meanwhile.
- The temporal field clears its announcement on unset.

Limits: a composite shows no none label, and inert hides it from assistive
technology, so only the pressed ⊘ tells none from keep. Partly typed
segments are lost on a press. A copy arrow into a frozen field does nothing.

## Connect

The toggle is disabled, and a checked field is inert, until each custom
element in the field is defined. Then a checked box applies the press, with
no event. A press that finds no control keeps the checkbox checked. After
five seconds without definition, the element reports and uses the native
path. Every failure goes to `reportClientError`.

## Look and access

The toggle is a segmented gray `ControlButton`. Its name is the none label;
`aria-describedby` points to the field label. When pressed, it has the brand
fill, also under `dark:`. Without scripting, `:defined` variants show the
checkbox in place of the toggle.

## The form

`UnsetWidget` renders its inner widget with the field attrs and, when
joined, the shape of its place. A write on the wrapper to a name it does not
own raises `AttributeError`. Outside an `UnsetFieldsForm`, it raises
`TypeError`.

`UnsetFieldsForm` checks its ⊘ fields at each read, late fields included.
It refuses a required field, a none row, and a field whose empty input is
refused or cleans to a value, both as none and as keep. `clean()` gives each
⊘ field one value:

| Posted | `cleaned_data[name]` |
|---|---|
| `-unset` | the empty value of the field: `None` or `""` |
| an empty field | `KEEP` |
| a value | the cleaned value |

## Media

A widget can declare `component_media` (`MediaWidget`). `FormFields`
attaches it. The pickers, the composites and the time zone row declare it;
`UnsetWidget` adds its inner widget's. A page adds a script only for a field
that `FormFields` does not render.
