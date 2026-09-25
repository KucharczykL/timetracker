# Plan: bulk Edit on the session list (#1211)

Spec: [Set one device across many sessions](../specs/2026-09-25-issue-1211-bulk-edit-design.md).
Wave: [Selectable tables](../specs/2026-09-19-selectable-tables-wave-design.md).

## Steps

1. **`describe_session` grows** (`games/writes/playersession.py`): keywords
   `idempotency_key`, `source_metadata`; returns `CommandResult`, as
   `move_session`. API callers (`games/api.py:896`, `:1091`) unchanged.

2. **Shared plain-manager resolve** (`games/bulk_sessions.py`):
   `session_of(actor, session_id) -> PlayerSession`, under
   `answered("session")`, `RowNotHeld` when absent. `bulk_move._session_of`
   and `bulk_finish._row` read it (finish keeps its own if it needs
   `select_related`; check).

3. **`games/bulk_edit.py`**:
   - `EditStatement(device: StatedDevice | None, emulated: bool | None)`,
     frozen; `__post_init__` refuses both `None` (`ValueError`);
     `encode()` JSON with absent keys; `decode()` raises `CommandRejected`
     with `STATEMENT_UNREADABLE` on bad JSON, unknown key, wrong type, empty.
   - Field names: `device_field(name)`, `no_device_field(name)`,
     `emulated_field(name)` suffixing `CHOICE_FIELD`.
   - `offer_edit`: `AsksNothing` for no rows; else `Control` with
     `SearchSelect(search_url="/api/devices/search", create_url=DEVICE_CREATE_URL,
     prefetch=DEFAULT_PREFETCH)`, `Checkbox` "No device", three `Radio`s.
   - `settle_edit`: `CHOICE_FIELD` present → decode; else compose. Refusals:
     `NOTHING_STATED`, `DEVICE_AND_NONE`, `DEVICE_UNREADABLE`, `DEVICE_GONE`
     (`Device.objects.for_library(library).filter(pk=…).exists()`).
   - `edit_one`: decode the choice under `answered` (None → `RowUnreadable`),
     `describe_session(..., source_metadata={"bulk": {"action": EDIT.name}})`.
   - `values_before(library, session_id, batch_id) -> EditStatement | None`:
     per fact, batch's own change event; earlier value from latest earlier
     event of `(created, <fact>_changed)`. `None` when the batch changed
     neither → refuse `NOT_EDITED_BY_THIS_BATCH`.
   - `edit_back`: `describe_session` with `values_before`.
   - Preview: Game, Day, Duration, Device, Emulated.
   - `EDIT = BulkAction(name="session.edit", label="Edit…",
     title=ActTitle("Edit this session", "Edit these sessions"),
     confirm_label="Save", color="blue", scope=session_scope,
     resolve=session_resolution, ...)`.

4. **Register** in `games/bulk_actions.py` foot import; tray order in
   `games/views/session.py`: Finish, Move, Edit, Reclassify, Remove.

5. **Docs**: wave doc step list marks #1211 shipped with a pointer to the
   spec; CLAUDE.md bulk runner paragraph gains one sentence.

## Tests

- `tests/test_bulk_edit.py` (new): statement round-trip and every `decode`
  refusal; offer (no rows, control names, none equals `CHOICE_FIELD`);
  settle (compose device, none, emulated, both; carried choice re-settles;
  each refusal; removed and foreign device); `edit_one` moved / unchanged /
  removed session refused; `values_before` from creation and from an
  earlier change, one fact only; undo end to end through the runner
  (device restored, emulated restored, second Undo unchanged, a row edited
  since is overwritten, a device removed since refuses the row);
  chunked batch replay idempotent.
- Update pins: `tests/test_session_list.py` tray labels (five, "Edit…"
  third), `tests/test_bulk_tray.py` `SESSION_ACTS`, `tests/test_bulk_runner.py`
  colour table gains `session.edit`.
- `e2e/test_bulk_edit_e2e.py`: select two sessions, Edit…, pick a device,
  Save, rows show it, toast Undo restores.

## Gotchas

- Controls never named `CHOICE_FIELD`: Move's picker is, and the confirmation
  then posts it raw.
- `DescribeSession` compares device first, so restating a removed device a row
  still holds is `Unchanged`, not refused.
- `transaction=True` for any test that POSTs through the runner.
- Run `make lint-fix` (import order) and `make format` before commit.
