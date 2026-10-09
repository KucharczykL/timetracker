# Plan: tri-state checkbox (#1293)

Spec: `docs/superpowers/specs/2026-10-09-issue-1293-tri-state-checkbox-design.md`.

## Task 1 — element contract and component

- `common/components/custom_elements.py`: `TriStateCheckboxProps`
  (`name`, `held: Literal["checked","unchecked","mixed"]`, `checked_word`,
  `unchecked_word`, `hint_mixed`, `hint_kept`, `hint_changed`);
  `register_element("tri-state-checkbox", "TriStateCheckbox", …)`;
  builder `_TriStateCheckbox`. `make gen-element-types`.
- `common/components/tri_state_checkbox.py`: `type TriState`,
  `TriStateCheckbox(*, name, box_id, held, stated, words, hints)` →
  host `inline-flex items-center gap-2` with hint span
  (`data-tri-state-hint`, id `<box_id>-hint`, `text-body-subtle`), bare
  `Input(type="checkbox")` (`data-tri-state-box`, `CHECKBOX_LOOK_CLASS`,
  `autocomplete="off"`, `aria-describedby`, `checked` when shown checked),
  hidden input (`data-tri-state-value`, `autocomplete="off"`). Media
  `dist/elements/tri-state-checkbox.js`.
- Tests `tests/test_tri_state_checkbox.py`: three held states, stated over
  held, hint words, hidden value.

## Task 2 — TypeScript element

- `ts/elements/tri-state-checkbox.ts`: read props; state from hidden value
  on connect; `change` listener: next state (agree: toggle; mixed held:
  mixed→checked→unchecked→mixed), write `checked`/`indeterminate`, hidden
  value, hint text. Bind once (reconnect). `reportClientError` on missing
  parts.
- `ts/elements/tri-state-checkbox.test.ts`: both cycles via `click()`,
  hidden value, hint, restored value on connect.

## Task 3 — widget and field

- `games/forms.py`: `TriStateCheckboxWidget(forms.Widget)`,
  `input_type = "checkbox"`, `held` default mixed, raw
  `value_from_datadict`, `component_media`, render through
  `TriStateCheckbox`; add to `apply_primitive_widget_classes` exclusion.
- `games/bulk_edit.py`: `FLAG_CHECKED = "True"`, `FLAG_UNCHECKED = "False"`,
  `flag_field(label)`, `held_flag(rows, value) -> TriState`.
- Tests: field cleaning (`""`, `True`, `False`, `maybe`), no input class
  after mixin, words equal choice keys.

## Task 4 — the four fields

- `games/bulk_game_edit.py`: mastered + two Visibility fields via
  `flag_field`; `__init__` sets `widget.held`; drop `FlagChoices`,
  `_*_CHOICES`, `_mastered_shown`, `LabeledChoice` import; keep
  `_excluded_shown`.
- `games/bulk_session_edit.py`: emulated likewise; drop
  `_EMULATED_CHOICES`, `_emulated_shown`.
- Move tests: `tests/test_bulk_game_edit.py:242-247`,
  `tests/test_bulk_session_edit.py:295-306`.

## Task 5 — e2e

- `e2e/test_bulk_game_edit_e2e.py`, `e2e/test_bulk_edit_e2e.py`: press the
  box (`get_by_role("checkbox", name=…)`).
- New mixed-cycle e2e: held mixed, Space → checked → unchecked → mixed
  (`to_be_checked(indeterminate=True)`), hint text, save states it.

## Gotchas

- `make ts` before e2e. `make gen-element-types` after the props.
- Run Mastered label `for` = `id_choice-mastered`; the id sits on the box.
- Spot check on dev server with the user before the gate.
