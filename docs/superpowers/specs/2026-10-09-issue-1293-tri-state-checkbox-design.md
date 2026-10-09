# A tri-state checkbox for a flag on a bulk form

Issue #1293. Follow-up from #1211; precondition met by #1270, which put
three flags on the Games list's Edit.

## Outcome

Every boolean on a bulk Edit form is a `<tri-state-checkbox>`: Mastered,
the two Visibility flags (`excluded_from_unfinished`,
`excluded_from_dropped`) on the Games list, and Emulated on the session
list. Each replaced a two-row `ChoiceSearchSelectWidget` whose placeholder
said `Keep: …`.

## States

The box starts at what the selected rows hold: checked, unchecked, or
mixed where they differ (`held_flag(rows, value)` in
`games/bulk_edit.py`, beside `keeping`).

- Rows that agree: a press toggles checked and unchecked. Mixed is not
  offered, because the rows are not mixed.
- Rows that differ: mixed → checked → unchecked → mixed.

The box posts nothing. One hidden input carries the field's name and
posts `""` while the state equals the held state, else `True` or
`False`. `""` keeps. A state equal to an agreeing held state posts `""`
as well; stating it would move nothing. Deliberate limit: where held
went stale since the offer, the shown value cannot be stated; a form
stating nothing else answers `NOTHING_STATED`.

The element reads its state on connect from the hidden input: `""` is
held, `True`/`False` that state. Both inputs carry `autocomplete="off"`,
as the check-all does, so a restored form state never stands beside a
`held` that disagrees.

`change` drives the cycle. The element keeps its own state and, after
each `change`, writes `checked` and `indeterminate` from it, so the
browser's own toggle never decides. Under mixed, `checked` is false.
The server renders `checked` on the box where held is checked, so the
box shows the held value before upgrade.

The two posted words are props (`checked_word`, `unchecked_word`),
taken from the constants `flag_field`'s choice keys are built from. The
TypeScript holds no spelling of `True` or `False`.

## The look

The visible box is a bare nameless `Input(type="checkbox")` with
`CHECKBOX_LOOK_CLASS`, as the check-all is (`Checkbox()` requires a
name). Flowbite's `[type='checkbox']:indeterminate` rule paints the
brand-filled dash, the same one the selectable table's check-all shows. So the
tri-state looks like every other checkbox in the app by construction.

The check-all box is not this component. It derives mixed from marked
rows, never steps into it on a press, and posts nothing.

The host is `inline-flex items-center gap-2`: hint, then box. A muted
hint (`text-body-subtle`) stands beside the box, linked by `aria-describedby`:

| State | Hint |
|---|---|
| mixed | Keep: mixed |
| equal to held | Keep |
| differs from held | Will change |

The words live in Python and reach TypeScript as props.

## Accessibility

The native checkbox gives `role="checkbox"`, focus, Space and the label
click. A browser exposes `.indeterminate` as `aria-checked="mixed"`, so
no ARIA is hand-written. `indeterminate` has no HTML attribute: the
element sets it on connect. Before upgrade a held-mixed box shows
unchecked and the hidden input still posts `""`.

Screen readers may not reread a changed description, so "Will change"
may go unheard. An Orca pass runs before merge, as the issue asks.

## The form side

`flag_field(label)` (`games/bulk_edit.py`) returns a `TypedChoiceField`
over `True`/`False`, `empty_value=None`, with
`TriStateCheckboxWidget`. An unknown value is refused as an invalid
choice, as before; a `NullBooleanField` would clean it to keep in
silence. The form sets `widget.held` from its rows.

`TriStateCheckboxWidget` (`games/forms.py`) is a plain `forms.Widget`,
never `CheckboxInput`, whose datadict methods turn the post into a
bool. Its `value_from_datadict` returns the posted string as it came;
the field's choices and `coerce` decide. It declares `input_type = "checkbox"`, so `FormFields` lays it
out on its checkbox row (label left, box and hint right), and
`component_media`. Its id goes on the visible box, so the label's `for`
reaches it. `held` defaults to mixed, which posts `""`.
`apply_primitive_widget_classes` would stamp the text-input look onto
its attrs: it joins that function's exclusion tuple.

The bulk flow renders the form unbound only: `offer_edit` with rows,
and a reconfirmation offers it again. A field error therefore never
renders here, and no `aria-invalid` is written.

## Files

- `common/components/tri_state_checkbox.py`: `TriStateCheckbox()`.
- `common/components/custom_elements.py`: `TriStateCheckboxProps`,
  `register_element("tri-state-checkbox", …)`; `make gen-element-types`.
- `ts/elements/tri-state-checkbox.ts` and its vitest.
- `games/forms.py`: the widget.
- `games/bulk_edit.py`: `flag_field`, `held_flag`.
- `games/bulk_game_edit.py`, `games/bulk_session_edit.py`: the four
  fields; `FlagChoices`, the `_*_CHOICES` tuples, `_mastered_shown`,
  `_emulated_shown` and the `LabeledChoice` import go. `_excluded_shown`
  stays: the confirmation preview reads it.
- Docs: the #1211 and #1270 specs, which describe the flags as
  `Keep: …` pickers.

## Tests

- Render: held checked/unchecked/mixed, hint text, hidden value,
  `autocomplete="off"`, no text-input class after the mixin runs.
- Form: `""` keeps, `True`/`False` state, `maybe` refused; the props'
  words equal the choice keys.
- vitest: both cycles through `click()`, the hidden value, the hint, a
  restored hidden value on connect.
- e2e: Mastered and Emulated pressed through the box; one mixed cycle
  by Space, read through `aria-checked`-equivalent `indeterminate`.
- Break and move: `tests/test_bulk_game_edit.py` (`Keep: Not mastered`,
  the two `count(...) == 2`), `tests/test_bulk_session_edit.py`
  (`…emulated_is_a_picker`), `e2e/test_bulk_game_edit_e2e.py` and
  `e2e/test_bulk_edit_e2e.py` locators. `test_bulk_session_edit.py`'s
  `count('placeholder="Keep: mixed"') == 2` stays: device and note.

## Follow-up issues to file

None.
