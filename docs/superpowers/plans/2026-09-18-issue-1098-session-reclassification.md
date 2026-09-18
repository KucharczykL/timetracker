# Reclassify a session as historical playtime — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: use
> `superpowers:subagent-driven-development` or
> `superpowers:executing-plans`. Steps are checkboxes.

**Goal:** Give a person the act that turns a mis-recorded session into a
historical playtime record, one row at a time and over everything a review
shows.

**Architecture:** One command answers two events — the record's creation and a
new `library.playersession.reclassified` — so the pair cannot half-happen. The
session keeps `removed_at` as its mark and gains a `reclassified_into`
reference. Two screens: a prefilled entry form for one row, a confirm page for
everything a filter shows.

**Tech Stack:** Django 6, PostgreSQL 18, the event/command/projector machinery
in `games/events/`, the Python component system in `common/components/`.

**Spec:** [2026-09-18-issue-1098-session-reclassification-design.md](../specs/2026-09-18-issue-1098-session-reclassification-design.md).
Read it first. This plan names what to touch; the spec says why.

## Global constraints

- Run everything through `make`. No `direnv exec .`, no bare `uv run`/`pytest`.
- Iterate with `make check-fast`; the gate is one full `make check`, e2e
  included, at the end. Read its exit code from a log, never `grep | tail`.
- Wrap every pytest target in the shared lock when another worktree may be
  running one:
  `flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make check`
- A view that dispatches carries no `@transaction.atomic`;
  `run_in_transaction` refuses to nest. A test that POSTs through one needs
  `@pytest.mark.django_db(transaction=True)`.
- Never write a `GeneratedField`. Never `instance.delete()`.
- Unabbreviated identifiers. Components, not HTML strings. `ControlButton`,
  not a wrapped `<a>`.
- `make vale` refuses `fold`, `seam`, `tombstone`, `archive`, `delete`, `heal`
  in prose and comments. Write "remove".
