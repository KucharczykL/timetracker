# Session preflight census implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A read-only management command that counts, per library, what the
legacy `Session` rows hold — timing verdict, run assignment, the rows no mode
converts, and the day-zone delta — so #689 and #700 decide against measured
data instead of assumptions.

**Architecture:** One pure module `games/preflight/session.py` holding the
classifiers and the walk, one thin command printing them, one Make target. No
model, no migration, no event. #700 later imports `classify_timing` and
`assign_run` from this module, so their signatures are the deliverable, not
the report text.

**Tech Stack:** Django 6, Python 3.14, PostgreSQL 18, pytest + pytest-django.

**Spec:** [docs/superpowers/specs/2026-09-12-issue-699-session-preflight-design.md](../specs/2026-09-12-issue-699-session-preflight-design.md)

## Global constraints

- Python 3.14 only; `except A, B:` bare form is correct (PEP 758).
- Run everything through `make`. Never `uv run pytest` directly, never wrap in
  `direnv exec .`. Focused runs: `make test ARGS="tests/test_session_preflight.py -k timing -x"`.
- The gate before the PR is a full `make check`, e2e included. `make check-fast`
  is for iterating only.
- No `QuerySet.iterator()` / `aiterator()` anywhere — `tests/test_iterator_guard.py`
  walks `games/` and fails on one. Page with `keyset_pages` from `common/keyset.py`.
- Unabbreviated identifiers (`element` not `el`, `session` not `s`).
- Name compound types: `TypedDict`/`NamedTuple`/`type` alias rather than a
  repeated structural annotation.
- Comments explain intent only; no issue or PR references in comments except
  forward `TODO`s. Docstrings follow the terse house style — see the deleted
  sibling, `git show 5442d168^:games/preflight/playthrough.py`.
- `make vale` is part of `make check`: `fold`, `seam`, `heal`, `delete` are
  refused in prose and comments. A projector *replays*; the row is a
  *projection*.
- Rebase onto `origin/main` before the first edit.

## Reference material

- The deleted sibling this follows, recoverable and worth reading first:
  `git show 5442d168^:games/preflight/playthrough.py`,
  `git show 5442d168^:games/management/commands/preflight_playthroughs.py`,
  `git show 5442d168^:tests/test_playthrough_preflight.py`.
- The write-statement parser to reuse: `games/events/rebuild.py:82-125`
  (`write_targets`, `only_shadow_writes`).
- Run reads: `live_ordinary_runs` in `games/reads/playthrough_runs.py:44`.
- Zone resolution: `resolve_str_for_user` in `timetracker/settings_resolver.py:290`,
  reached as `activity_clock(library).zone` in `games/reads/playthrough_activity.py:34`.

## File structure

| File | Responsibility |
|---|---|
| `games/preflight/__init__.py` | new package, empty |
| `games/preflight/session.py` | verdict enum, `classify_timing`, `assign_run`, counts, samples, the per-library walk, shared-catalog counts |
| `games/management/commands/preflight_sessions.py` | scope resolution, JSON line, readable sections |
| `tests/test_session_preflight.py` | unit tests for the pure functions, database tests for the walk, the write proof |
| `Makefile` | `preflight-sessions` target, after `audit-uuid-identity` |
| `CLAUDE.md` | one row in the commands table |

The walk stays in `session.py` beside the classifiers because #700 imports the
classifiers and the report is their only current caller; splitting the walk out
would give two files with one caller each.

---

### Task 0: Land the documents

The spec and the wave-design amendment were written before this plan and are
already in the working tree. They travel with the first commit so the branch
never carries code arguing from a document `main` does not have.

**Files:**
- `docs/superpowers/specs/2026-09-12-issue-699-session-preflight-design.md` (new)
- `docs/superpowers/specs/2026-09-12-session-wave-design.md` (amended: the zone
  premise, the removed gate, the zone-labelled figures)
- `docs/superpowers/plans/2026-09-12-issue-699-session-preflight.md` (this plan)

- [ ] **Step 1: Rebase onto `origin/main`** and branch.
- [ ] **Step 2: Run `make vale`.** Expected: no findings.
- [ ] **Step 3: Commit.** `docs: state what the legacy session census reports`

---

### Task 1: The timing taxonomy

