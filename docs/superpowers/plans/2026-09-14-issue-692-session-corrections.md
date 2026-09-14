# SES-04 — Correct a session's timing, description, and run: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Three commands, five events, five handlers that correct a recorded
`PlayerSession`: its timing, its note/device/emulated flag, and its run.

**Architecture:** `CreateSession`'s instance-method rules become module
functions, so `CorrectSessionTiming` states a whole `TimingStatement` through
the same builder and refusals. `DescribeSession` appends one event per fact
that differs; `MoveSessionToPlaythrough` appends one event naming the run. Each
handler is one `amend`. Nothing calls the commands; #702 owns surfaces.

**Tech Stack:** Python 3.14, Django 6, pydantic TypedDict payloads,
PostgreSQL 18, pytest + pytest-xdist.

**Spec:** `docs/superpowers/specs/2026-09-14-issue-692-session-corrections-design.md`
— read it before any task. This plan names files, interfaces, tests and traps;
it does not restate the spec's reasons.

## Global Constraints

- **Run everything through `make`.** No `direnv exec .`, no bare `uv run` /
  `pytest`. Focused: `make test ARGS="tests/test_playersession_command.py -k move -x"`.
- **Iterate with `make check-fast`; the gate is full `make check`**, including
  `e2e/`. Never gate on a subset.
- **Two sentences per refusal.** `raise CommandRejected(message, sentence=…)`.
  A raise site with no `sentence` is a defect. A no-fact `DescribeSession` is a
  `ValueError`, not a refusal.
- **One act, one verb.** `correct timing` / `CorrectSessionTiming` /
  `.timing_corrected`; `describe` / `DescribeSession` / `.note_changed`,
  `.device_changed`, `.emulated_changed`; `move` / `MoveSessionToPlaythrough` /
  `.moved`.
- **`make vale`** refuses `fold`, `seam`, `tombstone`, `archive`, `delete`,
  `heal` in docs and comments.
- **Complete words in identifiers; no issue numbers in comments.**
- **Never write a `GeneratedField`** (`effective_day`, `effective_duration`,
  `sort_instant`).
- **Dispatching tests** use the existing `owned_user`/`owned_library`/`run`
  fixtures and `dispatch(...)` directly, as `tests/test_playersession_command.py`
  does. A test through a view would need `transaction=True`; none here does.
- **Subagent batching:** dispatch Tasks 1–3 to one implementer and 4–6 to a
  second. The controller runs Task 7 and the `make check` gate once.

---

## File Structure

| File | Change |
|---|---|
| `games/commands/playersession.py` | Lift rules to module functions (Task 1); add `CorrectSessionTiming`, `StatedDevice`, `DescribeSession`, `MoveSessionToPlaythrough`. |
| `games/events/playersession.py` | Five payloads, five `EventSpec`s, five builders. |
| `games/projectors/playersession.py` | Five handlers and their `handles` entries. |
| `games/events/dispatch.py` | Three `CommandName` members. |
| `tests/test_playersession_command.py` | One section per command; one backstop test re-pointed. |
| `tests/test_playersession_events.py` | Payload round-trips, refusals, builder days, reference fields. |
| `tests/test_playersession_projection.py` | Handler entries, columns written, replay and rebuild. |
| `CLAUDE.md`, `docs/superpowers/specs/2026-09-12-session-wave-design.md` | Record what the slice settled (Task 7). |

---

### Task 0: Branch

- [ ] `git fetch origin`; cut `feat/issue-692-session-corrections` from
  `spec/issue-692-session-corrections`, then `git rebase origin/main`. The spec
  and this plan ride on the branch.

### Task 1: One rule set for creation and correction

Pure refactor plus one defect fix. Every existing test stays green.

**Files:** `games/commands/playersession.py`, `tests/test_playersession_command.py`

**Produces** (module level, private, in this module):
- `_normalized_timing(timing: TimingStatement) -> TimingStatement` — the
  `match` now in `CreateSession.__post_init__`: `_check_aware` on both
  instants, then `_stated_zones`; a `DurationOnlyTiming` passes through.
- `_timing_payload(timing: TimingStatement) -> TimingPayload` — today's
  `CreateSession._timing_payload`, taking the statement as its argument.
- `_library_device(context: CommandContext, device_id: uuid.UUID | None) -> Device | None`
  — today's `CreateSession._device`.
