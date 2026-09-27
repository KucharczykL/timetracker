# Bulk Edit states the playthrough — plan

Spec: `docs/superpowers/specs/2026-09-27-issue-1310-bulk-edit-moves-design.md`.

1. `games/bulk_move.py` becomes the move of one row, no act: `move_row(actor,
   session, target, *, act, idempotency_key, correlation_id) -> RowOutcome`,
   `move_back_row(actor, session_id, *, act, undoes, ...)`, `run_before`,
   `moved_by(library, session_id, batch_id) -> bool`, `ANOTHER_GAME`,
   `TARGET_GONE`, run label cell. `_source(act)`; both log lines name `act`.
   Drop `MOVE`, `TARGET`, `offer_target`, `settle_target`, `move_scope`,
   `MOVE_PREVIEW`. Reword `NO_EARLIER_RUN` / `SOURCE_TAKEN_AWAY` to name the run.
2. `games/bulk_sessions.py`: `labelled_session_resolution` (from
   `move_resolution`), `RUN_LABEL_ATTRIBUTE`, `run_label_cell`.
3. `games/forms.py`: export `run_options` (was `_run_options`).
4. `games/bulk_edit.py`: `EditStatement.playthrough`, `EditJson.playthrough`,
   decode; `BulkEditForm.playthrough`; offer drops the field and adds the
   sentence row for several games; settle checks the run; `edit_one` order and
   outcome; `edit_back` order; preview column; resolve.
5. Menus: tray without Move (`games/views/session.py`), row menu without Move
   (`games/views/session_menu.py`); `games/bulk_actions.py` foot import.
6. Tests: `tests/test_bulk_move.py` → per-row helpers only, or folded into
   `tests/test_bulk_edit.py` (move-only batch, mixed batch, undo both, bucket
   removed and restored, another game refused, multi-game offer, crafted run on
   multi-game, chunk twice). Tray/menu/list label tests. `e2e/test_bulk_move_e2e.py`
   → drive Edit's Playthrough field. `tests/test_session_writes.py:540` name.
   Retired-act Undo test already exists (`tests/test_bulk_runner.py`).
7. Docs: CLAUDE.md paragraph, wave spec line, visual-conventions mention.
8. `make lint-fix`, `make format`, full `make check` under the lock; `gh stack submit`.
