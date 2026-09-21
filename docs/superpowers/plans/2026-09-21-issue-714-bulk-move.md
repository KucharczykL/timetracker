# Bulk move sessions to a playthrough — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: use `superpowers:subagent-driven-development`
> or `superpowers:executing-plans`. Steps are checkboxes.

**Goal:** A person selects sessions on the session list and moves them to one
playthrough, as one batch they can undo as one.

**Architecture:** The bulk runner gains one concept — an act may ask for a fact
before it runs (`BulkChoice`), carried as one string in one runner-named field.
The move declares that act. No new route, no new page, no migration.

**Tech Stack:** Django 6, Python 3.14, pytest/pytest-xdist, Playwright e2e,
Python component system (no templates), Django Ninja.

**Spec:** [Move many sessions to one playthrough](../specs/2026-09-21-issue-714-bulk-move-design.md) — read it first; this plan argues from it and does not restate its reasoning.

**Issue:** [#714](https://github.com/KucharczykL/timetracker/issues/714).
Prerequisite #1080 is merged (`63b5940f`).

## Global Constraints

- Run everything through `make`. Never `uv run` / `pytest` / `pnpm` directly.
- Iterate with `make check-fast`; the gate is one full `make check` at the end,
  under `flock "$(git rev-parse --git-common-dir)/heavy-tests.lock"`.
- `make format` **and** `make lint-fix` before every commit (only `lint-fix`
  sorts imports; `format` alone leaves I001 to redden the gate).
- Refused words are enforced by `make vale`: never *delete*, *archive*,
  *tombstone*, *seam*, *fold*, *heal*. Write **remove**.
- Unabbreviated identifiers. Compound and primitive roles get named types
  (PEP 695 aliases).
- Comments explain intent only — no issue or PR references.
- A view that dispatches carries no `@transaction.atomic`; tests that POST
  through one need `@pytest.mark.django_db(transaction=True)`.
- Never write to a `GeneratedField` (`effective_day`, `effective_duration`,
  `sort_instant`).

---

### Task 1: The reads the act needs

Four reads, none of which exists. Pure functions, testable with no runner.

**Files:**
- Create: `games/reads/session_run_labels.py`
- Modify: `games/reads/events.py` (add `aggregate_events`)
- Modify: `games/reads/playthrough_runs.py` (add `buckets_of`)
- Modify: `games/reads/playthrough_referrers.py` (add `rows_naming`)
- Modify: `games/views/session.py` — remove `IMPORTED_HISTORY_LABEL`,
  `RunLabels`, `run_labels_for` (lines 101–132); import them from the new read
- Test: `tests/test_session_run_labels.py` (create),
  `tests/test_events_reads.py` (extend or create), `tests/test_playthrough_runs.py`

**Interfaces — Produces:**

```text
games/reads/session_run_labels.py
    type PlaythroughId = uuid.UUID
    type RunLabel = str
    type RunLabels = dict[PlaythroughId, RunLabel]
    IMPORTED_HISTORY_LABEL: str = "Imported history"
    every_run_label(library, sessions: Sequence[PlayerSession]) -> RunLabels
    ambiguous_run_labels(library, sessions) -> RunLabels

games/reads/events.py
    aggregate_events(library, aggregate_id: uuid.UUID) -> LibraryEventQuerySet

games/reads/playthrough_runs.py
    buckets_of(library, player_game: PlayerGame) -> QuerySet[Playthrough]

games/reads/playthrough_referrers.py
    rows_naming(referrer: BlockingReferrer, run: Playthrough) -> QuerySet[Any]
```

**Gotchas:**
- `every_run_label` is today's `run_labels_for` **without** its final
  comprehension (`games/views/session.py:127-131`), which keeps only runs whose
  game has siblings. `ambiguous_run_labels` is `every_run_label` plus that
  comprehension. The view keeps calling the narrow one — its column must not
  change.
- The labels come from `numbered_for(library, player_game_ids)`, which is what
  states `display_number`; a bucket is not in it, so the bucket's label is
  stamped separately, as today.
- `buckets_of` reads `Playthrough.objects.filter(library=…, player_game=…,
  kind=IMPORTED_HISTORY, removed_at__isnull=True, …)`. Plural: nothing
  constrains a game to one bucket. Mirror `live_ordinary_runs`' own shape
  (`games/reads/playthrough_runs.py:46`), which states the parent's facts
  rather than narrowing `library_runs`.
- `rows_naming` is `_live_rows_naming`
  (`games/reads/playthrough_referrers.py:112`) with `_default_manager` instead
  of `.alive()`, and **unscoped by library** — a foreign row naming the run is
  drift, which is a reason to leave the run alone.
- `aggregate_events` orders by `sequence` and rides the
  `library_event_aggregate` index (migration 0012). No migration.

**Steps:**

- [ ] **1.1** Write failing tests: `every_run_label` labels a session on a
      game holding exactly one ordinary run (today's reader answers `{}` there);
      it labels a bucket as "Imported history"; `ambiguous_run_labels` still
      answers `{}` for the one-run game.
- [ ] **1.2** Write failing tests: `buckets_of` answers a game's two buckets
      and skips a removed one; `rows_naming` finds a **removed** session naming
      a run where `_live_rows_naming` finds none; `aggregate_events` answers
      one session's events in sequence order and no other aggregate's.
- [ ] **1.3** `make test-fast ARGS="tests/test_session_run_labels.py tests/test_playthrough_runs.py -x"` → FAIL (import errors).
- [ ] **1.4** Implement the four reads; move the three names out of
      `games/views/session.py` and re-import them there.
- [ ] **1.5** `make test-fast ARGS="tests/test_session_run_labels.py tests/test_playthrough_runs.py tests/test_events_reads.py -x"` → PASS.
- [ ] **1.6** `make test-fast ARGS="tests/test_session_list.py -x"` → PASS
      (the list's own column is unchanged).
- [ ] **1.7** `make format && make lint-fix`, then commit.

---

### Task 2: `move_session` answers a result and takes a key

**Files:**
- Modify: `games/writes/playersession.py:213-229`
- Test: `tests/test_session_writes.py`

**Interfaces — Produces:**

```text
move_session(actor, session, playthrough_id, *, correlation_id,
             idempotency_key: IdempotencyKey | None = None,
             source_metadata: SourceMetadata | None = None) -> CommandResult
```

**Gotchas:**
- Copy the shape of `remove_session` / `remove_run` exactly — both keywords
  optional and keyword-only, the result returned rather than dropped. The
  single-row route states neither.
- `SourceMetadata` is `games/events/append.py:36`.
- The existing caller in `games/writes/playersession.py` (`restate_session`)
  and the API's move path must keep compiling; they ignore the result.

**Steps:**

- [ ] **2.1** Write a failing test: the same key twice appends once and the
      second answers `CommandOutcome.REPLAYED`; `source_metadata` lands on the
      event.
- [ ] **2.2** `make test-fast ARGS="tests/test_session_writes.py -k move -x"` → FAIL.
- [ ] **2.3** Add the two keywords and the return.
- [ ] **2.4** Same command → PASS.
- [ ] **2.5** `make format && make lint-fix`, commit.

---

### Task 3: Widen the act signatures (no behaviour change)

Mechanical. Every act keeps doing what it does; the batch stays green.

**Files:**
- Modify: `games/bulk_actions.py` — `ChoiceValue`, `BulkChoice`,
  `BulkAction.choice`, `RunRow`, `UndoRow`
- Modify: `games/views/bulk.py` — `Leg.choice`, `_forward`, `_backward`,
  the `leg.run(...)` call at `games/views/bulk.py:391`
- Modify: `games/bulk_removal.py` (six callables),
  `games/bulk_reclassification.py` (two)
- Test: `tests/test_bulk_removal.py` (13 call sites),
  `tests/test_bulk_actions.py` (6 call sites, 4 `BulkAction` constructions)

**Interfaces — Produces:**

```text
type ChoiceValue = str          # e.g. a target run's key, or a batch's id

class BulkChoice[RowT: Model]:
    offer:  Callable[[UserLibrary, Sequence[RowT], FieldName], Node | str]
    settle: Callable[[UserLibrary, QueryDict], ChoiceValue]

BulkAction.choice: BulkChoice[RowT] | None = None

type RunRow[RowT] = Callable[
    [User, RowT, ChoiceValue, IdempotencyKey, uuid.UUID], RowOutcome]
type UndoRow = Callable[
    [User, uuid.UUID, ChoiceValue, IdempotencyKey, uuid.UUID], RowOutcome]

Leg.choice: ChoiceValue
```

**Gotchas:**
- The choice is the **third** positional, after the row — it is about the act,
  not about the append, and the two append arguments stay last together.
- All eight existing callables ignore it. Name the parameter `choice` and let
  it be unused; do not prefix it with an underscore, since the alias names it.
- `BulkAction.__post_init__` gains no rule here. Task 4 adds the one that
  matters.
- `_forward` and `_backward` both state a `choice`; in this task both state
  `""`.

**Steps:**

- [ ] **3.1** Write a failing test in `tests/test_bulk_actions.py`: a declared
      act's `run` receives the leg's choice as its third argument.
- [ ] **3.2** `make test-fast ARGS="tests/test_bulk_actions.py -x"` → FAIL.
- [ ] **3.3** Widen the two aliases, `Leg`, `_forward`, `_backward` and the
      call site; add `choice` to all eight callables and every test call site.
- [ ] **3.4** `make test-fast ARGS="tests/test_bulk_actions.py tests/test_bulk_removal.py tests/test_bulk_runner.py -x"` → PASS.
- [ ] **3.5** `make typecheck` → clean.
- [ ] **3.6** `make format && make lint-fix`, commit.

---

### Task 4: The runner asks, and re-asks

**Files:**
- Modify: `games/views/bulk.py` — `CHOICE_FIELD`, settle in `run_bulk_action`,
  `_backward`'s choice, `_reconfirmation`
- Modify: `games/views/bulk_pages.py` — `ConfirmBatch(refusal=…)`, the choice
  slot, the wider page
- Modify: `common/components/primitives.py` — `ConfirmPage` takes a width and a
  left-aligned block slot
- Test: `tests/test_bulk_runner.py`, `tests/test_rendered_pages.py`

**Interfaces — Produces:**

```text
games/views/bulk.py
    CHOICE_FIELD = "choice"
    type FieldName = str
    UNREADABLE_CHOICE: str   # the sentence for an act that asks and got nothing

games/views/bulk_pages.py
    ConfirmBatch(..., refusal: Sequence[str] = (), choice: Node | None = None)

common/components/primitives.py
    ConfirmPage(..., refusal=(), choice: Children = None,
                max_width: str = FORM_MAX_WIDTH_CLASS)
```

**Gotchas:**
- **`run_bulk_action` settles; `undo_bulk_action` never does.** Both reach
  `_run_a_chunk`, and an undo POST carries no picker — settling there refuses
  every Undo of an asking act on its first request.
- `_backward` states `str(correlation_id)` — the route's own argument, re-read
  on every undo POST (`games/views/bulk.py:669`). `_run_a_chunk` derives its
  correlation id from the undo's **fresh** token (`games/views/bulk.py:379`),
  so this is the only way the batch's id reaches `action.inverse`.
- The gate is `declared.choice is not None`, never the field's truth: `""` is a
  value and `request.POST.get` cannot tell it from an absent field.
- **`_confirmation` must not draw the settle refusal.** It mints a fresh token
  (`games/views/bulk.py:265`) and a fresh `Tally` whose counts reset and whose
  `total` shrinks to the rows left — a mid-batch re-render would split one
  batch across two correlation ids and orphan half the Undo. `_reconfirmation`
  takes the posted token and tally verbatim and re-resolves `tally.rows` for
  its table.
- `ConfirmPage`'s `details` is `text-center` and heading-coloured
  (`common/components/primitives.py:2191`) — right for a list of rows, wrong
  for a labelled control. The choice gets its own left-aligned slot.
- `ProgressBatch` already takes `hidden` as an open pair list, so carrying
  `CHOICE_FIELD` forward is free.

**Steps:**

- [ ] **4.1** Write failing tests: a token POST on an asking act with no
      choice field is refused and writes nothing; the progress form carries the
      choice into the next chunk; three chunks settle three times; an act with
      no choice never settles; the undo leg's choice is the batch's correlation
      id.
- [ ] **4.2** Write a failing test: a refused settle answers 400, keeps the
      posted token, lists the tally's rows, and shows the sentence.
- [ ] **4.3** `make test-fast ARGS="tests/test_bulk_runner.py -x"` → FAIL.
- [ ] **4.4** Implement `CHOICE_FIELD`, the settle call, `_backward`'s choice,
      `_reconfirmation`, `ConfirmBatch`'s two new parameters and `ConfirmPage`'s
      two.
- [ ] **4.5** `make test-fast ARGS="tests/test_bulk_runner.py tests/test_bulk_removal.py tests/test_rendered_pages.py -x"` → PASS.
- [ ] **4.6** `make format && make lint-fix`, commit.

---

### Task 5: The move act, forward

**Files:**
- Create: `games/bulk_move.py`
- Modify: `games/bulk_actions.py` — import it at the foot beside the other two
- Modify: `games/bulk_removal.py` — `session_resolution` gains
  `select_related("device")`
- Test: `tests/test_bulk_move.py` (create)

**Interfaces — Consumes:** Task 1's `every_run_label`, `buckets_of`,
`rows_naming`; Task 2's `move_session`; Task 3's `BulkChoice`, `ChoiceValue`;
Task 4's `CHOICE_FIELD`.

**Interfaces — Produces:**

```text
MOVE: BulkAction[PlayerSession]          # name="session.move"
TARGET: BulkChoice[PlayerSession]
move_scope(library, filter_json)  -> QuerySet[PlayerSession]
move_resolution(library, keys)    -> Resolution[PlayerSession]
offer_target(library, rows, field_name) -> Node | str
settle_target(library, post)      -> ChoiceValue
move_one(actor, session, choice, idempotency_key, correlation_id) -> RowOutcome
```

**Declaration:** `name="session.move"`, `label="Move to playthrough…"`,
`title="Move these sessions to a playthrough"`,
`confirm_label="Move"`, `subject="session"`, `cardinality=MANY`,
`color="blue"`, `inverse_aggregate="playersession"`,
`fallback="games:list_sessions"`.

**Preview columns:** Playthrough, Day, Duration, Device, Note. No Game column.

**Gotchas:**
- **The label must be attached by the resolve.** `display_name` *raises*
  `UnnumberedPlaythrough` for a blank-named ordinary run carrying no
  `display_number` (`games/reads/playthrough_numbering.py:101`), and a session's
  `select_related` run never carries one. The resolve attaches a label per row
  from `every_run_label`; the cell reads it and raises `RowUnreadable` for a row
  that arrives without one, as `playthrough_tabledata` refuses a run with no
  condition alias.
- **`offer` reads every resolved row**, not the printed fifty, or the game
  count is the sample's. More than one distinct `player_game__game_id` answers
  the refusal sentence, naming the count and the `game` quick facet.
- The control is `SearchSelect(name=field_name, search_url=…, create_url=…,
  params={"game_id": LiteralParam(value=str(game_id))},
  prefetch=DEFAULT_PREFETCH, csrf=…)`. The key is **`game_id`**, not `game` —
  one mapping feeds the search and the create, and `game` 422s the search and
  leaves the create row hidden. Do **not** set `commit_sole_option`: the sole
  option is usually the run the rows already sit on.
- `settle_target` resolves the key against `library_runs(library)` and says
  nothing about the game.
- **`move_one` refuses a cross-game row itself**, comparing the row's
  `player_game_id` with the target's, with a sentence — the tally is
  person-editable by design, so the confirmation's whole-act refusal cannot
  stand in for this.
- **The bucket is asked about the game.** After a move that moved *or was
  already so*, walk `buckets_of(library, player_game)` and remove each bucket
  no `BLOCKING_REFERRERS` row names through `rows_naming`. Asking about the
  row's earlier run instead would never fire on a re-posted chunk, where the
  move answers `Unchanged`.
- **Two dispatches, two keys**: suffix the runner's key `-move` and `-bucket`,
  or the second raises `IdempotencyKeyMismatch` (409) after the first committed.
- **Swallow the bucket removal's answer.** A refusal there would mark a moved
  row refused, and `_refuse_a_foreign_referrer`'s `RowUnreadable` answers 500,
  which ends the whole batch. Catch, log, continue.

**Steps:**

- [ ] **5.1** Write failing tests for the scope and resolve: the filter
      narrows; a key of another library is lost; every row carries a label,
      including a session at a game holding one ordinary run and a bucket.
- [ ] **5.2** Write failing tests for `offer_target`: two games answer a
      sentence naming "2"; one game answers a node; the count is the
      selection's, not the sample's.
- [ ] **5.3** Write failing tests for `settle_target`: a non-uuid, another
      library's run, a removed run and a bucket each refuse; a live ordinary
      run answers its key; a run at another game answers its key too.
- [ ] **5.4** Write failing tests for `move_one`: a row moves; a row already
      on the target answers `UNCHANGED`; a row at another game refuses with a
      sentence; the last row out removes the bucket; a game with two buckets has
      both removed; a bucket named by a **removed** session is left alone; a
      bucket whose removal refuses leaves the row counted moved.
- [ ] **5.5** `make test-fast ARGS="tests/test_bulk_move.py -x"` → FAIL.
- [ ] **5.6** Implement `games/bulk_move.py`, register the import, add
      `select_related("device")`.
- [ ] **5.7** `make test-fast ARGS="tests/test_bulk_move.py tests/test_bulk_removal.py -x"` → PASS.
- [ ] **5.8** `make format && make lint-fix`, commit.

---

### Task 6: The move act, backward

**Files:**
- Modify: `games/bulk_move.py`
- Test: `tests/test_bulk_move.py`

**Interfaces — Produces:**

```text
run_before(library, session_id, batch_id: uuid.UUID) -> uuid.UUID
move_back(actor, session_id, choice, idempotency_key, correlation_id) -> RowOutcome
```

**Gotchas:**
- `choice` here is the **batch's correlation id** as text (Task 4).
- `run_before` finds the batch's own `library.playersession.moved` event for
  that aggregate, takes its `sequence`, then answers the `payload["playthrough"]`
  of the newest earlier event whose type is `…playersession.created` or
  `…playersession.moved`. Both payloads carry that key. A sequence counts within
  one library's stream, so the comparison is total.
- **Restore only what this batch removed.** `RestorePlaythrough` restores a run
  of any kind; an inverse restoring whatever it found removed would put back an
  ordinary run somebody removed by hand after the batch emptied it. Check the
  batch's events for that run's removal; refuse the row with a sentence
  otherwise.
- Restore first, move second: `MoveSessionToPlaythrough` refuses a removed
  target. `RestorePlaythrough` answers `Unchanged` once live, so later rows and
  repeats cost one silent dispatch.
- Keys: suffix `-restore` and `-move`.
- The run created ahead of the batch is **not** the batch's, so nothing here
  reaches it. Say so in the answer.

**Steps:**

- [ ] **6.1** Write failing tests: undo to the run a `created` payload named;
      undo to a run an earlier `moved` named; undo restores the bucket the
      batch removed; undo refuses a row whose earlier run was removed by hand
      after the batch; a key not of this batch is lost; the created run stays.
- [ ] **6.2** `make test-fast ARGS="tests/test_bulk_move.py -k undo -x"` → FAIL.
- [ ] **6.3** Implement `run_before` and `move_back`.
- [ ] **6.4** `make test-fast ARGS="tests/test_bulk_move.py -x"` → PASS.
- [ ] **6.5** `make format && make lint-fix`, commit.

---

### Task 7: The tray, the browser pass, the gate

**Files:**
- Modify: `games/views/session.py:223` — add `MOVE.name` to `tray_actions`
- Test: `e2e/test_bulk_move_e2e.py` (create), `tests/test_bulk_tray.py`

**Gotchas:**
- The act is declared whether or not the filter names a game; the game is the
  confirmation's question.
- E2E: never run while `make dev` is up — its watchers rewrite the served
  assets and cause mass phantom failures. Run `make ts` first so `dist/` is
  fresh.
- Seed through `create_tracked_game()` from `e2e/`'s own helper, never by
  writing status columns.

**Steps:**

- [ ] **7.1** Extend `tests/test_bulk_tray.py`: the session list offers three
      acts in order.
- [ ] **7.2** Write the browser pass: select two bucket sessions, "Move to
      playthrough…", pick a run, confirm; the rows read the run's name where
      they read "Imported history"; press Undo; the rows read "Imported
      history" again. Wait on the server-rendered section before any ORM read.
- [ ] **7.3** `make ts && make test-e2e ARGS="-k bulk_move"` → PASS.
- [ ] **7.4** `make format && make lint-fix`.
- [ ] **7.5** The gate:
      `flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make check`
      → green, read from the log's **exit code**, never a grep.
- [ ] **7.6** Commit, open the PR.

---

## Follow-up issues to file

File these with `gh issue create` when the plan is approved; none blocks #714.

1. **A picker cannot search a run's display number.** `GET
   /api/playthrough/search` narrows on the `name` column, so every unnamed
   `Playthrough N` leaves the panel as soon as a character is typed. Harmless
   while no game holds more than three runs; wrong for a library that grows.
   Belongs to #1080's route.
2. **Nothing holds a game to one imported-history run.** `buckets_of` is plural
   because no constraint says otherwise. Either a conditional
   `UniqueConstraint` or a line in the audit.
3. **The bulk confirmation's page width is a runner constant.** Task 4 gives
   `ConfirmPage` a `max_width`; whether every bulk confirmation should be wide,
   or only the ones with five columns, is an interface question for the rethink
   #1209 is parked against.

## Self-review notes

- Spec coverage: the choice (T3, T4), the move (T5), the bucket (T5), the run
  before (T6), the columns and the label (T1, T5), the control (T5), the
  refusals table (T4, T5, T6), the wiring (T2, T7).
- No task depends on a name another task did not produce; `ChoiceValue`,
  `CHOICE_FIELD`, `every_run_label`, `buckets_of`, `rows_naming`,
  `move_session` and `run_before` are each produced once and consumed by name.
- Nothing here needs a migration.