**Files:**
- Create: `games/preflight/__init__.py`, `games/preflight/session.py`
- Test: `tests/test_session_preflight.py`

**Interfaces:**
- Produces: `class TimingVerdict(StrEnum)` with members `NEGATIVE_ELAPSED`,
  `NEGATIVE_MANUAL`, `TIMED`, `DURATION_ONLY`, `CORRECTED`, `RUNNING`
  (values are the lowercase names); `classify_timing(session: Session) -> TimingVerdict`.

The order of tests inside `classify_timing` is the specification, not an
implementation detail: negative elapsed, then negative manual, then the four
shapes. A row that is both reversed and negative is named by the first.

- [ ] **Step 1: Write the failing tests.** No database needed — build
  `Session(...)` unsaved instances. Cases, one test each:
  - end after start, `duration_manual=timedelta(0)` → `TIMED`
  - end equal to start, zero manual → `TIMED` (a zero interval is a duration)
  - no end, `duration_manual=timedelta(hours=2)` → `DURATION_ONLY`
  - end after start, `duration_manual=timedelta(hours=2)` → `CORRECTED`
  - no end, zero manual → `RUNNING`
  - end before start → `NEGATIVE_ELAPSED`
  - end before start **and** `duration_manual=timedelta(hours=2)` →
    `NEGATIVE_ELAPSED` (order proof)
  - no end, `duration_manual=timedelta(hours=-1)` → `NEGATIVE_MANUAL`
  - end after start, negative manual → `NEGATIVE_MANUAL` (order proof)
  - `duration_manual=None`, no end → `RUNNING` (NULL reads as zero, never raises)
  - `duration_manual=None`, end set → `TIMED`
- [ ] **Step 2: Run and watch them fail.** `make test ARGS="tests/test_session_preflight.py -x"`.
  Expected: import error, then failures.
- [ ] **Step 3: Implement the enum and `classify_timing`.** Read
  `duration_manual` through a local `manual = session.duration_manual or timedelta(0)`
  — that is the NULL rule and the one place it lives.
- [ ] **Step 4: Run them green.** Same command.
- [ ] **Step 5: Commit.** `feat: classify a legacy session's timing`

---

### Task 2: The counts and samples containers

**Files:**
- Modify: `games/preflight/session.py`
- Test: `tests/test_session_preflight.py`

**Interfaces:**
- Produces: `@dataclass(frozen=True, slots=True) class PreflightCounts` with
  `__add__` and `as_dict`; `NO_COUNTS = PreflightCounts()`;
  `@dataclass(frozen=True, slots=True) class Samples` with `as_dict`.

Field list — every one an `int`, defaulting to `0`:

- scope: `sessions_in_scope`, `classified`, `removed`, `unaccounted`
- verdicts: one per `TimingVerdict` member, named by its value
- observations: `manual_duration_null`, `committed_zone_stated`
- ladder: `on_removed_game`, `without_player_game`, `on_removed_player_game`
- assignment, per zone, so the two never blend:
  `sole_run`, then `contained_primary`, `bucket_primary`, `many_claimers_primary`,
  `contained_secondary`, `bucket_secondary`, `many_claimers_secondary`
- games: `games_owned`, `games_without_sessions`, `games_needing_bucket_primary`,
  `games_needing_bucket_secondary`
- zone delta: `day_differs`, `month_differs`, `year_differs`

`primary` is the zone the report reads first (`settings.TIME_ZONE`) and
`secondary` the library's display zone; the payload names both, so the field
names stay stable when the two swap.

`Samples` holds `tuple[uuid.UUID, ...]` fields `negative_elapsed`,
`negative_manual`, `running`, `bucket_primary`, `many_claimers_primary`,
`games_needing_bucket_primary`, and `as_dict` renders them as `list[str]`.

- [ ] **Step 1: Write the failing tests.** `test_counts_sum_field_by_field`
  (add two populated instances, assert every field summed),
  `test_the_empty_counts_are_an_identity`, `test_counts_render_every_field`
  (`set(as_dict()) == {field.name for field in fields(PreflightCounts)}`),
  `test_samples_render_as_strings`.
- [ ] **Step 2: Run and watch them fail.**
- [ ] **Step 3: Implement both dataclasses.** `__add__` builds the new instance
  from `fields(self)` so a new field never needs a second edit.
