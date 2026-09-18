# Reclassification amendment: implementation plan

> **For agentic workers:** executed inline in one session. Steps use checkbox
> (`- [ ]`) syntax for tracking. Names, interfaces, test cases and gotchas;
> the code is written at the file, not here.

**Goal:** Bring the branch to the amended spec: the reference on the record,
the restated mark, the undo decided by marks alone, the bulk page honest, dates
without the inclusive members.

**Architecture:** Same shapes as the branch holds. One column moves from the
session to the record and one is added; three guards become queries; the
undo's rules become one ordered table; the bulk view classifies keys before
it dispatches; three date handlers lose two branches.

**Spec:** `docs/superpowers/specs/2026-09-18-issue-1098-session-reclassification-design.md`

## Global constraints

- `make` targets only; `make test-fast ARGS="tests/<file>"` to iterate.
- Full `make check` once, at the end, on the user's word.
- One act, one verb: `restated` event, `restated_at` column.
- Comments explain intent only, seven words where they can; no issue refs.
- `make vale` after every docs edit.
- Commit per task.

---

## Task 1: Storage

**Files:**
- `games/models.py` — take `PlayerSession.reclassified_into` away; add
  `HistoricalPlaytime.reclassified_from` (FK `PlayerSession`, `RESTRICT`,
  null, `related_name="reclassified_records"`) and
  `HistoricalPlaytime.restated_at` (nullable `DateTimeField`, not editable).
- `games/events/historical_playtime.py` — `HistoricalPlaytimeCreatedPayload`
  extends the statement payload with `reclassified_from: NotRequired[ReferenceId]`;
  `HISTORICALPLAYTIME_CREATED` reads it; `historicalplaytime_created(...,
  reclassified_from: uuid.UUID | None = None)` sets the key only when given.
- `games/projectors/historical_playtime.py` — `_created` writes
  `reclassified_from_id` from the payload when present; `_restated` writes
  `restated_at=event.recorded_at`.
- `games/projectors/playersession.py` — `_reclassified` amends `removed_at` alone.
- `games/projections.py` — `ProjectionReference.on(HistoricalPlaytime,
  "reclassified_from")` replaces the session entry.
- `games/migrations/0011_session_reclassified_into.py` → rewritten as
  `0011_historicalplaytime_reclassified_from.py`: two `AddField`s, then
  `RunPython` stating `restated_at` from the latest
  `library.historicalplaytime.restated` event per aggregate. Working copies
  that applied the old 0011 run `make migrate ARGS="games 0010"` first.

**Tests:**
- `tests/test_historical_playtime_events.py` — created payload admits the key
  and refuses null for it; restated payload refuses it.
- `tests/test_historical_playtime_projection.py` — created writes the
  reference; restated sets `restated_at`; a second restatement moves it.
- `tests/test_playersession_projection.py` — reclassified amends the mark alone.
- `tests/test_projection_references.py`, `test_projection_model.py`,
  `test_uuid_identity_audit.py` — the registry entry moved.
- `tests/test_projection_replay_gate.py` — `empty_projections` deletes
  `HistoricalPlaytime` before `PlayerSession`; both new columns reproduce.
- A migration test: a record with a restated event before the column
  exists gets its `restated_at` (build with `migrator`-style raw insert, or
  assert `verify-replay-parity` logic on a restated fixture).

**Gotchas:**
- Django's `Collector` enforces `RESTRICT` in Python: any test helper that
  deletes sessions before records now raises `RestrictedError`.
- The rebuild swaps under deferred constraints; nothing there changes.
- `NotRequired` on a `@with_config(STRICT_SCHEMA)` TypedDict: check pydantic
  refuses `None` as the value.

## Task 2: Commands

**Files:**
- `games/commands/historical_playtime.py` — `created_event(runs, device,
  statement, *, reclassified_from=None)`; `_refuse_beside_a_live_session`
  reads `record.reclassified_from` (skip when null) and adds the sibling
  guard: another live record of this library with the same
  `reclassified_from` → new sentence `ANOTHER_RECORD_LIVE`.
- `games/commands/playersession.py` — `_refuse_beside_a_live_record(context,
  session)` becomes a scoped query on `HistoricalPlaytime`.
- `games/commands/session_reclassification.py` —
  - `ReclassifySessionAsHistoricalPlaytime.build` refuses while a live record
    from the session exists (`RECORD_STILL_LIVE` reused), passes
    `reclassified_from=session.pk`.
  - `UndoSessionReclassification.build` in spec order: no record ever →
    `NEVER_RECLASSIFIED`; none live and session live → `Unchanged`; live
    record `restated_at` set → `RESTATED_SINCE` (new sentence, names the
    remedy: remove the record yourself); removed parent →
    `_refuse_under_a_removed_parent` from `playersession`; then each event
    still to happen.
  - Fix the device comment: the rehearsal counted no row naming a removed
    device; the reason is the rule, not the count.
- `games/writes/playersession.py` — `undo_reclassification` returns
  `CommandResult`.