- `_stated_zones`, `_check_note`, `_check_instants`, `_check_duration`,
  `_check_zones`, `_check_endpoint_zone` — today's static methods, same
  signatures, now module functions.

**Steps:**
- [ ] Write the failing test `test_it_refuses_a_blank_day_zone_by_naming_the_fact`:
  `a_timed(day_zone="")` is refused with sentence
  `"Say which time zone this session's day is read in."`.
  Trap found in review: `_check_zones` tests `day_zone is None`, but
  `_stated_zones` normalizes a blank to `""`, which falls through to
  `known_zone` and answers `" is not a time zone we know."` via the
  `name or 'That'` fallback. The `_stated_zones` docstring claims the
  opposite. Run it; expect FAIL on the sentence.
- [ ] Move the functions; `CreateSession` calls them. Change the day-zone guard
  to `if not day_zone:`. Keep `_check_zones`'s signature `day_zone: str | None`
  in spirit: a `None` from a caller that skipped normalization still lands on
  the same sentence.
- [ ] Re-point `test_a_refusal_the_command_forgot_reaches_a_person_as_a_sentence`:
  it patches `CreateSession._check_duration`; patch the module attribute
  `games.commands.playersession._check_duration` instead. Callers must look the
  function up as a module global for the patch to reach them — do not bind it
  as a default argument or a local alias.
- [ ] `make test ARGS="tests/test_playersession_command.py"` — all green.
- [ ] Commit `refactor: share the session timing rules at module level`.

### Task 2: Five events

**Files:** `games/events/playersession.py`, `tests/test_playersession_events.py`

**Produces:**

| Spec constant | Event type | Payload (all `@with_config(STRICT_SCHEMA)`) | Builder |
|---|---|---|---|
| `PLAYERSESSION_TIMING_CORRECTED` | `library.playersession.timing_corrected` | `timing: TimingPayload` | `playersession_timing_corrected(session_id: uuid.UUID, *, timing: TimingPayload) -> NewEvent` |
| `PLAYERSESSION_NOTE_CHANGED` | `library.playersession.note_changed` | `note: str` | `playersession_note_changed(session_id, *, note: str)` |
| `PLAYERSESSION_DEVICE_CHANGED` | `library.playersession.device_changed` | `device: Reference \| None` | `playersession_device_changed(session_id, *, device: Reference \| None)` |
| `PLAYERSESSION_EMULATED_CHANGED` | `library.playersession.emulated_changed` | `emulated: bool` | `playersession_emulated_changed(session_id, *, emulated: bool)` |
| `PLAYERSESSION_MOVED` | `library.playersession.moved` | `playthrough: ReferenceId` | `playersession_moved(session_id, *, playthrough_id: uuid.UUID)` |

All `aggregate_type="playersession"`, all registered on `DEFAULT_EVENT_TYPES`.
Only `playersession_timing_corrected` passes an `effective_time`:
`TemporalValue.parse(day_text(stated_day_of(timing)))`. The other four pass
none, as `playthrough_name_changed` does.

**Tests** (one each, in a new section per event):
- Each type is spelled as the table says, with `aggregate_type` `playersession`.
- Each payload round-trips through `DEFAULT_EVENT_TYPES.validate`.
- Timing: all three modes round-trip under the `timing` key; an unknown key
  beside `timing` and a non-canonical instant inside it are `PayloadInvalid`.
- Note: an empty note round-trips (it clears). Emulated: a string `"true"` is
  `PayloadInvalid` (strict).
- Device: `None` round-trips; `reference_fields_for` answers
  `{"device": ReferenceArity.OPTIONAL}`. Moved: a non-UUID string is
  `PayloadInvalid`; `reference_fields_for` answers `{}`.
- Timing correction dating: a Timed statement started 23:30 UTC with
  `day_zone="Europe/Prague"` is dated the next day; a Duration-only one is dated
  its written day; a Corrected statement whose end crosses midnight is dated by
  its start.
- Description and move events carry `effective_time is None`.
- Every builder sets `aggregate_id` to the session id it was given.

- [ ] Write the tests; run `-k "corrected or changed or moved"`; expect
  `ImportError`. Add payloads, specs, builders. Run green. Commit
  `feat: add the session correction events`.

### Task 3: Five handlers

**Files:** `games/projectors/playersession.py`, `tests/test_playersession_projection.py`