- [ ] **Step 4: Run them green.**
- [ ] **Step 5: Commit.** `feat: hold what one library's sessions count to`

---

### Task 3: The assignment rule

**Files:**
- Modify: `games/preflight/session.py`
- Test: `tests/test_session_preflight.py`

**Interfaces:**
- Produces:
  - `class RunInterval(NamedTuple)`: `run_id: uuid.UUID`,
    `started_lower: date | None`, `completed_upper: date | None`
  - `def claims(interval: RunInterval, day: date) -> bool`
  - `class AssignmentOutcome(StrEnum)`: `SOLE_RUN`, `CONTAINED`, `BUCKET`
  - `class Assignment(NamedTuple)`: `outcome: AssignmentOutcome`,
    `run_id: uuid.UUID | None`, `claimers: int`
  - `def assign_run(runs: Sequence[RunInterval], day: date) -> Assignment`

Pure over a sequence of intervals, so the walk owns the queries and the tests
own the data. `claimers` is what the report counts `many_claimers_*` from, and
is `0` for a sole run because containment was never consulted.

- [ ] **Step 1: Write the failing tests.**
  - one run, day far outside its interval → `SOLE_RUN`, that run, `claimers == 0`
  - one run with two NULL bounds → still `SOLE_RUN`
  - no runs at all → `BUCKET`, `run_id is None`
  - two dated runs, day inside exactly one → `CONTAINED`, that run, `claimers == 1`
  - two runs, day inside neither → `BUCKET`, `claimers == 0`
  - two runs, day inside both → `BUCKET`, `claimers == 2`
  - `claims` alone: start-only run claims the start day and every later day,
    refuses the day before; completion-only run claims the completion day and
    every earlier day, refuses the day after; a dated run claims both its
    endpoints and refuses one day outside each; a run with two NULL bounds
    claims nothing
- [ ] **Step 2: Run and watch them fail.**
- [ ] **Step 3: Implement.** `claims` returns `False` when both bounds are
  `None`, else compares the bounds that are set. `assign_run` short-circuits on
  `len(runs) == 1`.
- [ ] **Step 4: Run them green.**
- [ ] **Step 5: Commit.** `feat: choose the run a legacy session lands on`

---

### Task 4: The per-library walk

**Files:**
- Modify: `games/preflight/session.py`
- Test: `tests/test_session_preflight.py`

**Interfaces:**
- Produces:
  - `class ZonePair(NamedTuple)`: `primary: ZoneInfo`, `secondary: ZoneInfo`
  - `def report_zones(library: UserLibrary, override: ZoneInfo | None = None) -> ZonePair`
  - `@dataclass(frozen=True, slots=True) class LibraryPreflight`:
    `library_id`, `username`, `zones: tuple[str, str]`, `counts`, `samples`,
    plus `as_dict()`
  - `def preflight_library(library, *, sample_size: int = DEFAULT_SAMPLE_SIZE, day_zone: ZoneInfo | None = None) -> LibraryPreflight`
  - `WALK_PAGE_SIZE = 200`, `DEFAULT_SAMPLE_SIZE = 20`
  - `@dataclass(frozen=True, slots=True) class SharedCatalogCounts` +
    `def shared_catalog_counts() -> SharedCatalogCounts`

The walk, per batch of owned games:

1. `keyset_pages(Game.objects.filter(library=library), key=("id",), page_size=WALK_PAGE_SIZE)`,
   re-chunked with `itertools.batched`. `Game` has no manager method for this —
   write the filter in full, and do **not** call `.alive()`: a removed game's
   sessions are a reported category, not an exclusion.
2. one query for the batch's `Session` rows (`game_id__in=...`), no `.alive()`
   for the same reason;
3. one query for the batch's `PlayerGame` rows, which is what separates "no
   tracking row" from "removed tracking row" — a removed one holds no live run
   and is otherwise indistinguishable;
4. one query for the live ordinary runs under those `PlayerGame` rows, built
   from `live_ordinary_runs`' filter so the two never drift, read as
   `.values_list("id", "player_game_id", "started_lower", "completed_upper")`
   and grouped in Python into `RunInterval` lists.

Per session: the ladder first (removed game → no `PlayerGame` → removed
`PlayerGame`, each claiming the row and stopping), else classify, assign under
both zones, and add the zone-delta observations. `removed` counts the session's
own `removed_at`, beside the verdict rather than instead of it.