**Tests (`tests/test_session_reclassification.py`):**
- Every `reclassified_into` assertion → `record.reclassified_from_id`.
- Restated then undo → refused whole: session still removed, record still live.
- Restated, removed by hand, then undo → session returns.
- Converted, undone, converted again → restoring the first record refused
  with `ANOTHER_RECORD_LIVE`; restoring the second refused while the
  session... (session is removed here) → admitted only after the second is
  removed.
- Undo under a removed run → refused; marks unchanged.
- Undo on a session never reclassified → `NEVER_RECLASSIFIED` (kept).
- `test_a_session_holding_a_removed_device_still_converts` docstring: drop
  "91 of 93".

## Task 3: Routes

**Files:**
- `games/views/removal.py` —
  - `restore_and_return(..., unchanged: str | None = None)`: when `action()`
    answers a `CommandResult` whose outcome is `UNCHANGED` and `unchanged`
    is given, `messages.info(unchanged)` instead of `restored`.
  - `confirm_and_apply`: a `CommandFailed` at `DEFECT_STATUS` renders the
    confirmation with `confirm=False`.
- `common/components/primitives.py` — `ConfirmPage(confirm: bool = True)`;
  `False` renders no submit button, cancel link only.
- `games/views/session_reclassification.py` —
  - `_posted_keys(request) -> list[UUID]`: parses; an unparseable value is
    logged and counted as not recorded.
  - `_classified(library, keys) -> Classified`: `NamedTuple(convertible:
    list[PlayerSession], refused: list[tuple[UUID, str]])` with sentences
    `NOT_AVAILABLE` (other library, removed, unparseable), `NOT_WRITTEN`
    (live, not Duration-only), `UNDER_THRESHOLD` (live, written, short).
  - `_convert_each`: denominator is the number of posted keys; every
    unconverted key logged with key, library and correlation id; a
    `CommandFailed` whose status is not `CONFLICT_STATUS` re-raises as
    `CommandFailed(f"{recorded} of {posted} … before a problem on our side
    stopped the request …", DEFECT_STATUS)`.
  - `undo_reclassify_session` passes `unchanged="That session was already
    back."`.
  - `PlaytimeReviewPanel` copy: "Nothing is thrown away. Moving one session
    offers an Undo; moving all of them at once does not yet."

**Tests (`tests/test_session_reclassification_views.py`):**
- FK assertions moved to the record.
- A posted 7-hour written-down row → `UNDER_THRESHOLD`, untouched.
- An unparseable key → `NOT_AVAILABLE`, "0 of 1".
- One row removed between GET and POST → "1 of 2".
- A defect on the second row (monkeypatch `state_reclassification` to raise
  `CommandFailed(..., DEFECT_STATUS)`) → status 500, first row recorded,
  third untouched, page holds no submit button.
- Undo route pressed twice → second answer is the `unchanged` message, not
  "Session restored."
- Library copy no longer holds "every change offers an Undo".
- `e2e/test_session_reclassification_e2e.py` FK assertion.

## Task 4: Form

**Files:**
- `games/forms.py` — `playthroughs.required = True`; `statement()` takes the
  held duration from `record.duration` or `session.effective_duration`.

**Tests (`tests/test_historical_playtime_form.py`):**
- Empty playthroughs is a field error naming the field, on Add and on a
  bucket-seeded session alike.
- A session of 9h 0m 30s posted unchanged as `9`/`0` states 9h 0m 30s.

## Task 5: Dates

**Files:**
- `common/criteria.py` — `for_dates` lists its members explicitly, without
  the two; `DateCriterion.to_q`, `temporal_interval_handler`,
  `days_touched_handler` drop the two branches.
- `make ts` regenerates `ts/generated/filter-metadata.ts`.

**Tests:**
- `tests/test_filters.py` — `test_for_dates_offers_both` →
  `..._offers_neither`; `test_date_criterion`, `test_temporal_endpoint`,
  `test_days_touched` assert `FilterError`; docstring "all six bodies" →
  the four number bodies.
- `grep` `ts/elements/filter-tree/summary-modifiers.canonical.json`,
  `summary.test.ts`, `field-comparison-set.test.ts` for a date leaf using
  either member; field comparisons keep both.

## Task 6: Docs

**Files:**
- `docs/event-retention.md:215-221` — rewrite: an act that includes a removal
  states the mark and no second mark; its reference lives on the row the act
  created, because a row can be the source of more than one act.
- `docs/superpowers/specs/2026-09-17-issue-705-historical-playtime-aggregate-design.md`
  — line 28 (created carries one optional key more), line 76 (columns),
  line 84 (five keys), the Restore refusals (session live, sibling live).
- `docs/superpowers/specs/2026-09-17-historical-playtime-wave-design.md:146-149`
  — the column is the record's.
- `CLAUDE.md` — one sentence under HistoricalPlaytime and one under
  PlayerSession's #694 paragraph naming the act and the two guards.
- `Makefile:425` — "a separator" → "`/`".
- `make vale`.

## Task 7: Rehearsal and review

- `make restore-dump` + count `reviewable_sessions` and rows naming a
  removed device on the deployment's data; record the numbers in the PR body,
  not in code.
- Five `pr-review-toolkit` reviewers; act on findings.
- Sweep the spec back to 200–500 words; delete this plan.
- `make check` on the user's word.
