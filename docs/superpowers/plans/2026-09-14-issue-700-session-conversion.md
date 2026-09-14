# Legacy Session conversion (#700) — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** State every legacy `Session` row as `PlayerSession` events, each
naming a run, with the imported-history bucket minted where a game needs one,
gated so a differing row rolls the migration back.

**Architecture:** A revived `games/backfill/` package (the #684 shape) walks
one library's tracked games, builds a `TimingStatement` per legacy row through
the census's `classify_timing` and the command module's shared payload
functions, appends through `append_one` under `backfill:700:…` keys with the
row's own instants, and reconciles against the census, the playtime parity
reads, the identity audit and a replay check. Migration `0004` runs it.

**Tech Stack:** Django 6 migrations (`RunPython`), the event store
(`games/events/`), pytest with `transaction=True`.

**Spec:** `docs/superpowers/specs/2026-09-14-issue-700-session-conversion-design.md`

## Global constraints

- Python 3.14, `make` targets only; the gate is full `make check`.
- This branch is **member 1 of the wave stack** (#700 → #1047 → #702 → #704).
  Open it with `gh stack init` + `gh stack submit`. Never `gh pr merge` it.
- Aggregate id of a converted session is the legacy `Session.id`;
  `recorded_at` is the row's `created_at` (removal: `removed_at`); the bucket
  is minted at the migration's instant.
- `day_zone` is `resolve_str_for_user(library.user, "DISPLAY_TIME_ZONE")`.
- Refused words: `make vale` runs over docs and comments. `delete` next to a
  record noun is refused; a script *destroys*, a user *removes*.
- Comments explain intent only; no issue numbers except forward TODOs.
- Name compound types; full-word identifiers.

---

## Task 0: Rebase and open the stack

- [ ] `git fetch origin && git rebase origin/main`.
- [ ] `gh stack init` on this branch (base `main`). `gh stack view` shows one
      member.
- [ ] Commit nothing yet.

## Task 1: Revive the backfill package and publish the shared checks

**Files:**
- Create: `games/backfill/__init__.py` (empty), `games/backfill/appending.py`,
  `games/backfill/mismatch.py` — byte-for-byte from `git show
  9fa80537^:games/backfill/<name>`.
- Modify: `games/commands/playersession.py` — rename `_normalized_timing` →
  `normalized_timing`, `_timing_payload` → `timing_payload`, `_check_note` →
  `check_note`; update every caller (`grep -rn "_normalized_timing\|_timing_payload\|_check_note" games tests`).

**Produces:**
- `append_one(library, event, *, actor, idempotency_key, command_input, recorded_at, correlation_id, source_metadata) -> bool`
- `Mismatch[CodeT: StrEnum](code, subject, detail)` with `.as_dict()`
- `normalized_timing(TimingStatement) -> TimingStatement` (aware-check, zone spelling)
- `timing_payload(TimingStatement) -> TimingPayload` (every value refusal, as `CommandRejected`)
- `check_note(str) -> None`

Steps:
- [ ] `git show 9fa80537^:games/backfill/appending.py > games/backfill/appending.py`, same for `mismatch.py`; touch `__init__.py`.
- [ ] Rename the three functions and their references. Docstrings unchanged.
- [ ] `make check-fast` green. Commit `refactor: publish the session payload checks the conversion shares`.

Gotcha: `tests/test_command_scope_guard.py` walks `games/commands/`; the
rename adds no manager `.get()`, so it stays green. `games/backfill/` is not
under `games/commands/`, so the guard does not walk it — the walk's reads must
still state `library=` themselves.

## Task 2: One row, one statement

**Files:**
- Create: `games/backfill/playersession.py`
- Test: `tests/test_playersession_conversion.py`

**Consumes:** Task 1; `classify_timing`, `TimingVerdict`, `MODE_VERDICTS`
(`games/preflight/session.py`); `TimedTiming`, `DurationOnlyTiming`,
`CorrectedTiming` (`games/commands/playersession.py`); `playersession_created`,
`playersession_removed` (`games/events/playersession.py`);
`capture_reference` (`games/events/references.py`); `identity_at`,
`SourceMetadata` (`games/events/append.py`).

**Produces:**

```python
PLAYERSESSION_ISSUE = 700
KEY_PREFIX = "backfill:700"
BUCKET_NAME = "Imported history — needs sorting"

class ConversionRefused(Exception): ...   # message names the row and the reason

@dataclass(frozen=True, slots=True)
class ConversionCounts:                  # summable, as_dict(); fields:
    libraries, tracked, rows_total, rows_unreached, live_rows,
    rows_removed_converted, timed, duration_only, corrected,
    running_removed, notes, devices, sole_run, contained, bucket,
    buckets_minted, events_appended

class LegacyRow(NamedTuple):             # every Session column the pass reads
    ...                                  # named like _PLAYEVENT_FIELDS was, for the migration's sake

def display_zone_name(library: UserLibrary) -> ZoneName
def statement_for(row: Session, *, day_zone: ZoneName) -> TimingStatement
    # timed → TimedTiming(start, day_zone, start_zone, end, end_zone)
    # duration_only → DurationOnlyTiming(start.astimezone(day_zone).date(), duration_manual)
    # corrected → CorrectedTiming(start, end, duration_total, day_zone, zones)
    # running and removed → TimedTiming(start, day_zone, start_zone)  (no end)
    # running and live, negative_*, duration_manual is None → ConversionRefused
def legacy_evidence(row: Session, *, verdict: TimingVerdict, assignment: Assignment) -> SourceMetadata
def convert_row(row: Session, *, library, actor, run_id: uuid.UUID, assignment: Assignment, day_zone: ZoneName) -> ConversionCounts
    # keys f"{KEY_PREFIX}:playersession:created:{row.pk}", ":removed:"
    # command_input = {"session": row.pk, "playthrough": run_id}
    # device: capture_reference(row.device) as recorded; another library's device → ConversionRefused
    # note: row.note.strip(), then check_note
    # one correlation_id per row, shared by created and removed
```

Zone columns: `None if not value else value` — `""` never reaches a payload.

Tests to write, each a `def test_…` over `Session.objects.create` rows under a
tracked game with one live ordinary run (`tests/session_rows.py::tracked_run`
gives it):
- `a_timed_row_converts_to_a_timed_row` (instants, zones, `day_zone`, `effective_duration == duration_total`)
- `a_duration_only_row_states_the_day_in_the_display_zone` (start 23:30 UTC on a Prague library lands the next day; `day_zone` is NULL on the projection row; `effective_duration == duration_total`)
- `a_corrected_row_states_the_legacy_total_not_the_manual_part`
- `a_removed_running_row_converts_as_a_timed_row_with_no_end_and_a_mark`
- `a_live_running_row_refuses`
- `a_negative_interval_refuses`, `a_negative_manual_duration_refuses`, `a_null_manual_duration_refuses`
- `an_end_zone_without_a_start_zone_is_kept_as_recorded`
- `a_blank_zone_becomes_none`
- `a_removed_device_converts_as_named`, `another_librarys_device_refuses`
- `a_padded_note_is_stripped`, `a_note_holding_a_nul_byte_refuses`
- `the_identity_is_the_legacy_id_and_created_at_is_the_rows`
- `a_removed_row_appends_created_then_removed_at_its_removed_at`
- `the_evidence_names_every_legacy_column` (compare `LibraryEvent.source_metadata`)
- `a_second_pass_over_one_row_appends_nothing`
- `counts_add_field_by_field`, `every_mode_verdict_names_a_counts_field`

TDD: write each test, run `make test ARGS="tests/test_playersession_conversion.py -k <name> -x"`, implement, rerun. Commit after every three or four green tests: `feat: state one legacy session as its events`.

## Task 3: Assignment, the bucket, the walk

**Files:**
- Modify: `games/backfill/playersession.py`
- Test: `tests/test_playersession_conversion.py`

**Consumes:** `assign_run`, `RunInterval`, `Assignment`, `AssignmentOutcome`
(`games/preflight/session.py`); `playthrough_created`,
`playthrough_name_changed` (`games/events/playthrough.py`); `keyset_pages`
(`common/keyset.py`).

**Produces:**

```python
def runs_for(tracked_id, *, library) -> list[RunInterval]
    # live ordinary runs, library on the run and on player_game, order created_at, id;
    # bounds from started_lower / completed_upper
def bucket_for(tracked: PlayerGame, *, library, actor, minted_at: datetime) -> uuid.UUID
    # existing imported_history run of this game, else mint:
    #   playthrough_created(tracked.pk, kind="imported_history", playthrough_id=identity_at(minted_at))
    #   playthrough_name_changed(run_id, name=BUCKET_NAME)
    # keys f"{KEY_PREFIX}:playthrough:bucket:{tracked.pk}", ":bucket_name:"
    # command_input = {"player_game": tracked.pk}; recorded_at=minted_at; one correlation id
def convert_game(rows: Sequence[Session], *, library, actor, tracked: PlayerGame, day_zone, minted_at) -> ConversionCounts
def rows_the_walk_reaches(library) -> QuerySet[Session]   # every row on a game the library owns
def convert_library(library: UserLibrary, *, minted_at: datetime | None = None) -> ConversionCounts
    # pages live PlayerGame rows 200 at a time; a row whose game has no live PlayerGame,
    # whose catalog game is removed, or whose game is shared → ConversionRefused naming the category
```

The day for `assign_run` is `row.timestamp_start.astimezone(ZoneInfo(day_zone)).date()`.
`bucket_for` runs lazily: minted on the first `BUCKET` row, so a game with no
such row gets no bucket. A second pass finds the existing run by
`kind=imported_history` before it mints.

Tests:
- `a_sole_run_takes_every_row_whatever_the_day`
- `one_dated_claimer_takes_the_row`
- `a_row_no_dated_run_claims_lands_in_the_bucket`
- `two_dated_claimers_land_the_row_in_the_bucket` (synthetic overlap — the branch production never exercises)
- `an_undated_run_claims_nothing`
- `one_bucket_per_game_however_many_rows_reach_it`, `the_bucket_is_named_and_of_the_imported_kind`
- `a_game_needing_no_bucket_gets_none`
- `a_second_pass_mints_no_second_bucket`
- `a_row_on_an_untracked_game_refuses`, `…on_a_removed_tracking_row_refuses`, `…on_a_removed_catalog_game_refuses`, `…on_a_shared_game_refuses`
- `a_second_pass_over_a_library_appends_nothing`
- `rows_unreached_counts_what_the_walk_left` (monkeypatch the walk to skip one)
- `unreachable_kinds_stay_a_commands_claim` — `tests/test_playergame_playthrough_gate.py` needs no change; assert here that `convert_library` is what states the kind.

Commit: `feat: name a run for every legacy session, and mint the bucket`.

## Task 4: The gate

**Files:**
- Modify: `games/backfill/playersession.py`
- Test: `tests/test_playersession_conversion.py`

**Consumes:** `preflight_library`, `PreflightCounts` (`games/preflight/session.py`);
`playtime_figures`, `differing` (`games/reads/playtime_parity.py`);
`identity_models`, `check_ordering` (`games/identity_audit.py`);
`rebuild_projections`, `RebuildMode` (`games/events/rebuild.py`).

**Produces:**

```python
class MismatchCode(StrEnum):
    ROW_DISAGREEMENT, REMOVED_ROW_DISAGREEMENT, CENSUS_DRIFT, ROWS_UNREACHED,
    BUCKET_SURPLUS, BUCKET_MEMBERSHIP, PLAYTIME_DIFFERS, COUNT_DRIFT,
    IDENTITY_ORDERING, IDENTITY_AUDIT_BLIND, REPLAY_DIFFERS

class RowShape(NamedTuple):   # what a legacy row and its projection row must both say
    mode, started_at, started_at_zone, ended_at, ended_at_zone, stated_day,
    effective_duration, device_id, note, emulated, removed

def reconcile(library: UserLibrary, counts: ConversionCounts) -> list[Mismatch[MismatchCode]]
    # 1 row-to-row per session id (live and removed populations separately)
    # 2 counts vs preflight_library(library) read in the display zone:
    #     timed, duration_only, corrected, running(removed) ; sole_run, contained_secondary, bucket_secondary
    #     and rows_unreached == 0
    # 3 buckets: ≤1 imported_history run per game; its sessions == the BUCKET rows; none where no BUCKET row
    # 4 differing(playtime_figures(library, ZoneInfo(day_zone))) == []
    # 5 live/removed session counts, legacy vs projection
    # 7 rebuild_projections(library, mode=RebuildMode.CHECK): every TableDiff shows no difference
def ordering_violations() -> list[Mismatch[MismatchCode]]   # check 6, games_playersession, blind → mismatch
```

Gotchas: `_one_snapshot()` yields straight through inside an atomic block, so
check 4 runs in the migration's transaction. Check 7 replays into shadow
tables inside the same transaction; read `RebuildReport.tables` for a diff,
never `swapped`. Check 2 reads the **secondary** column of `PreflightCounts`,
which `report_zones` fills from `activity_clock(library).zone` — the same
setting `display_zone_name` reads; assert that in a test rather than assume it.

Tests, one per code, each seeding a clean conversion then breaking one thing
(an `UPDATE` on the projection row, a hand-written extra bucket, a monkeypatched
census) and asserting the code and subject:
- `a_converted_library_reconciles_clean`
- `a_row_disagreement_is_reported`, `a_removed_row_without_a_mark_is_reported`
- `a_census_disagreement_is_reported`, `a_row_the_walk_never_saw_is_reported`
- `a_second_bucket_is_reported`, `a_bucket_holding_a_contained_row_is_reported`
- `a_playtime_difference_is_reported`
- `a_count_difference_is_reported`
- `an_identity_out_of_order_is_reported`, `a_blind_identity_audit_is_reported`
- `a_replay_difference_is_reported`
- `the_display_zone_the_census_reads_is_the_one_the_conversion_seeds`

Commit: `feat: gate the session conversion on seven readings`.

## Task 5: The migration and the sample loader

**Files:**
- Create: `games/migrations/0004_playersession_conversion.py`
- Modify: `games/management/commands/load_sample_data.py` (after the
  `rebuild_projections(...)` block, before `backfill_wikidata_references`)
- Test: `tests/test_playersession_conversion.py` (migration section),
  `tests/test_anonymize_sample.py` unchanged, `tests/test_load_sample_data*.py` if one exists (`ls tests | grep sample`).

Migration: the `0045` shape — `MACHINE_PREFIX = "PLAYERSESSION_CONVERSION_RECONCILIATION_JSON="`,
`SUMMARY_KEYS` = `ConversionCounts` fields + `mismatches`, `_emit`,
`_fail_if_mismatched`, `convert_legacy_sessions(apps, schema_editor)` importing
`games.backfill.playersession` and `UserLibrary` inside the function, one
`minted_at = timezone.now()` for the run, a second pass per library counted as
`COUNT_DRIFT` if it appended, `reconcile` then `ordering_violations`, emit on
`except Exception` with `"aborted": 1`, `RunPython(convert_legacy_sessions, RunPython.noop, elidable=True)`,
`dependencies = [("games", "0003_remove_game_playtime")]`.

Sample loader:

```python
from games.backfill.playersession import ConversionRefused, convert_library, ordering_violations, reconcile
...
try:
    converted = convert_library(user.library)
except ConversionRefused as refusal:
    raise CommandError(f"Sample sessions could not be converted: {refusal}") from refusal
mismatches = [*reconcile(user.library, converted), *ordering_violations()]
if mismatches:
    raise CommandError("Sample sessions did not reconcile: " + "; ".join(...first three...))
```

and the success line gains `f"{converted.live_rows + converted.rows_removed_converted} session(s) converted"`.

Tests:
- `the_migration_converts_and_reports` (machine line off stderr, `mismatches == []`)
- `the_migration_raises_on_a_mismatch`, `the_migration_names_the_mismatch_it_raises_on`, `a_mismatch_leaves_the_conversion_rolled_back`
- `a_refused_row_aborts_and_still_emits`
- `load_sample_data_converts_the_fixture` — `call_command("load_sample_data", ...)` then `PlayerSession.objects.count() == Session.objects.count()`; skip if the fixture load already has a test that runs it, and extend that one instead.

Then: `make preflight-sessions ARGS="--all-libraries"` against a restored dump
(`make restore-dump`, `DATABASE_URL=<printed>`), then
`make migrate DATABASE_URL=<printed>` and read the machine line: expect
`timed=2663 duration_only=142 corrected=0 running_removed=2 sole_run=2743
contained=61 bucket=1 buckets_minted=1 mismatches=0` (Europe/Prague). Record
the line in the PR body.

Commit: `feat: convert every legacy session in migration 0004`.

## Task 6: Documents, issues, the stack

- [ ] CLAUDE.md, PlayerSession bullet: one sentence — the conversion is
      `games/backfill/playersession.py`, run by `0004`, gated on seven
      readings, member 1 of the wave stack.
- [ ] Wave spec `2026-09-12-session-wave-design.md`, "#700" section: a
      **Delivered.** paragraph naming the design and the four decisions later
      issues inherit (running rule, per-game bucket, no-run refusal, stack).
- [ ] `make vale`, `make check` (full, with e2e).
- [ ] Issue comments (`gh issue comment`):
  - #772: replace `0004`'s callable with `RunPython.noop`; take `games/backfill/` out with the table.
  - #601: the stack is #700 → #1047 → #702 → #704; "harmless on main" rests on the quadlet holding no `AutoUpdate`.
  - #702: the bucket exists at ≤1 game; `MoveSessionToPlaythrough` is the only way out; every bucketed session is a `BUCKET` outcome the evidence names.
  - #1047: the conversion seeds `day_zone` from the display zone per #689; its counts were read in Europe/Prague.
- [ ] `gh stack submit` — PR body: the spec link, the dump's machine line, and
      "member 1 of the wave stack; do not merge alone".
- [ ] Kaneo TIM-8: comment with spec + plan + PR links, status → in progress.

## Self-review

Spec coverage: delivery (T0, T5, T6), module (T1, T2), one row (T2), assignment
and bucket (T3), keys (T2, T3), gate (T4, T5), verification list (T2–T5
tests), recorded elsewhere (T6). Placeholders: none — every function is named
with its signature, every test by name. Types: `ConversionCounts`,
`Mismatch[MismatchCode]`, `Assignment`, `TimingStatement`, `ZoneName` are used
with one spelling throughout.