`report_zones` answers `ZoneInfo(settings.TIME_ZONE)` and
`activity_clock(library).zone`; `override` replaces the secondary.

`shared_catalog_counts` counts games with `library__isnull=True` and the
sessions on them — the only place a shared-game session is reported.

- [ ] **Step 1: Write the failing tests.** Use `owned_library` from
  `tests/conftest.py:50`. Build games with the existing helpers there rather
  than `Game.objects.create` where one fits; note the autouse
  `_track_created_games` (`tests/conftest.py:235`) already gives each created
  game a `PlayerGame` and a `Playthrough`, so a test wanting "no tracking row"
  must remove what the fixture made. Cases:
  - a game with no sessions raises `games_without_sessions`, nothing else
  - each verdict reaches its own count, and a removed session raises `removed`
    while still carrying its verdict
  - a session on a removed game counts `on_removed_game` and no verdict
  - a session on a game whose `PlayerGame` was destroyed counts
    `without_player_game`
  - a session on a removed `PlayerGame` counts `on_removed_player_game`
  - a game both removed and untracked counts once, in `on_removed_game`
  - `unaccounted` is zero across all of the above
  - a session whose game holds one run reaches `sole_run` under both zones
  - a session on a two-run game, contained under one zone and not the other,
    moves between `contained_primary` and `bucket_secondary` — build it at
    `23:30 UTC` against a run bounded on that UTC day, with the secondary zone
    forced to `Europe/Prague` through `day_zone`
  - the zone delta counts a day, a month and a year crossing (one session each
    at `23:30` on a day, a month end and 31 December)
  - `committed_zone_stated` counts a row carrying `timestamp_start_timezone`
  - one library never counts another's rows
  - a shared game (`library=None`) reaches no per-library count and is counted
    by `shared_catalog_counts`
  - samples cap at `sample_size`, and `sample_size=0` leaves them empty
  - **the walk writes nothing**: wrap only the `preflight_library(...)` call in
    `connection.execute_wrapper(...)` raising when `write_targets(sql)` from
    `games.events.rebuild` is non-empty. Wrapping the whole test fails on the
    fixtures' own inserts.
- [ ] **Step 2: Run and watch them fail.**
- [ ] **Step 3: Implement the walk.**
- [ ] **Step 4: Run them green**, then `make test ARGS="tests/test_session_preflight.py"`
  whole-file.
- [ ] **Step 5: Commit.** `feat: count what one library's legacy sessions hold`

---

### Task 5: The command

**Files:**
- Create: `games/management/commands/preflight_sessions.py`
- Modify: `Makefile`, `CLAUDE.md`
- Test: `tests/test_session_preflight.py`

**Interfaces:**
- Produces: `MACHINE_PREFIX = "SESSION_PREFLIGHT_JSON="`, `GENERATED_PREFIX = "Generated at "`.

Copy the scope resolution verbatim from
`git show 5442d168^:games/management/commands/preflight_playthroughs.py` —
`--user` / `--library` / `--all-libraries` mutually exclusive and required, four
distinct `CommandError` sentences, `--sample-size` refusing a negative. Add
`--day-zone`, refused with a `CommandError` naming the value when `ZoneInfo`
raises `ZoneInfoNotFoundError`.

Payload: `schema_version` 1, `generated_at`, `summary`, `libraries`,
`shared_catalog`. Each library entry carries its two zone names. JSON printed
first, `sort_keys=True, separators=(",", ":")`.

The readable sections mirror the spec's tables in order: scope, verdicts,
observations, ladder, assignment (both zones side by side), games, zone delta.
Print the unaccounted difference explicitly — it reads as zero and a reader
should see that it does.

Makefile target, beside `audit-uuid-identity`:

```make
# Read-only: reports what the legacy Session rows hold.
# Usage: make preflight-sessions ARGS="--user NAME"
preflight-sessions: ensure-postgres
	uv run --frozen python manage.py preflight_sessions $(ARGS)
```

`CLAUDE.md` commands table gains one row naming it as read-only, beside the
other audit rows.