- Commit messages end with
  `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.

## Step 0 — before any edit

```bash
git fetch origin && git rebase origin/main
```

## File map

| File | Responsibility |
|---|---|
| `common/criteria.py` | `for_numbers()` gains two members; four `to_q` bodies gain two branches |
| `common/components/filters.py` | `NumberFilter`'s option list gains two labels |
| `games/events/playersession.py` | `PlayerSessionReclassifiedPayload`, the `EventSpec`, its builder |
| `games/events/dispatch.py` | two `CommandName` members |
| `games/models.py` | `PlayerSession.reclassified_into` |
| `games/migrations/` | one generated migration |
| `games/projections.py` | one `AUDITED_PROJECTION_REFERENCES` entry |
| `games/projectors/playersession.py` | `_reclassified` handler |
| `games/commands/historical_playtime.py` | `created_event` extracted; `RestoreHistoricalPlaytime` guard |
| `games/commands/playersession.py` | `statement_from_session`, the two new commands, `RestoreSession` guard |
| `games/writes/playersession.py` | `reclassify_session`, `undo_reclassification` |
| `games/forms.py` | `HistoricalPlaytimeForm(session=…)` |
| `games/views/session_reclassification.py` | **new** — the three views |
| `games/views/returns.py` | three route names |
| `games/urls.py` | three routes |
| `common/components/domain.py` | "Was an estimate" in `SessionActions` |
| `games/views/session.py` | the review row above the quick bar |
| `docs/event-retention.md` | the Naming case |

---

### Task 1 — Greater-or-equal in the leaf number path

Ships alone and is worth its own review: it changes a shared algebra.

**Files:** modify `common/criteria.py`, `common/components/filters.py`; test
`tests/test_filters.py`, `tests/test_quick_filter_bar.py`.

**Interfaces produced:** `Modifier.GREATER_THAN_OR_EQUAL` and
`LESS_THAN_OR_EQUAL` usable as leaf number/date criteria and offered by
`NumberFilter`.

- [ ] **Step 1 — failing tests.** In `tests/test_filters.py`, one test per
      criterion class that owns a numeric `to_q` (`IntCriterion`,
      `FloatCriterion`, `DateCriterion`) asserting `>= v` compiles to
      `__gte` and `<= v` to `__lte`; one asserting a `duration_hours`
      criterion at `GREATER_THAN_OR_EQUAL` matches a session of exactly the
      threshold and `GREATER_THAN` does not. In `tests/test_quick_filter_bar.py`,
      one asserting `NumberFilter` renders both new options and that a
      `GREATER_THAN_OR_EQUAL` criterion survives a render/parse round trip
      instead of degrading to `EQUALS`.
- [ ] **Step 2 — run them, see them fail.**
      `make test ARGS="tests/test_filters.py tests/test_quick_filter_bar.py -k equal"`.
      Expect the modifier to fall back to `EQUALS` and the `__gte` assertions
      to fail.
- [ ] **Step 3 — implement.** Add both members to `Modifier.for_numbers()`
      (`common/criteria.py:155`); `for_dates()` returns `for_numbers()`, so
      dates follow. Add a `__gte`/`__lte` branch beside the existing
      `GREATER_THAN`/`LESS_THAN` branch in each of the three leaf `to_q`
      bodies (around `:468`, `:506`, `:544`) and in `_numeric_to_q`
      (`:2001`). Add `("GREATER_THAN_OR_EQUAL", "is at least")` and
      `("LESS_THAN_OR_EQUAL", "is at most")` to `NumberFilter`'s `options`
      (`common/components/filters.py:856`).
- [ ] **Step 4 — the TypeScript is deliberately untouched.** `readNumberWidget`
      (`ts/elements/filter-widgets.ts:74`) reads the select's value verbatim,
      so the new options round-trip with no change. Do **not** touch
      `buildRangeCriterion` (`:47`) — its min/max bounds keep their present
      exclusive meaning. If a contract fixture in
      `ts/elements/filter-tree/fixtures.json` needs a case, add one and let
      `tests/test_filter_tree_contract.py` prove the two languages agree.
- [ ] **Step 5 — green, then commit.** `make check-fast`.

---

### Task 2 — The event, the column, the projector

**Files:** modify `games/events/playersession.py`, `games/events/dispatch.py`,
`games/models.py`, `games/projections.py`,
`games/projectors/playersession.py`; create one migration; test
`tests/test_playersession_events.py`, `tests/test_playersession_projection.py`.

**Interfaces produced:**

```python
PLAYERSESSION_RECLASSIFIED: EventSpec  # "library.playersession.reclassified"
def playersession_reclassified(session_id: uuid.UUID, *, record_id: uuid.UUID) -> NewEvent
PlayerSession.reclassified_into  # FK to HistoricalPlaytime, null, RESTRICT
CommandName.PLAYERSESSION_RECLASSIFY = "library.playersession.reclassify"
CommandName.PLAYERSESSION_UNDO_RECLASSIFICATION = "library.playersession.undo_reclassification"
```

- [ ] **Step 1 — failing tests.** `tests/test_playersession_events.py`: the
      payload refuses a key that is not canonical UUID text and refuses an
      extra key (`STRICT_SCHEMA`). `tests/test_playersession_projection.py`:
      applying `reclassified` sets `removed_at` to the event's `recorded_at`
      **and** `reclassified_into`; applying `restored` afterwards clears
      `removed_at` and **leaves** `reclassified_into`.
- [ ] **Step 2 — run, fail.**
      `make test ARGS="tests/test_playersession_events.py tests/test_playersession_projection.py"`.
- [ ] **Step 3 — the payload and spec.** In `games/events/playersession.py`,
      beside `PlayerSessionMovedPayload`, a `TypedDict` with the single field
      `record: ReferenceId` under `@with_config(STRICT_SCHEMA)`; the
      `EventSpec` with `aggregate_type="playersession"`; register it in
      `DEFAULT_EVENT_TYPES`; the builder taking `record_id` and writing
      `{"record": str(record_id)}`. A bare `ReferenceId`, not a `Reference`:
      the record row does not exist when the event is built. The anonymizer
      picks the key up automatically, because `aggregate_id_keys` reads the
      annotation's alias name.
- [ ] **Step 4 — the two command names** in `CommandName`
      (`games/events/dispatch.py:76`).
- [ ] **Step 5 — the column.** In `games/models.py`, on `PlayerSession`, after
      `removed_at`:

```python
#: The record this session became; the mark beside it is removed_at.
reclassified_into = models.ForeignKey(
    "HistoricalPlaytime",
    on_delete=models.RESTRICT,
    null=True,
    default=None,
    related_name="reclassified_sessions",
)
```

      `default=None` is load-bearing: it is what keeps the column out of
      `_required_columns`, so `_created` need not name it.

- [ ] **Step 6 — the migration.** `make makemigrations ARGS="games --name session_reclassified_into"`.
      The target passes `--noinput`; check the generated file adds one
      nullable FK and nothing else.
- [ ] **Step 7 — the audit entry.** `ProjectionReference.on(PlayerSession, "reclassified_into")`
      into `AUDITED_PROJECTION_REFERENCES` (`games/projections.py:115`), in
      the tuple's sorted position. Without it
      `tests/test_projection_references.py:105` and
      `tests/test_playersession_projection.py:415` fail before `games.E009`
      is reached.
- [ ] **Step 8 — the handler.** `_reclassified` in `PlayerSessions` amends
      `removed_at=event.recorded_at` and
      `reclassified_into_id=uuid.UUID(event.payload["record"])`; add it to
      `handles`. Leave `_restored` alone — clearing `removed_at` only is the
      behaviour the tests in Step 1 pin.
- [ ] **Step 9 — green, commit.** `make check-fast`.

---

### Task 3 — The Reclassify command

**Files:** modify `games/commands/historical_playtime.py`,
`games/commands/playersession.py`; test
`tests/test_session_reclassification.py` (**new**).

**Interfaces consumed:** Task 2's event builder and command names.

**Interfaces produced:**

```python
# games/commands/historical_playtime.py
def created_event(
    runs: Sequence[Playthrough],
    device: Device | None,
    statement: HistoricalPlaytimeStatement,
) -> NewEvent

