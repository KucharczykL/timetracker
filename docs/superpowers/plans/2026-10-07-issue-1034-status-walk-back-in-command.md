# Plan: an act states its status in its own dispatch (#1034)

Spec: `docs/superpowers/specs/2026-10-07-issue-1034-status-walk-back-in-command-design.md`.
Implementation inline, TDD per task. Iterate with focused `make test ARGS=…`
under the shared lock; `make check-fast` at task ends.

## Task 1 — the rule

- `games/models.py`: `status_implied_over(held, implied) -> bool` beside
  `PlayerGameStatus`. Played: `held is UNPLAYED`. Completed: `held is not
  COMPLETED`. Any other `implied` raises `ValueError`.
- `games/reads/companion_status.py`: `played_is_offered` calls it.
- `games/commands/playergame.py`: `implied_status_change(context, tracked,
  implied) -> NewEvent | None`; removed row answers `None`; event built like
  `RecordPlayerGameFacts`'s status event (`_stated_now`). Share the event
  construction with `RecordPlayerGameFacts` (one private helper).
- Tests: new `tests/test_implied_status_rule.py` — full status table for
  both implied words, other word raises, removed row answers None.

## Task 2 — `RecordPlayerGameFacts.implied_status`

- Field `implied_status: PlayerGameStatus | None = None`. Guard: counts as a
  fact; refused beside `status` (`ValueError`). Build: `implied_status_change`
  when set.
- `games/writes/playergame.py` `record_facts`, and
  `games/views/playergame_writes.py` `record_facts_for_request`: parameter.
- `tests/test_bulk_game_edit.py::test_the_fact_lists_agree`: exclude
  `implied_status`, with the reason.
- Tests in `tests/test_playergame_command.py`: implied Played over Unplayed
  appends, over Completed unchanged, beside a mastery change appends mastery
  alone; both fields raise; implied alone is not "no fact".

## Task 3 — fingerprint version

- `games/events/idempotency.py`: `FINGERPRINT_VERSION = 6`.
- `tests/test_playergame_command.py`: a key recorded under version 5
  replays (copy the version-1/2 precedent near line 830).

## Task 4 — playthrough carriers

- `games/commands/playthrough.py`:
  - `StartPlaythrough.implies_status: bool`, `CompletePlaythrough.
    implies_status: bool`, no default. Build: when the endpoint appends and
    the flag is set, append `implied_status_change(..., run.player_game,
    PLAYED/COMPLETED)` **last**.
  - `CreatePlaythrough` `kw_only=True`, `implies_played`,
    `implies_completed: bool`. Completed wins: one event at most, only for
    a stated act.
  - `MovePlaythroughToGame`: append the status the run's endpoints imply on
    the target, last. Held status: `HeldTarget.row.status`, or Unplayed for
    `NewlyTracked`. Gotcha: the new row's aggregate id is the tracking
    event's.
- `games/writes/playthrough.py`:
  - `FirstActCommand` protocol with `implies_status`; `EndpointStatement.first`
    typed with it.
  - `RunDraft`: `implies_played`, `implies_completed` before `game_id`.
  - `_state_endpoint` passes the draft's box to the first act only.
  - `_record_once` passes the boxes to `CreatePlaythrough`.
  - `start_run`/`complete_run` take `implies_status`.
  - `_move` reads `MovedRun.status` from its result; delete
    `_state_the_moved_status`.
- `games/writes/implied_status.py`: keep `StatusStated`, `StatusAnswer`
  (`StatusStated | None`) and `implied_status(run)`; add
  `stated_status(result) -> StatusAnswer` (outcome first, then
  `dispatched_events`). Delete `StatusRefused`, `state_implied_status`,
  `implied_by_start`, `_EXPECTED_REFUSALS`, `_STATUS_KEY_SUFFIX`. Consider
  moving the survivors to `games/writes/playthrough_endpoints.py` if the
  module empties.
- `games/writes/playthrough_endpoints.py`: one dispatch each; status from
  `stated_status`.
- Callers: `games/bulk_playthrough_acts.py` (pass True; delete
  `_report_a_refused_status`; Undo's `-status` key stays),
  `games/views/playthrough.py` (drafts from the form boxes; delete
  `_record_companion_status`, `record_completed`, `NewActs` if unused),
  `games/views/playthrough_writes.py` (drop the refused toast), `games/api.py`
  (drafts pass False; drop the refused-status log), `games/forms.py`
  (`clean` keeps `setdefault`, drops the gate).
- Tests: `tests/test_playthrough_command.py` (each flag true/false, Unchanged
  act states no status, event last), `tests/test_playthrough_move_status.py`
  (drop `-status` key and refusal tests; add target Completed stays),
  `tests/test_playthrough_endpoint_writes.py` (drop monkeypatch tests),
  `tests/test_playthrough_form.py` (rewrite clean test to assert status),
  `tests/stated_runs.py`, `tests/completed_runs.py`, replay gate and every
  other construction: pass the flag.

## Task 5 — session carrier

- `games/commands/playersession.py`: `CreateSession` `kw_only=True`,
  `implies_played: bool`; status event last.
- `games/writes/playersession.py`: `SessionDraft.implies_played`;
  `record_session` passes it; `clone_session` passes False.
- `games/views/session.py`: add sets it from `mark_as_played`; edit
  dispatches `record_facts_for_request(implied_status=PLAYED)`; delete
  `_record_played`.
- `games/api.py` session POST, `games/events/benchmark_workload.py`: False.
- Tests: `tests/test_playersession_command.py` (flag), the
  `_record_played` tests (assert row), replay gate construction.

## Task 6 — fingerprint recordings

- `tests/test_endpoint_fingerprints.py`: re-record; add
  `RecordPlayerGameFacts`.

## Gotchas

- Status event last in every dispatch: `created_aggregate_id` reads first.
- `dispatched_events` raises on Unchanged.
- Libraries without a `LibraryCalendar` in tests now fail in the act.
- `make lint-fix` for import order after deleting imports.
