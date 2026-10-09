# A tri-state checkbox for a flag on a bulk form

Issue #1293.

## Scope

Each flag on a bulk Edit form is a `<tri-state-checkbox>`. The Games
list has three: Mastered, Unfinished lists and Dropped figures. The
session list has one: Emulated.

## States

The box starts at the held state of the selected rows.
`held_flag(rows, value)` in `games/bulk_edit.py` gives it: `checked`,
`unchecked`, or `mixed` where the rows differ.

- Rows that agree: a press toggles checked and unchecked.
- Rows that differ: a press steps mixed, checked, unchecked, mixed.

The box has no name. One hidden input carries the field's name. It posts
`""` while the state equals the held state. Otherwise it posts the
checked word or the unchecked word. `""` keeps the rows.

Limit: if the rows change after the offer, the box cannot state the
value it shows. A form that states nothing else is refused.

## The element

`TriStateCheckbox()` (`common/components/tri_state_checkbox.py`) renders
the host, a hint, the box and the hidden input. The server sets
`checked` on the box where the shown state is checked.

`ts/elements/tri-state-checkbox.ts` reads its state from the hidden
input on connect: `""` is the held state. On each `change` it sets
`checked` and `indeterminate` from its own state. The browser toggle
does not decide. Both inputs carry `autocomplete="off"`.

The hint beside the box says:

| State | Hint |
|---|---|
| mixed | Keep: mixed |
| equal to held | Keep |
| differs from held | Will change |

The posted words and the hints are props. The TypeScript holds no
spelling of them.

## The look

Every checkbox uses `CHECKBOX_LOOK_CLASS`: a 24 px rounded square. The
class also draws the mixed dash on the check mark's grid, so the dash
replaces the Flowbite dash. The tri-state box, the table's selection
boxes and a form's boxes look the same.

## Accessibility

The native checkbox gives the role, focus, Space and the label click.
The browser exposes `indeterminate` as `aria-checked="mixed"`. A screen
reader can skip a changed description, so "Will change" can go unheard.

## The form side

`flag_field(label)` returns a `TypedChoiceField` over `FLAG_CHECKED` and
`FLAG_UNCHECKED`, with `empty_value=None`. The field refuses an unknown
value. The form sets `widget.held` from its rows.

`TriStateCheckboxWidget` (`games/forms.py`) is a plain `forms.Widget`.
It takes the words as an argument, because `games/forms.py` does not
import the bulk modules. `value_from_datadict` returns the posted string
as it came. `input_type = "checkbox"` puts it on the checkbox row of
`FormFields`. Its id goes on the box, so the label reaches it.
`apply_primitive_widget_classes` skips it.

The bulk flow renders the form unbound only. No field error renders.
