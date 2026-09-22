# Bulk Started today and Completed today implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Two tray acts on the two playthrough tables — "Started today" and "Completed today" — each stating one endpoint at the library's calendar day on every selected run, each carrying the status the act implies, each undoable through two new endpoint-voiding commands; the two per-row routes retire into the runner.

**Architecture:** The acts are `BulkAction` values on the shipped runner (`games/views/bulk.py`), shaped after `games/bulk_finish.py`: a `BulkChoice` stamps the day into the confirmation so a re-posted chunk replays rather than mismatching each row's fingerprint. The forward half is a request-free writer that states the endpoint and then the status. The inverse needs a retraction nothing in the tree has, so `VoidPlaythroughStart` / `VoidPlaythroughCompletion` and their two events arrive with it.

**Tech Stack:** Django 6 / Python 3.14 / PostgreSQL 18, pydantic payload validation, pytest + pytest-xdist, Playwright for e2e.

**Spec:** `docs/superpowers/specs/2026-09-22-issue-1256-bulk-endpoint-acts-design.md` — read it first; every "why" lives there and is not repeated here. Wave doc: `docs/superpowers/specs/2026-09-19-selectable-tables-wave-design.md` (PR #1260 carries the one-press correction this issue implements).

## Global Constraints

- Run everything through `make`. Never `direnv exec .`, never bare `uv run` / `pytest` / `pnpm`.
- Iterate with `make check-fast`; the gate before "done" is the full `make check`, e2e included. Wrap every pytest target in `flock "$(git rev-parse --git-common-dir)/heavy-tests.lock"`.
- `make format` and `make lint-fix` before every commit; only `lint-fix` sorts imports.
- Python 3.14 only. `except A, B:` (PEP 758) is valid here.
- The recorded vocabulary is frozen on merge: the two event type names, their payload keys and the two `CommandName` values cannot change afterwards.
- Every `CommandRejected` carries two sentences: `raise CommandRejected(message, sentence=…)`. A refusal whose cause is the row raises `RowUnreadable` and states no sentence.
- No command resolves a row with a bare manager `.get()`; use `library_playthrough` / `library_row`. `tests/test_command_scope_guard.py` enforces it.
- No act module imports a sibling act module. `tests/test_bulk_act_imports.py` enforces it; shared halves go in a module that declares no act.
- Comments explain intent, never history; no issue or PR references in code comments.
- `make vale` governs prose and comments. `void` is the retention doc's word for a retraction and is not refused.

---

### Task 1: The two voids

**Files:**
- Modify: `games/events/playthrough.py` (after `PLAYTHROUGH_COMPLETION_CORRECTED`)
- Modify: `games/events/dispatch.py:92-100` (`CommandName`)
- Modify: `games/commands/playthrough.py` (after `CorrectPlaythroughCompletion`)
- Modify: `games/projectors/playthrough.py` (two handlers, two `handles` entries)
- Modify: `games/writes/playthrough.py` (two wrappers)
- Modify: `tests/test_projection_replay_gate.py` (`build_stream`, the hardcoded missing count at `:475`)
- Test: `tests/test_playthrough_voids.py` (new), `tests/test_playthrough_events.py`, `tests/test_playthrough_projection.py`

**Interfaces produced:**
- `PLAYTHROUGH_START_VOIDED` / `PLAYTHROUGH_COMPLETION_VOIDED` — `EventSpec`, aggregate `playthrough`, empty `TypedDict` payload each (two classes, as removed/restored have two), registered in `DEFAULT_EVENT_TYPES`
- `playthrough_start_voided(playthrough_id) -> NewEvent`, `playthrough_completion_voided(playthrough_id) -> NewEvent` — no `effective_time`
- `CommandName.PLAYTHROUGH_VOID_START = "library.playthrough.void_start"`, `…VOID_COMPLETION = "library.playthrough.void_completion"`
- `VoidPlaythroughStart(playthrough_id: uuid.UUID)`, `VoidPlaythroughCompletion(playthrough_id: uuid.UUID)`
- `void_start(actor, run, *, correlation_id, idempotency_key=None, source_metadata=None) -> CommandResult` and `void_completion(…)` in `games/writes/playthrough.py`, shaped like `remove_run`

**Gotchas:**
- Order inside `build`: resolve with `library_playthrough`, then `Unchanged` where the endpoint is unstated, then `_refuse_under_a_removed_game(run)`, then the run's own mark. `_live_run` refuses first and is the wrong helper — copy `RemovePlaythrough`'s order (`games/commands/playthrough.py:591-599`).
- The projector writes all three columns of the endpoint: `started=None, start_recorded_at=None, start_note=""`. The generated bound columns follow; never write them.
- The creation handler names three columns only, so the two new handlers must be amendments (`self.amend`), never `project`.
- `tests/test_projection_replay_gate.py:451` fails until `build_stream` dispatches both voids; `:475` asserts `len(missing) == 27` and moves with it.

- [ ] **Step 1: Write the failing tests**

`tests/test_playthrough_voids.py`, docstring `"""Retracting the record of an endpoint."""`:

| test | state | expected |
|---|---|---|
| `test_a_stated_start_is_voided` | run states a start | `started`, `start_recorded_at`, `start_note` all back to unstated |
| `test_a_voided_start_leaves_the_completion` | both stated | completion's three columns untouched |
| `test_an_unstated_start_is_unchanged` | no start | `CommandOutcome.UNCHANGED`, no event |
| `test_a_removed_run_refuses_the_void` | run removed | `CommandRejected` |
| `test_a_removed_game_refuses_the_void` | `PlayerGame` removed | `CommandRejected` |
| `test_an_unstated_start_under_a_removed_game_is_unchanged` | both | `UNCHANGED` — the no-op precedes the refusal |
| `test_a_stated_completion_is_voided` | completion stated | its three columns unstated |
| `test_a_void_replays` | void, then rebuild the projection | the same row |

Add to `tests/test_playthrough_events.py` that each new spec is registered and carries an empty payload; to `tests/test_playthrough_projection.py` that the handler map holds both.

- [ ] **Step 2: Run them and watch them fail**

`flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make test ARGS="tests/test_playthrough_voids.py -x"` — ImportError.

- [ ] **Step 3: Write the events, the commands, the projector handlers and the write wrappers**

- [ ] **Step 4: Extend the replay gate's stream**

Dispatch both voids in `build_stream` on a run that states both endpoints, after the corrections it already states, and move the count at `:475`.

- [ ] **Step 5: Run the two suites green**

`make test ARGS="tests/test_playthrough_voids.py tests/test_projection_replay_gate.py -x"` under the lock.

- [ ] **Step 6: Commit** — `feat: a command retracts the record of an endpoint`

---

### Task 2: The rows both playthrough acts read

**Files:**
- Create: `games/bulk_runs.py`
- Modify: `games/bulk_removal.py` (delete the moved half, import it back)
- Test: `tests/test_bulk_removal.py` (import paths), `tests/test_bulk_act_imports.py` (no change expected — it must stay green)

**Interfaces produced:**
- `RUN_GONE: str`
- `run_scope(library, filter_json) -> QuerySet[Playthrough]`
- `run_resolution(library, keys) -> Resolution[Playthrough]`
- `RUN_PREVIEW: tuple[PreviewColumn[Playthrough], ...]` with its three private cell writers

**Gotchas:**
- A pure move. No behaviour changes in this task; the diff must read as one.
- `games/bulk_runs.py` declares no act, so both act modules may import it. `bulk_removal` importing `bulk_playthrough_acts` (or the reverse) fails `tests/test_bulk_act_imports.py` for one import order only, which is why the guard exists.

- [ ] **Step 1: Move the four names and the three cell writers, leaving `games/bulk_removal.py` importing them**
- [ ] **Step 2: `make test ARGS="tests/test_bulk_removal.py tests/test_bulk_act_imports.py tests/test_bulk_runner.py -x"` under the lock**
- [ ] **Step 3: Commit** — `refactor: the rows every run act reads`

---

### Task 3: The endpoint and the status it implies

**Files:**
- Create: `games/writes/playthrough_endpoints.py`
- Modify: `games/writes/playergame.py:28-101` (`_dispatch`, `record_facts`)
- Modify: `games/writes/playthrough.py` (`_state_first_act`, `start_run`, `complete_run` take a key and source metadata and answer the `CommandResult`)
- Test: `tests/test_playthrough_endpoint_writes.py` (new)

**Interfaces produced:**
- `StatedAct(NamedTuple)`: `result: CommandResult`, `status_refusal: CommandFailed | None`
- `state_start(actor, run, when, *, correlation_id, idempotency_key=None, source_metadata=None) -> StatedAct`
- `state_completion(actor, run, when, *, correlation_id, idempotency_key=None, source_metadata=None) -> StatedAct`
- `record_facts(...) -> CommandResult` now takes `idempotency_key: IdempotencyKey | None = None` and `source_metadata: SourceMetadata | None = None`

**Interfaces consumed:** `start_run` / `complete_run` (Task 1's file, unchanged semantics), `played_is_offered` (`games/reads/companion_status.py`).

**Gotchas:**
- State the status where the endpoint dispatch answered `APPENDED` **and** where it answered `REPLAYED`. A replay is a chunk posted again, and the status may be the half the first post never reached. `RecordPlayerGameFacts` answers `Unchanged` where the game holds the word already, so the second statement writes nothing.
- Derive the status key from the caller's: `f"{idempotency_key}-status"`, as `games/bulk_move.py:264,313` derives `-move` and `-bucket`. A `None` key stays `None`.
- The endpoint is dispatched first. `_act_of` in the runner reads the metadata of the batch's **first** event (`games/views/bulk.py:785-793`), and a status event first would hide the act's name.
- A status refusal at 409 is caught and returned; anything else rises. `answered()` gives 409 for `CommandConflict`, and the runner ends the batch on every other `CommandFailed` (`games/views/bulk.py:527-544`).
- A start states Played only where `played_is_offered`; a completion states Completed every time.

- [ ] **Step 1: Write the failing tests**

`tests/test_playthrough_endpoint_writes.py`:

| test | expected |
|---|---|
| `test_a_start_states_played_on_an_unplayed_game` | status Played, one correlation id over both events |
| `test_a_start_leaves_a_stronger_status` | game at Completed stays Completed |
| `test_a_completion_states_completed` | status Completed |
| `test_an_unchanged_endpoint_states_no_status` | run already states that day → `UNCHANGED`, status untouched |
| `test_a_replayed_endpoint_states_the_status` | same key twice, status stated once, second answers Unchanged |
| `test_the_status_key_is_derived_from_the_row_key` | two posts under one key append one status event |
| `test_a_refused_endpoint_rises` | run states another start → `CommandFailed` out of `state_start` |
| `test_a_refused_status_is_carried_back` | status refused at 409 → endpoint stated, `status_refusal` set |

- [ ] **Step 2: Run them and watch them fail**
- [ ] **Step 3: Grow `record_facts`, grow the two first-statement writers, write the new module**
- [ ] **Step 4: Run `make test ARGS="tests/test_playthrough_endpoint_writes.py tests/test_playthrough_writes.py tests/test_playergame_write_path.py -x"` under the lock**
- [ ] **Step 5: Commit** — `feat: one writer states an endpoint and the status it implies`

---

### Task 4: The two acts, forward

**Files:**
- Create: `games/bulk_playthrough_acts.py`
- Modify: `games/bulk_actions.py` (the foot import list)
- Modify: `games/views/playthrough.py:183` and `games/views/game.py:1168` (the tray)
- Test: `tests/test_bulk_playthrough_acts.py` (new), `tests/test_bulk_tray.py`

**Interfaces produced:**
- `DayStatement` with `encode() -> ChoiceValue` / `decode(raw) -> DayStatement`, refusing text that is no ISO day
- `offer_day(library, rows, field_name) -> Offered`, `settle_day(library, post) -> ChoiceValue`, `DAY: BulkChoice[Playthrough]`
- `start_one` / `complete_one` — the `RunRow` callables
- `START_RUNS` (`playthrough.start`, label `"Started today"`), `COMPLETE_RUNS` (`playthrough.complete`, label `"Completed today"`), both `color="green"`, `subject="playthrough"`, `inverse_aggregate="playthrough"`, `fallback="games:list_playthroughs"`, `scope=run_scope`, `resolve=run_resolution`, `preview=RUN_PREVIEW`, `choice=DAY`

**Interfaces consumed:** Task 2's `games/bulk_runs.py`, Task 3's `state_start` / `state_completion`, `calendar_today` (`games/reads/calendar.py:47`), `TemporalValue.from_day`.

**Gotchas:**
- `offer` answers `AsksNothing()` for no rows; the confirmation says so itself.
- The sentence beside the hidden input names the day and the side effect — "Each game is marked Completed", "Each game that is not yet played is marked Played".
- `settle` runs again on every chunk over its own last answer, so it must be idempotent: decode, re-encode. No browser field to merge, unlike Finish.
- `ActTitle` refuses one clause for both counts: `one="Record that this playthrough started today"`, `many="Record that these playthroughs started today"`.
- `run` raises `RowUnreadable` under `answered("playthrough")` for a `None` choice: the runner settles before it runs, so a missing choice is a defect, not a refusal.
- A 409 status refusal is logged with the act's name, the row and the library, and the row still counts moved.
- Declaration order in the tray is priority order: `START_RUNS`, `COMPLETE_RUNS`, `REMOVE_RUN`.

- [ ] **Step 1: Write the failing tests**

`tests/test_bulk_playthrough_acts.py`, forward half:

| test | expected |
|---|---|
| `test_a_selected_run_states_a_start_today` | `started` is the calendar day, marker set |
| `test_a_run_that_states_a_start_is_refused_by_row` | tally counts one refused, sentence names the run, the batch goes on |
| `test_a_run_that_states_today_already_counts_as_already_so` | `UNCHANGED` bucket |
| `test_a_completion_states_completed_on_the_game` | status changed under the batch's correlation id |
| `test_a_start_states_played_only_where_offered` | two rows, two games, one status event |
| `test_a_chunk_posted_twice_acts_once` | one event per row |
| `test_the_stamped_day_survives_the_progress_form` | second chunk states the first chunk's day |
| `test_a_doctored_day_field_states_that_day` | the grammar's day, no refusal |
| `test_the_confirmation_names_the_day_and_the_side_effect` | both strings in the HTML |
| `test_the_act_asks_nothing_for_no_rows` | `AsksNothing` |

`tests/test_bulk_tray.py`: both tables offer the three acts in order.

- [ ] **Step 2: Run them and watch them fail**
- [ ] **Step 3: Write the act module and add it to the table's foot import**
- [ ] **Step 4: Wire both trays**
- [ ] **Step 5: Run `make test ARGS="tests/test_bulk_playthrough_acts.py tests/test_bulk_tray.py tests/test_bulk_act_imports.py -x"` under the lock**
- [ ] **Step 6: Commit** — `feat: state a start or a completion on many runs`

---

### Task 5: The two inverses

**Files:**
- Modify: `games/bulk_playthrough_acts.py`
- Test: `tests/test_bulk_playthrough_acts.py` (the Undo half)

**Interfaces produced:**
- `void_start_one` / `void_completion_one` — the `UndoRow` callables
- `stated_by_this_batch(library, run_id, batch_id, family) -> None` — refuses where the latest event of that endpoint's family is not this batch's
- `status_before(library, game_id, batch_id) -> PlayerGameStatus | None` — the word that stands before the batch's own status event, or `None` where the batch stated none

**Interfaces consumed:** `aggregate_events` / `batch_events` (`games/reads/events.py`), Task 1's `void_start` / `void_completion`, `record_facts`.

**Gotchas:**
- The family of an endpoint is three event types: the statement, the correction and the void. The rule is "the latest event of that family is this batch's own" — checking only for a correction lets a second statement through, and the void then destroys a value the batch never wrote.
- A row this batch never stated is refused with `NOT_STATED_BY_THIS_BATCH`; a row another act states since is refused with `CORRECTED_SINCE`. Both are sentences, both tallied refused, the batch continues.
- An unstated endpoint answers `Unchanged`, which is what keeps a doubled Undo green: each press mints its own token.
- `status_before` reads the batch's `library.playergame.status_changed` for that game, then the most recent earlier status event of that aggregate, then Unplayed — the word a tracked row holds while its stream states none, which `games/reads/playergame_history.py` already reads the same way.
- Say nothing where the game holds that earlier word already, and nothing where this Undo's own correlation id states it: two rows at one game share one forward status event, and the sibling would otherwise read the first restoration as a person's change.
- Every other status is a person's and stays. Log the row, the game and both words.
- The endpoint is voided before the status is restated, so a failure leaves the same shape a half-finished forward leaves.

- [ ] **Step 1: Write the failing tests**

| test | expected |
|---|---|
| `test_an_undo_voids_the_start` | endpoint unstated again |
| `test_an_undo_puts_the_status_back` | game at Unplayed again |
| `test_an_undo_leaves_a_status_a_person_changed` | person's word kept, endpoint still voided, row counts undone |
| `test_a_corrected_endpoint_refuses_the_undo` | value kept, one refused in the tally |
| `test_a_restated_endpoint_refuses_the_undo` | void, state again, Undo → refused |
| `test_an_undo_pressed_twice_is_already_so` | `UNCHANGED` bucket |
| `test_two_rows_at_one_game_restore_one_status` | one status event in the Undo batch |
| `test_a_row_of_another_batch_is_lost` | `NOT_THIS_BATCH`, the runner's own rule |
| `test_a_removed_run_refuses_the_undo` | sentence from the command |

- [ ] **Step 2: Run them and watch them fail**
- [ ] **Step 3: Write the two inverses and their two readers**
- [ ] **Step 4: Run the file green under the lock**
- [ ] **Step 5: Commit** — `feat: an Undo retracts the endpoint and puts the status back`

---

### Task 6: Retire the two per-row routes

**Files:**
- Delete: `games/views/playthrough_acts.py`
- Modify: `games/urls.py:105-118`, `games/views/returns.py:53,83`, `games/views/playthrough_rows.py` (`_act_items`, `_act`, `_ACT_WORDS`), `games/views/playthrough_writes.py` (drop the two wrappers), `games/writes/playthrough.py` (drop `start_run` / `complete_run` / `_state_first_act` once Task 3's module is their only caller — keep whatever `restate_run` still needs)
- Modify: `games/bulk_tray.py` (add `one_row_statement`), `games/views/session_menu.py:25-34` (read it instead of its own copy)
- Test: `tests/test_playthrough_rows.py:225-270`, `tests/test_playthrough_companion_status.py:232-394`, `tests/test_returns_classification.py`, `tests/test_action_origin_parity.py`

**Interfaces produced:**
- `one_row_statement(row_id: uuid.UUID) -> Node` in `games/bulk_tray.py` — the hidden `SELECTION_STATEMENT_FIELD` naming one key, mode `some`

**Gotchas:**
- The items' words come from `START_RUNS.label` / `COMPLETE_RUNS.label`. The tail "also marks the game Completed" goes: the confirmation states the side effect, and one act reads the same in both places.
- The gate stays exactly as it is — a run that states a completion is offered no start, a run that states no start is offered no completion. The comment beside it claims the command refuses a start on a completed run; `endpoints_certainly_reversed` uses a strict comparison and accepts a start at today on a run completed today, in the future, on no day, or under a qualifier. Rewrite the comment to state what the gate is, not what the command refuses.
- `record_completed` (`games/views/playthrough.py:343`) and `played_is_offered` stay: the run's form states both.
- `tests/test_playthrough_companion_status.py` keeps every assertion about which status follows which act; only the transport changes — post the runner's statement and its confirmation token instead of the retired route.

- [ ] **Step 1: Move the nine posts in `tests/test_playthrough_companion_status.py` onto the runner's two-POST path, and `tests/test_playthrough_rows.py`'s assertions onto the runner's URL and the one-row statement**
- [ ] **Step 2: Run them and watch them fail**
- [ ] **Step 3: Retire the view module, the two routes, the two `ORIGIN_AWARE` names and the dead writers; point the menu items at the runner**
- [ ] **Step 4: Run `make test ARGS="tests/test_playthrough_companion_status.py tests/test_playthrough_rows.py tests/test_returns_classification.py tests/test_action_origin_parity.py tests/test_paths_return_200.py -x"` under the lock**
- [ ] **Step 5: Commit** — `refactor: the row's two acts reach the runner`

---

### Task 7: The browser, the docs and the gate

**Files:**
- Create: `e2e/test_bulk_playthrough_acts_e2e.py`
- Modify: `CLAUDE.md` (the Playthrough paragraph: the two voids and where the acts live)
- Modify: `docs/superpowers/specs/2026-09-22-issue-1256-bulk-endpoint-acts-design.md` (only if the build taught it something)

**Gotchas:**
- Never run e2e while `make dev` is up: its watchers rewrite the served assets.
- UI assertion is not database assertion — wait on the server-rendered page after the write before reading the ORM.
- `open_row_menu` lives in `e2e/helpers.py`; use it rather than a seventh copy.

- [ ] **Step 1: Write the e2e**

One file, on the Playthrough list: select two runs, press Completed today, read the confirmation's day and side-effect sentence, confirm, assert both rows state a completion and both games read Completed, press Undo, assert both endpoints and both statuses are back. Then one row through its ⋯ menu, to prove the item reaches the same confirmation.

- [ ] **Step 2: `make ts` if any TypeScript changed (it should not have), then run the file under the lock**
- [ ] **Step 3: Update CLAUDE.md's Playthrough paragraph**
- [ ] **Step 4: `make format`, `make lint-fix`, then the full `make check` from a log, read by exit code, never by grep**
- [ ] **Step 5: Commit and open the PR** — `feat: bulk Started today and Completed today (#1256)`

---

## Follow-up issues to file

- **An Undo for the row's own press.** The row's two acts now go through the runner, so they already have one; what has none is every other single-row act reached by its own route (Reset, the game's status dropdown). File it as "which single-row acts still cannot be undone".
- **The gate and the command disagree.** `endpoints_certainly_reversed` accepts a start at today on a run completed today, so the menu's gate is narrower than the rule. Decide which is right — the gate, or a command that refuses a start not before its completion.