**Produces:** `PlayerSessions._timing_corrected`, `_note_changed`,
`_device_changed`, `_emulated_changed`, `_moved`, each registered in `handles`.
- `_timing_corrected`: `amend(PlayerSession, id, **columns_for_timing(payload["timing"]))`.
- `_device_changed`: `device_id=None if device is None else uuid.UUID(device["id"])`,
  as `_created` reads it.
- `_moved`: `playthrough_id=uuid.UUID(payload["playthrough"])`.
- The other two amend `note` / `emulated`.

**Tests** (append events with the builders, as the `.ended` tests do; no command):
- Each of the five types has a `CURRENT_STATE` handler (mirror
  `test_the_end_event_has_a_current_state_handler`).
- Every mode transition projects and satisfies the CHECKs: parametrize over the
  twelve (from, to) pairs of distinct states among Timed-running,
  Timed-finished, Duration-only, Corrected — create in one, correct to the other, assert all eight columns
  equal `columns_for_timing(to)` and the generated `effective_day` /
  `effective_duration` read the new statement. At least Corrected → Timed
  running and Duration-only → Corrected must be in the set.
- A timing correction leaves `note`, `device_id`, `emulated`, `playthrough_id`,
  `created_at` untouched; each description event leaves the timing columns and
  the other two facts untouched.
- A move to a run at another tracked game: `playthrough_id` changes, the row
  stays under the library, and `PlayerSession.objects.alive()` still reads it.
- A stream holding create → timing_corrected → note_changed → device_changed →
  emulated_changed → moved replays from empty to the same row, and a rebuild
  swaps with an empty diff (mirror `test_an_ended_session_replays` and
  `test_a_rebuild_reproduces_an_ended_session`).

- [ ] Write tests; expect FAIL (no handler). Add handlers. Green. Commit
  `feat: project the session corrections`.

### Task 4: `CorrectSessionTiming`

**Files:** `games/events/dispatch.py`, `games/commands/playersession.py`,
`tests/test_playersession_command.py`

**Consumes:** Task 1's functions; `playersession_timing_corrected`.

**Produces:**
- `CommandName.PLAYERSESSION_CORRECT_TIMING = "library.playersession.correct_timing"`.
- `CorrectSessionTiming(Command)`, frozen slots dataclass: `session_id: uuid.UUID`,
  `timing: TimingStatement`. `__post_init__` sets `timing` to
  `_normalized_timing(self.timing)`. `build`: `_live_session` →
  `_timing_payload(self.timing)` → compare `columns_for_timing(payload)` with
  the same eight attributes of the row → `Unchanged("This session's time already reads so.")`
  when equal, else one `playersession_timing_corrected` event.

**Trap:** import `columns_for_timing` from `games.projectors.playersession`.
This is the first command module to import a projector module; the projector
imports only `games.events.*` and `games.models`, so no cycle is expected.
Never copy the mapping into the command — the spec's point is that the
comparison and the write share one function. Refusals run before the comparison: an invalid restatement of the
row's own values is still refused, not `Unchanged`.

**Tests** (new section `# --- Correcting a session's timing ---`, helper
`corrects(library, actor, session, timing, *, key=None)` beside `ends`):
- Each of the twelve state transitions is recorded (parametrized; one event, row
  matches). Includes Corrected → Timed running, then `EndSession` on it succeeds.
- Restating the row's own statement answers `CommandOutcome.UNCHANGED` and
  appends nothing; the same instants in a different `started_at_zone` append.
- Every refusal the creation has, once each through this command: end before
  start, negative duration, sub-second duration, zero Duration-only, unknown
  zone, blank/`None` day zone, end zone with no end, naive instant (raised at
  construction), with a sentence.
- Unknown session, another library's session, session under a removed run,
  under a removed tracked game: refused with a sentence.
- The event's `effective_time` is the new statement's day, not the old one's.
- Reset shape: a running Timed row corrected to
  `TimedTiming(started_at=now, day_zone=row.day_zone, started_at_zone="Asia/Tokyo")`
  is recorded; the same statement on a row with an end is refused
  (end before start).
- Same idempotency key, same command: `REPLAYED`.

- [ ] Tests → FAIL → implement → green → commit `feat: correct a session's timing`.

### Task 5: `DescribeSession`

**Files:** `games/events/dispatch.py`, `games/commands/playersession.py`,
`tests/test_playersession_command.py`

