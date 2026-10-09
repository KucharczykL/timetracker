# Plan: Log a game in one modal (#1517), add-and-edit redesign

Spec: `docs/superpowers/specs/2026-10-09-issue-1517-log-a-game-design.md`.
TDD, one task at a time. Iterate with
`flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make test-fast ARGS=…`.
Never run e2e while `dev-1517` is up.

Already on the branch and kept: route, entry points, `FormFieldGroup.container`,
`<log-sections>` (nested modals, `open-section`), `CopyFields` extraction in
`games/entry_forms.py` (Add to library keeps it; the Log form stops using it),
`SubmissionKind` "log", the e2e and test scaffolding.

## Task 1: Access Unknown

- `games/models.py`: `EntryAccess.UNKNOWN = "unknown", "Unknown"`; the CHECK
  at the column follows the enum; `make makemigrations ARGS="games --name entry_access_unknown"`.
- `games/events/libraryentry.py`: the access `Literal` gains `"unknown"`.
- Tests: `tests/test_libraryentry_events.py` pin stays green; new tests that
  an Unknown copy is not counted by `games/reads/copy_figures.py`, leaves
  `AccessSummary.owned_now` false, and a game purchase refund does not end it.
- Gotcha: grep `EntryAccess.` and `"owned"` lists in tests that pin exact
  choices (filters metadata, API schema snapshots) and update them.

## Task 2: reads and run writes

- `games/reads/log_game.py`: replace `HeldFacts`/`held_facts` with the spec's
  fields: `removed`, `status`, `run` (newest live ordinary by `created_at`),
  `started`/`completed` (`StatedEndpoint` days), `platform`, `mastered`,
  `note`. Platform per spec order; live Release and Platform only.
  Helper `copy_release_for(library, game, platform) -> Release | None`
  (spec Copy step 1).
- `games/writes/playthrough.py`: `record_run(..., idempotency_key=None)`
  passes the key to the creation; new `void_run_endpoint(actor, run,
  endpoint, *, correlation_id)` dispatching `VoidPlaythroughStart` /
  `VoidPlaythroughCompletion` under `answered("playthrough")`.
- Tests: `tests/test_log_game_reads.py` (prefill order, removed game,
  several copies on a platform, no-day act reads empty);
  `tests/test_playthrough_writes.py` (keyed `record_run` twice creates one;
  void then `Unchanged`).

## Task 3: `LogStatement` and `log_game`

- `games/writes/log_game.py` rewritten: `LogStatement(game, run_id,
  started: Restated[ActStatement], completed: Restated[ActStatement],
  note: str | Keep, platform_id, platform_changed: bool,
  playtime: SessionTiming | HistoricalHours | None, attempt: int,
  mastered: bool | Keep, status: PlayerGameStatus | Keep, seen_status)`.
  Steps per spec table: Track → Copy (`copy_release_for`, else
  `release_on` for owned / standing read for shared, then `record_entry`
  Unknown) → Run (`restate_run`/`record_run` keyed `log-run-<token>`, then
  voids) → Playtime (run order per spec; Release from Copy) → Mastered →
  Status (Played after a record where the spec says).
  `LogStep` = track/copy/dates/playtime/more/status/platform; `RowRefused`
  from `release_on` → `LogRefused("platform", …)`.
- Tests: `tests/test_log_game.py` rewritten to the spec's Tests list.

## Task 4: `LogGameForm`

- `games/log_forms.py` rewritten. Fields: `game` (picker, `NEW_GAME`,
  opener fact; `prefill_game` → `initial`), `status` (required choice,
  prefilled word or Unplayed) + `status_seen`, `platform` (platform picker
  with `PostCreate(PLATFORM_CREATE_URL)` and `NEW_PLATFORM`, optional) +
  `platform_seen`, `started`/`completed` + `_seen`, `run` (hidden id),
  `playtime_kind`, `day`, `duration`, `device`, `attempt` (hidden),
  `mastered` + `mastered_seen`, `note` + `note_seen`, `submission`.
  `TODO(#1604)` on the platform field.
- `clean()`: removed game; platform step-2 refusals; reversed days using
  seen day for an unchanged side; zero duration.
- `statement()` builds `LogStatement`.
- Tests: `tests/test_log_forms.py` rewritten.

## Task 5: view and `<form-dialog>` reload

- `games/views/log_game.py`: groups: top (game, status, platform, started,
  completed) inline; Playtime and Mastered-and-note in containers; openers
  are `ControlButton`s with `data-log-section-edit`; link text flips to
  "Playtime added"/"Mastered and note set" through CSS or the element.
  Submit label "Create log"/"Save". Refusal re-render per spec (seen values
  from post, written playtime dropped, `attempt` raised).
  Drop summaries, ticks, `TICKED_SHOWN`/`SUMMARY_HIDDEN`/`RUN_ROW_SHOWN`.
- `ts/elements/form-dialog.ts`: `form-dialog:reload` `{url}` refetches in
  dialog mode, replaces the body, rebaselines. Vitest in
  `ts/elements/form-dialog.test.ts`.
- `ts/elements/log-sections.ts`: no ticks; openers open; dismiss = Done;
  on game `search-select:change` build `log/?prefill_game=<id>&origin=…` and
  dispatch `form-dialog:reload`, else `location.assign`; drop handles on
  disconnect. Vitest updated.
- Tests: `tests/test_log_game_view.py` rewritten to the spec list.

## Task 6: e2e

- `e2e/test_log_game_e2e.py` per spec: navbar pick reloads with data and no
  unsaved prompt; Add playtime + Done; refusal reopens; Game detail locked,
  Save reloads Game detail.

## Task 7: docs sweep, gate, PR

Delete this plan; spec timeless (ASD-STE100, 200–500 words); CLAUDE.md
(Log a game under Key patterns; `EntryAccess.UNKNOWN` in LibraryEntry;
`form-dialog:reload` in the form-dialog bullet; `prefill_<field>` beside
the opener-facts bullet); comment #1519, #1596, #1526 where the work
changes them; full `make check`; draft PR; five reviewers.
