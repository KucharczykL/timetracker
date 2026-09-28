# Set status on many games — plan

Spec: `docs/superpowers/specs/2026-09-28-issue-1270-bulk-set-status-design.md`.
Wave: `docs/superpowers/specs/2026-09-19-selectable-tables-wave-design.md`.

0. Rebase onto `origin/main`.
1. `games/reads/playergame_status.py`: `status_before(library, player_game_id,
   batch_id) -> PlayerGameStatus | None` over `aggregate_events`; family is
   `PLAYERGAME_CREATED` + `PLAYERGAME_STATUS_CHANGED`, shaped like
   `_earlier` in `games/bulk_edit.py`. No creation before the batch's event →
   `RowUnreadable` naming library, key and sequence.
   Tests first (`tests/test_playergame_status_read.py`): none changed → None;
   earlier word; creation only → UNPLAYED; forged stream with no creation →
   `RowUnreadable`; two batches → reads the one asked.
2. `games/bulk_playthrough_acts.py`: `_status_before` delegates; keep its
   `None` = skip. `tests/test_bulk_playthrough_acts.py` stays green unedited.
3. `games/bulk_status.py`:
   - `status_resolution(library, keys) -> Resolution[Game]`:
     `Game.objects.tracked_by(library).filter(pk__in=…)
     .select_related("platform").order_by("sort_name", "id")`; lost →
     `GAME_GONE` (import from `bulk_removal`).
   - `StatusForm(PrimitiveWidgetsMixin, forms.Form)` built with one field
     named `field_name` in `__init__` (see memory: dynamic fields go into
     `self.fields` after `super().__init__`, then
     `apply_primitive_widget_classes`); `ChoiceField(choices=PlayerGameStatus
     .choices, required=True, error_messages={"required": CHOOSE_A_STATUS,
     "invalid_choice": CHOOSE_A_STATUS})`, `ChoiceSearchSelectWidget(
     placeholder=…)`. Placeholder `Now: <label>` / `Now: mixed` from
     `tracked_status`.
   - `offer_status`: no rows → `AsksNothing`; else `Control(FormFields(form))`.
   - `settle_status`: bind the form on `CHOICE_FIELD` (local import, as
     `settle_edit`), invalid → `CommandRejected(sentence=first error)`;
     answer the word.
   - `set_status_one` (run): `answered("game")`; `choice` None or not a word →
     `RowUnreadable`; `record_facts(..., status=, idempotency_key=,
     correlation_id=, source_metadata=_source())` → `RowOutcome.of`.
   - `set_status_back` (inverse): under `answered("game")` read PlayerGame via
     plain manager + library (`RowNotHeld` when absent, as `_removed_row`);
     `removed_at` → `CommandRejected(GAME_REMOVED)`; `status_before` None →
     `CommandRejected(NOT_CHANGED_BY_THIS_BATCH)`; then `record_facts(status=
     before)` on `player_game.game`.
   - `STATUS_PREVIEW`: Game, Platform (`"Unspecified"`), Status (label).
   - `SET_STATUS = BulkAction(...)` per spec.
4. `games/bulk_actions.py` foot import adds `bulk_status`.
5. `games/views/game.py:303`: `tray_actions(SET_STATUS.name, REMOVE_GAME.name,
   …)`. `games/bulk_tray.py` docstring: order follows the row menu for acts
   both offer.
6. `tests/test_bulk_status.py` (`transaction=True` where it POSTs through the
   runner): the spec's Proof list, through `games:run_bulk_action` and the
   Undo route, as `tests/test_bulk_game_removal.py` does. Plus: offer renders
   a `choice` input and the placeholder; tray on the Games list lists Set
   status before Remove (`tests/test_bulk_tray.py` or the list's page test).
7. `e2e/test_bulk_game_status_e2e.py`: select two games, Set status…,
   pick Completed, Save, wait for the tally page, assert rows via ORM after
   the server-rendered answer, press Undo, assert the earlier words.
8. Docs: CLAUDE.md bulk-runner paragraph gains one sentence for #1270; wave
   spec cross-wave line marked landed.
9. `make lint-fix`, `make format`, `make vale`, then full `make check` under
   `flock "$(git rev-parse --git-common-dir)/heavy-tests.lock"`; `make
   render-pages` diff before/after (only Games list tray differs).

## Follow-up issues to file

- #1313 Retire `SetPlayerGameStatus` (filed): no write path dispatches it; `record_facts`
  writes the same event. Mind the `CommandName` stored in idempotency records.

## Gotchas

- `tracked_status` is the raw value; render `PlayerGameStatus(...).label`.
- The runner re-posts the settled word under `CHOICE_FIELD`; one unprefixed
  field keeps offer and settle on one name.
- The Undo's key for `record_facts` is the runner's per-row key as is: one
  dispatch per row, no suffix needed.