**Produces:**
- `CommandName.PLAYERSESSION_DESCRIBE = "library.playersession.describe"`.
- `class StatedDevice(NamedTuple): device_id: uuid.UUID | None`.
- `DescribeSession(Command)`: `session_id: uuid.UUID`, `note: str | None = None`,
  `device: StatedDevice | None = None`, `emulated: bool | None = None`.
  `__post_init__`: all three `None` → `ValueError`; strip a stated note, then
  `_check_note`. `build`: `_live_session`; for each stated fact that differs
  from the row, one event (order: note, device, emulated). A stated device is
  compared by `device_id` with `session.device_id` **before**
  `_library_device` resolves it. No event → `Unchanged("This session already reads so.")`.
  Device event payload is `capture_reference(device)` or `None`.

**Tests:**
- Note alone, device alone, emulated alone each append exactly their event and
  change their column.
- All three stated and differing: three events under one dispatch.
- Two stated, one equal: only the differing event.
- Empty note clears a note; a padded note is stripped before comparison (so
  `"  x "` on a row holding `"x"` is `Unchanged`) and before the fingerprint
  (same key, `" x"` then `"x"` → `REPLAYED`, not a conflict).
- `StatedDevice(None)` on a row with a device clears it; `device=None` leaves it.
- A NUL byte in the note is refused with a sentence.
- Device of another library, removed device: refused. Restating the device the
  row already names after that device was removed: `Unchanged`.
- No fact stated: `ValueError` at construction, no dispatch.
- Unknown / other-library / removed-run session refused.
- Fingerprint: `DescribeSession(session_id=…, device=StatedDevice(None))` and
  `DescribeSession(session_id=…, note="")` dispatched under one key raise
  `IdempotencyKeyMismatch` (they are different statements).

- [ ] Tests → FAIL → implement → green → commit `feat: describe a session`.

### Task 6: `MoveSessionToPlaythrough`

**Files:** `games/events/dispatch.py`, `games/commands/playersession.py`,
`tests/test_playersession_command.py`

**Produces:**
- `CommandName.PLAYERSESSION_MOVE = "library.playersession.move"`.
- `MoveSessionToPlaythrough(Command)`: `session_id: uuid.UUID`,
  `playthrough_id: uuid.UUID`. `build`: `_live_session`; if
  `session.playthrough_id == self.playthrough_id` → `Unchanged("This session already belongs to that playthrough.")`
  ahead of any target read; else `_live_run(context, self.playthrough_id)` →
  one `playersession_moved` event.

**Tests:**
- Move to another run at the same game; move to a run at another tracked game
  (the session's game, read through its run, is the new one).
- Move to an `IMPORTED_HISTORY` run is recorded.
- Same run: `Unchanged`, no event.
- Target run of another library, removed target run, target under a removed
  tracked game, unknown target: refused with a sentence.
- Source under a removed run or removed game: refused (spec: `alive()` hides it).
- The moved row keeps every timing column and its description.

- [ ] Tests → FAIL → implement → green → commit `feat: move a session to another playthrough`.

### Task 7: Record the slice, propagate, gate

- [ ] `CLAUDE.md`, the **PlayerSession** paragraph: "Two acts state one today"
  becomes the five acts; one sentence each for the three commands, pointing at
  the spec as its contract, in the paragraph's existing compressed style.
- [ ] Wave spec `### #692` section: replace "which mode transitions are legal"
  and "an override on a row with no elapsed time" with the settled rule (whole
  statement, every transition permitted); state `reset_session`'s statement.
- [ ] `_timed_start`'s Corrected sentence says "Correct it again to change it" —
  now true; leave it. Check the two `_stated_zones` / `_check_zones` docstrings
  match Task 1's fix.
- [ ] Comment on the siblings (bare `#NNN`, no pasted titles):
  - #702 — `reset_session` is `CorrectSessionTiming` with `TimedTiming(now,
    day_zone=row's, started_at_zone=browser's)`, offered only while running;
    the edit form posts two commands.
  - #714 — the bulk move is `MoveSessionToPlaythrough` per row; same-run rows
    answer `Unchanged`; a session under a removed run or game is refused.
  - #694 — `MoveSessionToPlaythrough` exists; the remedy for its refusal is live.
- [ ] `make vale`, then full `make check`. Commit
  `docs: record what the session correction slice settled`.

## Follow-up issues to file

None found. If implementation meets a reader of `PlayerSession` that assumes a
session never changes its run, file one naming that reader.
