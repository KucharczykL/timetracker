# Plan: move a playthrough to another game (#1466)

Spec: [design](../specs/2026-10-03-issue-1466-move-playthrough-to-game-design.md).
Implementation inline, TDD per task. Iterate with focused
`flock … make test ARGS=…`; `make check-fast` between tasks.

## Task 1: events

- `games/events/playthrough.py`: `PlaythroughMovedPayload {player_game:
  ReferenceId}`, `PLAYTHROUGH_MOVED = EventSpec("library.playthrough.moved",
  aggregate_type="playthrough")`, registered; `playthrough_moved(run_id, *,
  player_game_id)`.
- `games/events/historical_playtime.py`: `HistoricalPlaytimeMovedPayload`,
  `HISTORICALPLAYTIME_MOVED` (`library.historicalplaytime.moved`),
  `historicalplaytime_moved(record_id, *, player_game_id)`.
- Tests: `tests/test_playthrough_events.py`, the historical playtime events
  test: registered spec, aggregate type, payload refuses a stray key.

## Task 2: projectors

- `Playthroughs._moved` → `amend(Playthrough, event, player_game_id=…)`;
  restate the `handles` comment (replay starts empty).
- `HistoricalPlaytimes._moved` → `amend(HistoricalPlaytime, event,
  player_game_id=…)`; no `restated_at`.
- Tests: `tests/test_playthrough_projection.py`, historical playtime
  projection test.

## Task 3: tracking split

- `games/commands/playergame.py`: `tracking_event(game) -> NewEvent`;
  `tracking_events` = `[tracking_event(game), playthrough_created(id)]`.

## Task 4: the command

- `CommandName.PLAYTHROUGH_MOVE = "library.playthrough.move"`.
- `MovePlaythroughToGame(playthrough_id, game_id)` in
  `games/commands/playthrough.py`, steps as the spec orders them.
- Record read: `HistoricalPlaytimeRun.objects.filter(library=…,
  playthrough=run)` → record ids; for each record, the set of its run ids;
  >1 → `CommandRejected(sentence=…)` naming edit / restore-then-edit.
  Import of `HistoricalPlaytimeRun` from models only (no command import
  cycle: `historical_playtime.py` imports this module).
- Target placeholder: `placeholder_run(library, target_pg)` (function-local
  import, as `RecordPlaythroughByName`). Only for a tracked target.
- Source bare: `_other_live_ordinary_runs(context, run).exists()` false →
  `playthrough_created(run.player_game_id)`.
- Tests (`tests/test_playthrough_move.py`): move; same game Unchanged
  (also for a removed run); removed run/game refused; bucket refused;
  removed target PlayerGame refused (owned and shared game); unknown
  target `RowNotHeld`; untracked target tracked, no placeholder minted;
  target placeholder removed; target with named run or session keeps it;
  source placeholder minted; source with sibling run mints none; sole
  record moved (live, removed), `restated_at` null, join ids kept; shared
  record refused (live and removed sentences); sessions follow (read
  `library_sessions` by game).

## Task 5: batch Undo

- `games/reads/events.py`: `run_parent_at(library, run_id, sequence) ->
  uuid.UUID` — latest `playthrough.created`/`.moved` payload
  `player_game` at or before `sequence`; `RowUnreadable` if none.
- `games/bulk_playthrough_acts.py`: find the batch's endpoint event
  sequence (already read in `_refuse_unless_this_batch_wrote_it`); read
  the parent; use it in `_word_before`, `_stated_since`,
  `_put_the_status_back` (load `PlayerGame` by library + pk, plain
  manager, for `game`).
- Test in `tests/test_bulk_playthrough_acts.py`: batch start → move →
  Undo restores source status.

## Task 6: write path, form, view, API

- `restate_run(actor, run, draft, *, game_id=None, correlation_id)`:
  inside `answered`, dispatch the move first where `game_id` differs from
  `run.player_game.game_id`; then `run.refresh_from_db()`.
- `restate_run_for_request` passes `game_id`.
- `PlaythroughForm`: `locked_game` comment and sentence name the bucket.
- `edit_playthrough`: `locked_game=game` only for a non-ordinary run;
  `game_id=form.cleaned_data["game"].pk`; companion status and fallback
  redirect on the form's game.
- `UpdatePlaythroughIn.game_id: UUIDv7 | None`; PATCH passes it when set.
- Tests: form (bucket lock), view (`tests/test_playthrough_view_cutover.py`
  or new), API (`tests/test_playthrough_api_writes.py`): move, 404.

## Task 7: replay gate

- `tests/test_projection_replay_gate.py::build_stream`: one move carrying a
  sole record to a second game (one `historicalplaytime.moved`, one
  `playthrough.moved`); `62` → `64`.

## Task 8: docs

- CLAUDE.md Playthrough paragraph: `MovePlaythroughToGame`.
- Wave doc: #1466 entry notes the two rulings.

## Gotchas

- `Command` fingerprints fields: UUIDs, not models.
- Unchanged before every refusal; `RowNotHeld` for an unknown target.
- `MovePlaythroughToGame` must not import `games.commands.historical_playtime`
  (cycle).
- Tests that POST through the view need `transaction=True`.
- `make lint-fix` before each commit for import order.
