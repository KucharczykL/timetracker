# Times played — implementation plan (#1024)

Spec: [docs/superpowers/specs/2026-10-07-issue-1024-times-played-design.md](../specs/2026-10-07-issue-1024-times-played-design.md)

**Precondition:** #1034 merged (or its branch pushed and this branch rebased
onto it). Its `with_implied_status` / `status_implied_over` and
`FINGERPRINT_VERSION = 6` are what Task 2 and Task 5 build on.

Inline, TDD per task. Iterate with
`flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make test-fast ARGS=…`.

## Task 1 — Read predicates

Files: `games/reads/playthrough_count.py` (new), `tests/test_playthrough_count_reads.py`.

- `bare_runs(library, player_game) -> QuerySet[Playthrough]` and
  `dateless_runs(library, player_game) -> QuerySet[Playthrough]`: live
  ordinary runs (`live_ordinary_runs`) with the spec's column rules, plus
  `~Exists(...)` per `BLOCKING_REFERRERS` entry, own library, any mark.
  Build the `Exists` from `rows_naming`'s filter shape (`referrer.model.
  _default_manager.filter(**{field: OuterRef("pk")}, library=OuterRef("library"))`);
  add a helper beside `rows_naming` in `games/reads/referrers.py` if it
  reads cleaner (`naming_exists(referrer, *, library_scoped)`).
- `foreign_naming(run)`: reuse `foreign_referrer` for the `RowUnreadable` path.
- Ordering: `dateless_runs(...).order_by("-created_at", "-id")`.
- Column checks: `start_recorded_at`/`completion_recorded_at` not null,
  `started`/`completed` null (unknown collapses to NULL, `stated_date`),
  `name=""`, `note=""`, both act notes `""` (look up the endpoint note
  column names in `games/endpoint_fields.py`).
- Tests: a run each for: dated start, dated completion, named, noted, act
  note, live session, removed session, live record, removed record → not
  dateless; plain dateless → yes. Bare: no act, blank, unnamed → yes; noted → no.

## Task 2 — `StatePlaythroughCount`

Files: `games/commands/playthrough_count.py` (new), `games/events/dispatch.py`
(`CommandName.PLAYTHROUGH_STATE_COUNT = "library.playthrough.state_count"`),
`tests/test_playthrough_count_command.py`.

- Fields: `game_id: uuid.UUID`, `count: int`. `MAX_TIMES_PLAYED = 100`.
- Resolve the PlayerGame with `library_row` + own `Refusal` (not
  `tracked_game`; `tests/test_command_scope_guard.py` forbids bare `.get()`).
- Order of refusals exactly as the spec lists.
- Raise: if exactly one live ordinary run and it is bare → started+completed
  (no day, no note) on it; then `playthrough_created` + started + completed
  per new run, ids minted in order with `uuid.uuid7()`. Then #1034's
  `with_implied_status(context, acts, HeldGame(tracked),
  PlayerGameStatus.COMPLETED)`, both from `games/commands/playergame.py`
  (`HeldGame` wraps the PlayerGame row; `ImpliedStatus` in `games/models.py`).
- Lower: take `d` from `dateless_runs`; foreign referrer check →
  `RowUnreadable`; if `d` covers every live ordinary run, keep the last of the
  slice (oldest) and append `void` events for completion then start
  (`void_endpoint`'s event builders from `games/events/playthrough.py`)
  instead of `playthrough_removed`.
- Tests: every Verification "State" bullet in the spec, plus fingerprint
  stability of a repeat.

## Task 3 — `UndoPlaythroughCount`

Same module; `CommandName.PLAYTHROUGH_UNDO_COUNT`.

- Fields: `game_id`, `statement: uuid.UUID`, `stated: int`.
- Read `batch_events(library, statement)` under the lock; refuse with
  `RowNotHeld`-style refusal where none (a statement this library never made).
- Build inverses per event type (spec table). Status back via
  `status_change(library, player_game_id, statement)`, only if no later
  `playergame.status_changed` on that aggregate (`aggregate_events`).
- Guards in the spec's order; "touched run changed since" = any event in
  `aggregate_events(library, run_id)` with sequence > the statement's last
  on that run.
- Tests: every "Undo" bullet in the spec.

## Task 4 — Writes

Files: `games/writes/playthrough_count.py` (new).

- `state_times_played(actor, game, count, *, submission: uuid.UUID) -> TimesPlayed`
  (`NamedTuple(previous: int, stated: int, statement: uuid.UUID, changed: bool)`),
  dispatching with `correlation_id=submission`,
  `idempotency_key=f"times-played-{submission}"`, under `answered("playthrough")`.
- `undo_times_played(actor, game, statement, stated)`, key
  `f"times-played-undo-{statement}"`, fresh correlation id.

## Task 5 — Form, views, routes

Files: `games/forms.py` (or `games/views/times_played.py` with its form),
`games/views/game.py` (`_played_row`), `games/urls.py`,
`games/views/returns.py`, `tests/test_times_played_views.py`.

- `TimesPlayedForm`: `count` `IntegerField(min_value=0)`, label "Times
  played through", help "Adds or removes playthroughs with no days
  stated."; hidden `submission` uuid7 like the other submission-keyed forms;
  `PrimitiveWidgetsMixin`. Max checked by the command (lower above 100 allowed).
- `state_times_played` view: GET/POST, `render_page(width="form")` with
  `AddForm`; `CommandFailed` → `form.add_error("count", failure.message)`;
  success → `notify(..., action=Undo(reverse("games:undo_times_played", …)))`,
  `redirect(return_url(request, fallback=game page))`. Unchanged → info toast,
  no Undo. 404 for a game not `visible_to` the library.
- `undo_times_played`: `@require_POST`, `restore_and_return`.
- `_played_row`: add `DropdownLinkItem(url, "Set times played…",
  attributes=form_dialog_link())` only when the game is tracked (pass a flag
  from the caller, which already has `tracked`).
- Both routes in `ORIGIN_AWARE`.
- Tests: spec "View" bullets; `tests/test_paths_return_200.py` if it lists
  routes.

## Task 6 — Gates the suite enumerates

- `tests/test_projection_replay_gate.py`: add a raise, a lower and an Undo to
  `build_stream`.
- `tests/test_endpoint_fingerprints.py`: add both commands to
  `COMMANDS`/`RECORDED` (after #1034's re-record).
- `tests/test_command_answers.py`: any new conflict type mapped (none expected).

## Task 7 — e2e

`e2e/test_times_played_e2e.py`: Game detail → split ▾ → "Set times played…"
opens a `<form-dialog>` (assert dialog, not navigation) → 3 → Save → wait for
the server-rendered Playthroughs section → three rows "Unknown" → Undo in
toast → back to one bare row. Use `create_tracked_game`.

## Gotchas

- A build cannot read rows its own append writes: mint every id.
- `TemporalValue.unknown()` and None are one fact; compare with `stated_date`.
- Tests that POST through views need `@pytest.mark.django_db(transaction=True)`.
- Never ask the process for a day; no day is needed here.
- Comments ≤ 7 words; refused words checked by `make vale`.