# games/commands/playersession.py
def statement_from_session(
    session: PlayerSession,
    provenance: HistoricalPlaytimeProvenance = HistoricalPlaytimeProvenance.MANUALLY_ENTERED,
) -> HistoricalPlaytimeStatement

class ReclassifySessionAsHistoricalPlaytime(Command):
    session_id: uuid.UUID
    statement: HistoricalPlaytimeStatement
```

- [ ] **Step 1 — extract first, no behaviour change.** Move the body of
      `RecordHistoricalPlaytime.build`'s event construction into
      `created_event(runs, device, statement)`; `build` resolves `runs` with
      `_live_runs` and `device` with `library_device`, then calls it. Run
      `make test ARGS="tests/test_historical_playtime_command.py"` — it must
      stay green with no test edits. Commit this alone.
- [ ] **Step 2 — failing tests** in `tests/test_session_reclassification.py`:
      - a Duration-only session converts: exactly two events appended, in the
        order created-then-reclassified, one `correlation_id`, the record's
        columns equal to the session's, `when` equal to the session's
        `effective_day` at day precision;
      - the session row is removed and names the record;
      - a running Timed row is refused, with its sentence;
      - a finished Timed row is **admitted** (the command's rule; the screen
        is what narrows it);
      - a statement naming a run of another game is refused;
      - a statement naming a sibling run of the same game is admitted;
      - a session whose device was removed converts, because the session
        holds it — the regression that would otherwise refuse 91 of 93 rows;
      - a device named anew and removed is refused;
      - the same command under the same idempotency key twice appends one
        pair;
      - a removed session, a removed run and a removed game are each refused
        by `_live_session`.
- [ ] **Step 3 — run, fail.**
      `make test ARGS="tests/test_session_reclassification.py"`.
- [ ] **Step 4 — implement.** `statement_from_session` reads
      `effective_duration`, `effective_day`, `playthrough_id`, `device_id`,
      `emulated`, `note`. The command's `build`:
      1. `session = _live_session(context, self.session_id)`;
      2. refuse a running Timed row —
         `timing_mode == TIMED and ended_at is None`;
      3. `runs = _live_runs(context, self.statement)`, then refuse unless
         every run's `player_game_id` equals the session's run's;
      4. resolve the device with `library_device_row` when
         `statement.device_id == session.device_id`, else `library_device` —
         the rule `RestateHistoricalPlaytime` already uses
         (`games/commands/historical_playtime.py:283`);
      5. return `[created_event(...), playersession_reclassified(session.pk, record_id=<the created event's aggregate_id>)]`.

      Read the record id off the event the first call returns; do not mint a
      second one.

      Every refusal carries a `sentence=`. A refusal whose cause is the row
      rather than the statement raises `RowUnreadable`, not `CommandRejected`.

- [ ] **Step 5 — pin what moves.** In the same file, one test per figure the
      spec's "What moves" section names, so the change is recorded rather
      than discovered: after converting a game's only session, the game's
      playtime total is unchanged, `total_sessions` falls by one, and the
      run's `activity` alias reads `Never played` — the last is the one a
      person sees, on Game detail and in the `activity` facet
      (`games/reads/playthrough_activity.py`).
- [ ] **Step 6 — green, commit.**

---

### Task 4 — The undo, and the two symmetric guards

**Files:** modify `games/commands/playersession.py`,
`games/commands/historical_playtime.py`; test
`tests/test_session_reclassification.py`.

**Interfaces produced:** `UndoSessionReclassification(session_id: uuid.UUID)`.

- [ ] **Step 1 — failing tests.**
      - the undo appends two events, removes the record and restores the
        session, under one correlation id;
      - pressing it twice appends nothing the second time (`Unchanged`);
      - a session that states no `reclassified_into` is refused;
      - a record already removed by hand: the undo still returns the session
        and appends only the restore;
      - `RestoreSession` alone is refused while the record is live, and the
        sentence names the record;
      - `RestoreSession` alone is admitted once the record is removed;
      - `RestoreHistoricalPlaytime` is refused while a live session names the
        record;
      - `RestoreSession` on a live session still answers `Unchanged`, not the
        new refusal — the ordering pin.
- [ ] **Step 2 — run, fail.**
- [ ] **Step 3 — implement.** `UndoSessionReclassification.build`: the no-op
      first (session live and record removed → `Unchanged`), then the refusal
      (no `reclassified_into`), then the events — the record's `removed` only
      when the record is live, and the session's `restored` only when it is
      removed. In `RestoreSession.build`, after its existing `Unchanged` and
      before the event, refuse when `reclassified_into` names a live record.
      In `RestoreHistoricalPlaytime.build`, after its `Unchanged`, refuse when
      a live `PlayerSession` names the record.
- [ ] **Step 4 — green, commit.**

---

### Task 5 — The replay gate

**Files:** modify `tests/test_projection_replay_gate.py`.

- [ ] **Step 1 — fix the removal order first.** In `empty_projections`
      (`:552`), move `PlayerSession` **above** `HistoricalPlaytime`. Once a
      session names a record, removing records first raises
      `RestrictedError`, because the column persists through the undo by
      design.
- [ ] **Step 2 — add the legs to `build_stream`:** one conversion of a
      Duration-only session, and one conversion that is then undone, so both
      new event types and both sides of the mark appear. Use the `run(...)`
      helper so each carries its own key.
- [ ] **Step 3 — raise the guard count.** `assert len(missing) == 26` at
      `:426` becomes 27.
- [ ] **Step 4 — run the whole gate.**
      `make test ARGS="tests/test_projection_replay_gate.py"`. All of it:
      every-type coverage, the emptied-library replay, the shadow swap with an
      empty diff, and every command repeated under its key recording nothing.
- [ ] **Step 5 — commit.**

---

### Task 6 — The writes layer and the form

**Files:** modify `games/writes/playersession.py`, `games/forms.py`; test
`tests/test_session_writes.py`, `tests/test_historical_playtime_form.py`.

**Interfaces produced:**

```python
# games/writes/playersession.py — takes an actor, never a request
def reclassify_session(
    actor: User,
    session: PlayerSession,
    statement: HistoricalPlaytimeStatement,
    *,
    idempotency_key: IdempotencyKey,
    correlation_id: uuid.UUID,
) -> uuid.UUID          # the record's id
def undo_reclassification(
    actor: User, session: PlayerSession, *, correlation_id: uuid.UUID
) -> None
```

- [ ] **Step 1 — failing tests.** For the writes: a refusal becomes
      `CommandFailed` with the command's sentence, under
      `answered("session")`. For the form: a form built with `session=`
      keeps the session's run selected and its provenance, rather than the
      latest run and `Estimated`; the session's device is among the choices
      even when removed; `submission` is still rendered.
- [ ] **Step 2 — run, fail.** The form tests fail today because
      `_record_initial` runs after the caller's `initial` and overwrites it
      (`games/forms.py:1163`).
- [ ] **Step 3 — implement the writes** beside `record_session`, each wrapped
      in `answered("session")`, reusing the module's `_dispatch`.
- [ ] **Step 4 — implement the form parameter.** `HistoricalPlaytimeForm`
      takes `session: PlayerSession | None = None` beside `record`. When it is
      given, the seed is the session's run and the caller's provenance, and
      the device queryset is widened with the session's own device exactly as
      the `record` branch widens it (`:1188`). `record` and `session` are
      mutually exclusive; raise `TypeError` if both arrive.
- [ ] **Step 5 — green, commit.**

---

### Task 7 — The one-row screen

**Files:** create `games/views/session_reclassification.py`; modify
`games/urls.py`, `games/views/returns.py`, `common/components/domain.py`;
test `tests/test_session_reclassification_views.py` (**new**),
`tests/test_session_actions_component.py`.

- [ ] **Step 1 — failing tests.** GET renders the prefilled form; POST
      converts and redirects to the origin; the Undo toast carries the
      restore route with the session key; POST to the undo route reverses the
      pair; a refusal re-renders the form with the command's sentence and its
      status code; "Was an estimate" appears on a Duration-only row and not on
      a Timed one; a repeated POST under the same `submission` records one
      record. Mark POST tests `@pytest.mark.django_db(transaction=True)`.
- [ ] **Step 2 — run, fail.**
- [ ] **Step 3 — the views.** `reclassify_session` mirrors
      `add_historical_playtime` (`games/views/historical_playtime_entry.py:80`):
      resolve the session through the library, build the form with
      `session=`, call `reclassify_session` under `form.submission_key()`,
      queue the success notice with an `UndoOffer` naming
      `games:undo_reclassify_session` and `[session.pk]`. Thread
      `FORM_SCRIPTS` — the temporal and search-select modules — because the
      widget's `Media` never bubbles. `undo_reclassify_session` is
      `@require_POST` over `restore_and_return`.
- [ ] **Step 4 — the row action.** In `SessionActions`
      (`common/components/domain.py:606`), a fifth `ButtonGroup` member,
      conditional on `timing_mode == DURATION_ONLY`, built with `action_url`
      so `tests/test_action_origin_parity.py` passes.
- [ ] **Step 5 — the routes,** and both names into `ORIGIN_AWARE` in
      `games/views/returns.py`, or `tests/test_returns_classification.py`
      fails. Add the undo route to `ROUTES` in
      `tests/test_restore_routes.py:118`.
- [ ] **Step 6 — green, commit.**

---

### Task 8 — The review and the bulk conversion

**Files:** modify `games/views/session_reclassification.py`,
`games/views/session.py`, `games/urls.py`, `games/views/returns.py`; test
`tests/test_session_reclassification_views.py`, `tests/test_session_list.py`.

- [ ] **Step 1 — failing tests.** The session list carries a "Review
      estimates" link whose `?filter=` parses and leaves the quick bar
      editable (assert `is_quick_editable` over the parsed dict, not the
      rendered HTML alone); the confirm page lists every matching row and not
      just the page, with one hidden input per row; the POST converts exactly
      the posted keys; a posted key that is not Duration-only is refused; a
      posted key of another library is refused; one refused row does not stop
      the rest and the answer names both counts; a second submit under the
      same token converts nothing new.
- [ ] **Step 2 — run, fail.**
- [ ] **Step 3 — the review row.** In `games/views/session.py:248`, between
      `PlaytimeTabs("sessions")` and `quick_bar`, a `Div` holding the two
      links. The filter JSON is built from one constant:

```python
REVIEW_THRESHOLD_HOURS = 8
# timing_mode is a set criterion: a list value and INCLUDES.
```

      Build it with the criterion classes and serialize, rather than writing
      JSON by hand, so it cannot drift from what the parser accepts.

- [ ] **Step 4 — the bulk view** through `confirm_and_apply`. The GET builds
      the row list from the filter; the POST builds it from
      `request.POST.getlist(...)`, so a re-render after a refusal shows what
      was acted on. Refuse any key whose row is not Duration-only before
      dispatching anything. The action closure catches every `CommandFailed`
      itself and raises none — `confirm_and_apply` discards the return and
      turns one raised refusal into a re-rendered page — and queues its own
      answer through `common/notices.py`: the converted count, then one line
      per distinct refusal sentence. One `correlation_id` for the whole
      request; each row's idempotency key is the submit token and the session
      key.
- [ ] **Step 5 — the route name** into `ORIGIN_AWARE`.
- [ ] **Step 6 — green, commit.**

---

### Task 9 — Prose, the browser, and the sibling issue

**Files:** modify `docs/event-retention.md`; create
`e2e/test_session_reclassification_e2e.py`.

- [ ] **Step 1 — the Naming case.** In the Naming section of
      `docs/event-retention.md`, after the two-column paragraph: an act that
      includes a removal states the removal's mark and adds its own
      reference, never a second mark; `reclassified_into` beside `removed_at`
      is the case, and the reason is that every session scope already states
      the one mark.
- [ ] **Step 2 — e2e.** The review link from the session list, one conversion
      through the form, the Undo from the toast, and a console check for the
      module scripts the form loads. Never run e2e while `make dev` is up.
- [ ] **Step 3 — comment on #795** with the orphaned-record case the spec's
      last section names, so the Trash owns the rule when it arrives.
- [ ] **Step 4 — `make vale`,** then commit.

---

### Task 10 — The rehearsal and the gate

- [ ] **Step 1 — restore the copy.** `make fetch-dump` if none is local, then
      `make restore-dump`, then `make migrate` against the printed
      `DATABASE_URL`.
- [ ] **Step 2 — measure before.** `make render-pages ARGS="--user <name> --out before"`,
      and record `total_sessions`, `unique_days`, the longest session, the
      highest average, the first and last play, and every playtime total per
      scope.
- [ ] **Step 3 — convert** the rows of 8 hours or longer through the screen.
- [ ] **Step 4 — measure after,** `diff -r before after`, and attribute every
      differing file. Every playtime total must be equal; `total_sessions`
      falls by the converted count; each of the five session figures that
      moved is attributed to a converted row.
- [ ] **Step 5 — write the numbers into the spec's Verification section,**
      replacing the sentence that promises them.
- [ ] **Step 6 — the gate.**

```bash
flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make check 2>&1 | tee /tmp/check.log; echo "exit=$?"
```

      Read the exit code, not the tail.

- [ ] **Step 7 — drop the scratch database** (`make drop-dump`), commit, open
      the PR.

## Follow-up issues to file

- None new. The one deferral — a record restored after its session was
  converted a second time — belongs to the Trash, #795, and Task 9 Step 3
  records it there rather than opening a duplicate.

## Notes for whoever executes this

- Tasks 1, 2 and 3 are the natural first dispatch; 4, 5 and 6 the second; 7,
  8 and 9 the third. The controller owns the gate — do not run a full
  `make check` per task.
- Task 3 Step 1 is a pure extraction and must be committed before any
  behaviour rides on it, so a later bisect can tell the refactor from the
  feature.
- The two places this design has already been got wrong once, both caught in
  review: the form's seed overwrites the caller's `initial`, and
  `library_device` refuses the device the session already holds. Both have a
  named test above. Do not "simplify" either back.
