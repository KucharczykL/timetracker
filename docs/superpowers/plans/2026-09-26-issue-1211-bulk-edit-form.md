# Bulk Edit form rework — plan

Spec: `docs/superpowers/specs/2026-09-25-issue-1211-bulk-edit-design.md`.

1. Heading, every act. `ActTitle.many` holds `{count}`; `for_count(n | None)`
   formats it, `None` reads "these". `__post_init__` refuses a `many` without
   exactly one `{count}` and a `one` with one. `ConfirmPage.message` optional;
   `ConfirmBatch` passes none when rows exist. Update every act's `many`,
   `_act_refused`, `tests/test_bulk_actions.py`, `test_bulk_runner.py`, and
   the e2e headings (move, device removal, selection actions, playthrough
   acts, game removal, edit).
2. Primitives. `SearchSelect(shape=)` replaces `rounded-base` on its box.
   `UnsetToggle(name, label, shape)`: a label around an `sr-only` checkbox,
   segmented gray, `has-[:checked]:` brand fill, `has-[:focus-visible]:` ring.
   `SegmentedRadios(name, legend, options, checked)`: a fieldset whose radios
   draw the same way. New `ban` icon (⊘) through `make gen-icons`.
3. `games/bulk_edit.py`. `EditStatement.note`; `EditJson.note`; `EditFields`
   gains `no_note`, `note`, and renames `no_device` to `unset_device`.
   `_composed` refuses value plus ⊘ per field (`DEVICE_AND_NONE`,
   `NOTE_AND_NONE`). Placeholders from `rows`: `current_device`,
   `current_emulated`, `current_note`. Undo reads `note_changed`.
   Preview adds Note.
4. Tests. Round trip with note; note refusals; offer renders ⊘ toggles,
   segmented radios and placeholders (agree / mixed / none); undo restores a
   note; e2e drives the ⊘ toggle for "No device" and undoes it.
5. `make lint-fix`, `make format`, full `make check` under the lock.