- [ ] **Step 1: Write the failing tests.** `call_command` with `stdout=StringIO`:
  - a scope naming no library prints the "read nothing" line and exits zero
  - the JSON line parses and carries `schema_version`, both zone names, and the
    summary's fields
  - two runs print identical bytes but for the `generated_at` line
  - a row no mode can hold does **not** fail the run (exit zero, count printed)
  - `--user` with an unknown name, a user owning no library, `--library` with
    non-UUID text, and an unknown UUID each raise `CommandError` with their own
    sentence
  - `--sample-size -1` and an unknown `--day-zone` each raise `CommandError`
- [ ] **Step 2: Run and watch them fail.**
- [ ] **Step 3: Implement the command, the Make target and the CLAUDE.md row.**
- [ ] **Step 4: Run them green.**
- [ ] **Step 5: Commit.** `feat: print the legacy session preflight`

---

### Task 6: Verify against the production dump

**Files:** none — this task produces a comment on the PR, not a diff.

- [ ] **Step 1: Restore.** `make restore-dump`, which prints its `DATABASE_URL`.
- [ ] **Step 2: Run the command against it** with `--all-libraries`.
- [ ] **Step 3: Run the hand-written comparison** — the timing query in the
  spec, plus the assignment, ladder, shared-catalog and zone-delta queries built
  the same way — and check each category agrees with the printed report.
- [ ] **Step 4: Check against the expected figures.** `timed` 2,663/0,
  `duration_only` 142/0, `running` 0/2, nothing else; `sole_run` 2,743 live +
  2 removed; `contained`/`bucket` 60/2 in UTC and 61/1 in Europe/Prague; every
  ladder and shared-catalog count zero; zone delta 124 / 10 / 5. A difference
  is a finding, not a failure — the dump may have moved since 2026-09-12; report
  what differs and why.
- [ ] **Step 5: Record the output** in the PR body, and drop the scratch
  database.

---

### Task 7: The gate and the wave follow-through

- [ ] **Step 1: Run the full gate.** `make check`, e2e included. Green, or fix
  and repeat. Never a hand-picked subset.
- [ ] **Step 2: Open the PR** with the dump output from Task 6 in the body, and
  merge with `gh pr merge --merge` once green.
- [ ] **Step 3: Comment on #689** — its `day_zone` seeding rationale is void:
  every day-grained read groups in the viewer's zone today, and seeding from
  `TIME_ZONE` moves 124 sessions to another day, 10 to another month and 5 to
  another year. The choice is #689's; the census reports both. #689 also owns
  the test asserting `PlayerSessionTimingMode`'s three members are spelled as
  `TimingVerdict`'s first three.
- [ ] **Step 4: Comment on #704** — its strict-equality gate depends on that
  choice, and its assignment figures must name the zone they were measured in.
- [ ] **Step 5: Comment on #700** — it imports `classify_timing` and
  `assign_run` rather than restating them, refuses `NEGATIVE_ELAPSED`,
  `NEGATIVE_MANUAL` and `RUNNING`, and the bucket it mints covers a game with
  no live ordinary run, not only an ambiguous day.

---

## Gotchas

- **`duration_manual` is never NULL in practice but nullable in the schema.**
  Every rule tests `> timedelta(0)`. A presence test classifies all 2,805 live
  rows as `TIMED`, which is the whole trap this issue exists to name.
- **`make test-e2e ARGS=…` does not scope** — `ARGS` appends to `pytest e2e/`.
  And never run e2e while `make dev` is up; its watchers rewrite the served
  assets and cause mass phantom failures.
- **`PYTEST_WORKERS=0`** when debugging: parallel output interleaves and `-x`
  stops only the worker that hit it.
- **The autouse `_track_created_games` fixture** gives every created game a
  `PlayerGame` and a `Playthrough`. Tests of the ladder must undo that, and the
  write guard must wrap the census call rather than the test.
- **`TIME_ZONE` differs between shells**: `Europe/Prague` under `DEBUG`, `UTC`
  otherwise (`timetracker/settings.py:173`). The report prints the zones it
  read for exactly this reason; compare against the matching column.
- **The anonymized sample fixture answers `duration_only` 141 and `corrected` 1**
  where the dump answers 142 and 0. The fixture predates two rows the wave
  review corrected by hand. Do not "fix" it — it is the only `corrected`
  specimen in the tree.
- **Do not add an index for this command.** It is run by hand over 859 games.
