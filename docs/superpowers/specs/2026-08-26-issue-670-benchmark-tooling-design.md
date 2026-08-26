# Command, replay, and projector benchmark tooling

Issue [#670](https://github.com/KucharczykL/timetracker/issues/670), phase
[#601](https://github.com/KucharczykL/timetracker/issues/601). Architecture: the
[overhaul charter](https://github.com/KucharczykL/timetracker/blob/codex/player-history-architecture/docs/superpowers/specs/2026-08-09-timetracker-overhaul-design.md).

Dependency: `#671 -> #670`, satisfied. #671 merged as `a0165cea`. This
specification measures what #671 shipped, not a stand-in for it. An earlier
draft of this document built a synthetic workload; that draft was parked
precisely because a synthetic workload would have needed new placeholder command
names in production code, a projection table created by runtime DDL, and would
have understated both budgets by skipping the reference rows every append writes.
None of that survives here.

## What it is

One management command, `manage.py benchmark_events`, and the measurement module
behind it. It answers two of the three questions the charter fixes numbers for,
and records a third the charter demands be tracked and sets no limit on:

- does an ordinary synchronous command finish within **100 ms at p95**;
- does a complete library rebuild of **100,000 events finish within 60 seconds**;
- **how many rows** does one event write, per projector family.

The first two are gates. The third is reported and never gated: the charter says
to record write amplification after every new projector family, and fixes no
limit for it.

It also produces the parity evidence #601 asks of an event-sourced slice, because
the rebuild scenario diffs a replay against projections the real write path
produced at full scale.

## The workload is real

There is no workload protocol, no plug point, and no `--workload` flag. #671
shipped one command, one event type, and one projector family, and the harness
names them directly:

| Piece | What #671 shipped |
| --- | --- |
| Command | `games.commands.playergame.TrackGame(game_id=...)` |
| Event | `library.playergame.created`, one per command |
| Reference | one `catalog.game`, `Resolution.REQUIRED` |
| Family | `ProjectorFamily.CURRENT_STATE` via `games.projectors.playergame.PlayerGames` |
| Table | `games_playergame`, one row per event |

Two properties of that command shape the harness:

- **Every dispatch needs its own catalog row.** `TrackGame.build` refuses a
  second track of the same game with `CommandRejected`, and
  `unique_library_player_game` refuses it again at the database. So a measured
  loop of N dispatches needs N `Game` rows nothing has tracked yet.
- **The refusal check is a query against the projection.**
  `PlayerGame.objects.filter(library=..., game=...).exists()` runs inside every
  dispatch. Measuring it against a library that already holds 100,000 tracked
  games is the measurement worth having, and is one the parked synthetic draft
  could not have produced. The command scenario therefore runs *after* seeding,
  never against an empty library.

`events_per_command` is 1. It is not a parameter.

### There is no bulk scenario

The charter asks for "ordinary and representative bulk commands" against the
100 ms budget. #671 shipped no bulk command: `TrackGame` emits exactly one event,
and nothing in the application chunks a bulk operation under one correlation ID
yet. The harness therefore measures no bulk command, and says so in its output
rather than reporting a second copy of the ordinary latency under a bulk label.

What it does report in that place is **append throughput**, taken from seeding:
batches of 1,000 real events per locked transaction, which is the fastest the
write path can go and the closest thing to a bulk write that exists. It is
labelled an append measurement and carries no budget, because the 100 ms budget
is a claim about commands.

The scenario returns when a chunked bulk command ships. The charter already
requires a re-measurement after every new projector family, so that
re-measurement is the trigger; nothing extra needs tracking.

## Ownership boundary

| Not here | Owner |
| --- | --- |
| The 200 ms Journal page query budget and its read model | phase 14 (#601) |
| A chunked bulk command | the phase that needs one |
| Deleting the `TEST_COMMAND_*` allowlist members | #907 |
| A lever to disable server-side cursors under a pooler | #917 |
| Blocking direct writes to event-sourced projections | #737 |
| The shadow rebuild, the diff, and the swap | #667 |
| The bounded ordered fold | #666 |

This issue owns the measurement core, the three scenarios, the command that
prints them, the budget declarations, and the recorded results document.

**It adds no migration and no model.** It changes one line of existing code: a
private helper in #667's module becomes public, below.

## Preconditions

| Depends on | For |
| --- | --- |
| #664 `dispatch()` | the command-latency scenario |
| #666 `replay()` | folded through the rebuild |
| #667 `rebuild_projections()` and its per-phase timings | the rebuild scenario |
| #665 `ProjectorRegistry` and `EventWiring` | the projectors that seeding folds |
| #661 `lock_stream().append()` | batch seeding |
| #671 `TrackGame`, `PlayerGames`, `games_playergame` | everything measured |
| `games/retention.py` `purging_library()` | scratch teardown |

PostgreSQL is required, as everywhere else. A run against any other backend is
not a supported measurement and the command does not attempt one.

`RebuildAttempt` already carries `replay_seconds`, `diff_seconds`, and
`swap_seconds`, so the rebuild scenario adds no instrumentation inside #667.

## Design

### Three scenarios

| Scenario | What it calls | Budget |
| --- | --- | --- |
| `command` | `dispatch(TrackGame(...))`, N times, each with its own idempotency key, against the seeded library | 100 ms p95 |
| `rebuild` | `rebuild_projections(CHECK)` then `rebuild_projections(REBUILD)` | 60 s per 100,000 events |
| `amplification` | the `command` scenario again, under the row counter | recorded, never gated |

Seeding is timed and reported alongside them, and its time is never inside a
measured window.

`--library <uuid>` runs the `rebuild` scenario alone, in `CHECK` mode, against a
library that already exists. It seeds nothing, creates nothing, and writes
nothing. It is how a production copy gets measured, and now that real
projections exist its diff is genuine parity evidence rather than an empty
comparison of two empty tables.

### Seeding: the catalog first, then the stream

`--seed N` (default 100,000):

1. create a `User` named `benchmark-<uuid7>` and its `UserLibrary`;
2. `bulk_create` the catalog in batches of 1,000: `N + 2 * (iterations +
   warmup)` `Game` rows named `Benchmark game <index>`, owned by the scratch
   library, with no platform and no release year. The extra rows are the
   untracked ones the `command` and `amplification` scenarios each consume;
3. append `N` events in batches of 1,000, each batch one transaction taking
   `lock_stream()` once and calling `append()` with the whole batch. Each event
   is a real `PLAYERGAME_CREATED` whose payload carries `capture_reference(game)`
   for one of the first N catalog rows;
4. run the scenarios;
5. delete the scratch user, in a `finally`.

Batching step 3 is the difference between ~100 locked transactions and ~100,000
of them. It goes through `LockedStream.append`, not `dispatch`, which is
deliberate and has one consequence worth stating: the seeded events skip the
idempotency record and the duplicate check, but they pass through the same
validation, write the same `LibraryEventReference` rows, and are folded by the
same projectors in the same loop. `append()` applies the registry inline, so
seeding leaves live `games_playergame` rows that the write path produced. That
is what makes step 4's rebuild a parity proof rather than a timing exercise.

The catalog is separated from the stream in both the code and the report,
because it is setup rather than measurement. Its time is reported so a reader
can tell a slow seed from a slow write path.

`--seed` and `--library` are mutually exclusive; the command refuses both
together and names the argument that was wrong.

A scratch user is a real row in whatever database `DATABASE_URL` names. The
command prints what it is about to create, and how many rows, before creating it.

### Teardown

The scratch user is deleted through the existing
`manage.py delete_user_library --user <name> --confirm <name>`, which already
runs `user.delete()` inside `purging_library()` and is already tested. The
harness calls it with `call_command` in a `finally`.

At 100,000 events this collects roughly 400,000 rows through Django's ORM
collector: the events, their reference index rows, the catalog games, and the
projected `PlayerGame` rows. That is not free, and the harness does not pretend
it is: **the teardown is timed and printed like every other phase.** A second,
raw-SQL copy of the cascade would be faster and would be a second thing that can
drift from `on_delete` — the failure `docs/event-retention.md` argues against for
the archive path. If the measured teardown proves unacceptable, that is then a
recorded number to act on rather than a guess.

One cost is known in advance and stated rather than discovered:
`delete_user_library` walks the collector twice, once to print the deletion scope
and once to delete. The reported teardown time includes both.

`--keep` skips the teardown for debugging and prints the exact
`delete_user_library` invocation that cleans up after it.

### Timing and percentiles

Every sample is one `monotonic()` interval around one call. A run discards
`--warmup` samples (default 10) before recording, because the first dispatch of a
process pays for connection setup, query-plan caching, and Python imports that no
later one pays for.

The percentile is **nearest rank** on the sorted samples: index
`ceil(p / 100 * n) - 1`. Not `statistics.quantiles`, whose interpolation invents
a value between two observations; a latency budget is a claim about observations.

p50, p95, and max are reported. The mean is not: it hides the tail the budget is
about.

`--iterations` defaults to **200**. That is comfortably above the 20-sample
gating floor below, and at ~100 ms a sample it is a scenario measured in seconds
rather than minutes.

### The rebuild scenario is also a parity proof

The seeded library is filled through the real append path, so its live
`games_playergame` rows are what the write path produced. `rebuild_projections`
replays the same events into a shadow table and diffs it against those rows. A
run whose `TableDiff` reports zero `only_live`, zero `only_rebuilt`, and zero
`differing` is replay parity demonstrated at 100,000 events, which is the
evidence the issue's acceptance criteria asks for.

**A non-empty diff fails the run regardless of how fast it was.** A rebuild that
is quick and wrong is not a passing benchmark.

`CHECK` runs first and writes nothing, so its `replay_seconds` is the fold cost
without the swap. `REBUILD` then gives the full five-phase wall clock, which is
the number the 60-second budget is stated against.

The fold also exercises `require_resolvable_references`, which runs once before
the first row and does one anti-join per `REQUIRED` kind. With 100,000
`catalog.game` references that anti-join is part of what the budget is measuring,
and it is present here because the events are real.

### The budget is scaled, and refuses to be scaled too far

The charter fixes 60 seconds at 100,000 events. A smaller run is compared against
`60 s * events / 100_000`.

Below **10,000 events** the gate does not apply the rebuild budget at all, and
says so. Temp-table creation, the `FULL OUTER JOIN` diff, and the swap have a
fixed cost that dominates a small stream, so a scaled budget there measures
overhead rather than throughput. The measured time, the event count, and the
events-per-second are printed in every case; only the verdict is withheld.

The same rule guards the latency budget: fewer than **20** recorded samples
reports p95 without gating it.

A budget therefore has three outcomes, not two. `Budget.verdict` is
`PASSED`, `MISSED`, or `NOT_GATED`; there is no boolean `passed`, because a
boolean forces a run that was too small to judge into one of two answers it did
not earn.

### Write amplification, counted from the statements

A `connection.execute_wrapper` names the table each statement writes and adds
`context["cursor"].rowcount` to a per-table total. Rows are then classified by
whether the table belongs to `projection_models()`, to the event store, or to
neither.

Counting statements rather than diffing `COUNT(*)` before and after is what makes
an update or a delete visible: a family that rewrites one row per event has an
amplification of one, and a before/after count would report zero. #671's
projector uses `update_or_create`, so this distinction is load-bearing from the
first family measured.

**The statement parser is shared, not copied.** `games/events/rebuild.py` already
parses a statement's write targets for the shadow-write guard, in
`_write_targets`. That function becomes public as `write_targets` and the
harness imports it. Two regexes for one job would drift, and the shadow guard is
the one that must not be wrong. This is the only edit to existing code in this
issue: a rename and its call sites, no behaviour change.

Two limits, stated rather than hidden:

- the wrapper sees one connection, so a family that opens its own is not counted;
- under `executemany`, `rowcount` is the total across the batch, not per row,
  which is what the report wants anyway.

The report gives rows per event, rows per command, and the per-table breakdown.
For #671's single family the expected shape is one `games_playergame` row, one
`games_libraryevent` row, one `games_libraryeventreference` row, and one
`games_libraryeventstreamhead` update per event, plus the idempotency record
`dispatch` writes. Recording that shape is what makes a later family's regression
visible.

### A pooled connection fails here first

`replay()` opens the longest-lived server-side cursor the application has. Under
a transaction-pooling connection pooler the following `FETCH` fails, and
`DISABLE_SERVER_SIDE_CURSORS` cannot currently be set — that is #917. A benchmark
is the first thing likely to be pointed at a pooled production copy, so a cursor
error out of the fold is caught and re-raised with a message naming #917 and the
pooler, rather than reading as a replay bug.

### What is not measured

- **Concurrency.** Every scenario is one process issuing one command at a time.
  Lock contention on the stream head, the retry path under a real conflict, and
  throughput under parallel writers are all outside this harness. This is a
  stated limit rather than a gap to fill: the charter's two budgets are both
  single-command and single-rebuild claims, and a concurrency harness is a
  different tool with a different failure mode.
- **Any query path.** The charter's 200 ms Journal page budget has no read model
  to measure yet and belongs to phase 14.

## API contract

```python
# games/events/benchmark.py

type Seconds = float
type TableName = str

class BudgetVerdict(StrEnum):
    PASSED = "passed"
    MISSED = "missed"
    #: The run was too small to judge.
    NOT_GATED = "not_gated"

@dataclass(frozen=True, slots=True)
class Timings:
    samples: int
    p50: Seconds
    p95: Seconds
    maximum: Seconds

@dataclass(frozen=True, slots=True)
class RowsWritten:
    per_table: Mapping[TableName, int]
    projection_rows: int
    event_store_rows: int

@dataclass(frozen=True, slots=True)
class Budget:
    name: str
    limit: float
    unit: str
    #: None when the run was too small to gate.
    measured: float | None
    verdict: BudgetVerdict

@dataclass(frozen=True, slots=True)
class Environment:
    platform: str
    processor: str
    cpu_count: int
    #: None where the platform does not report it.
    total_memory_bytes: int | None
    python_version: str
    postgresql_version: str
    shared_buffers: str
    work_mem: str
    debug: bool

@dataclass(frozen=True, slots=True)
class SeedReport:
    catalog_rows: int
    catalog_seconds: Seconds
    events: int
    append_seconds: Seconds
    #: The bulk-write number, in place of a bulk command.
    events_per_second: float

@dataclass(frozen=True, slots=True)
class BenchmarkReport:
    schema: int  # 1
    environment: Environment
    #: None in --library mode.
    seed: SeedReport | None
    command: Timings | None
    rebuild: RebuildReport | None
    amplification: RowsWritten | None
    #: None when --keep was given.
    teardown_seconds: Seconds | None
    budgets: tuple[Budget, ...]

    def as_json(self) -> str: ...

def run_benchmark(
    *,
    seed: int,
    iterations: int,
    warmup: int,
    library: UserLibrary | None = None,
    keep: bool = False,
) -> BenchmarkReport: ...
```

`library=None` seeds a scratch one and runs all three scenarios. A `library`
given runs the read-only `rebuild` scenario against it and ignores `seed`; the
mutual exclusion of the two flags is enforced one layer up, where the operator
can be told which argument was wrong.

`Environment` records what the numbers are only true of. `total_memory_bytes`
comes from `os.sysconf` where POSIX offers it and is `None` elsewhere;
`shared_buffers` and `work_mem` come from `SHOW`, because the same hardware
tuned two ways gives two different rebuild times and a recorded number without
them cannot be reproduced.

The management command holds arguments and printing, the way
`rebuild_projections` does. It exits non-zero when `--gate` is given and a budget
is `MISSED`, and **always** exits non-zero on a non-empty rebuild diff, gated or
not.

That last rule differs from `manage.py rebuild_projections --check`, which exits
zero for drift because a rebuild is the thing that removes drift. The difference
is deliberate: that command is an operator tool reporting a condition it can fix,
while this one is producing evidence, and a diff means the parity claim the run
exists to make is false.

## Where the behaviour is pinned

`tests/test_event_benchmark.py`, at event counts small enough for the ordinary
suite:

- nearest-rank percentiles against a known sample list, including `n == 1` and a
  list whose p95 index lands exactly on the last element;
- warmup samples are excluded from the recorded ones;
- the row counter attributes an insert, an update, and a delete to the right
  table, and separates projection rows from event-store rows;
- one `library.playergame.created` event writes exactly one `games_playergame`
  row, which pins the `CURRENT_STATE` family's amplification;
- a seeded run's rebuild diff is empty — parity, at a small event count;
- a run purges its scratch user, and purges it after a scenario raises;
- `--keep` leaves it and prints the cleanup invocation;
- `--library` mode leaves every row of that library untouched, asserted by
  comparing projection contents and the stream head before and after;
- `--seed` and `--library` together are refused, naming the arguments;
- a rebuild diff that is not empty fails the run;
- a run below either gating threshold reports `NOT_GATED` and still prints its
  measurement;
- `--gate` exits non-zero on `MISSED` and zero on `PASSED`;
- `--json` parses and carries `schema == 1` and every scenario key;
- the seeded catalog is large enough for both consuming scenarios, asserted by
  running them both and finding no `CommandRejected`.

`write_targets` is today reached only through `only_shadow_writes`, and
`tests/test_projection_rebuild.py` exercises it that way. Making it public makes
it a name a second module depends on, so the rename brings direct tests of the
parser with it: a plain `INSERT`, a leading-comment `INSERT`, a `WITH` statement
that writes two tables, and a statement that writes nothing.

## Verification

- `make check` is green, including the new tests.
- `make bench` is run once on the development machine at the full 100,000 events,
  and its output is committed to `docs/event-benchmarks.md` together with the
  `Environment` block that produced it. That document is where the charter's
  "documented development machine" is finally documented; nothing in the
  repository defines it today.
- The committed run shows an empty rebuild diff at 100,000 events, which is the
  parity evidence #601 asks for.
- `make bench` is **not** part of `make check`. CI is 4 vCPU, where a timing gate
  produces a red build on a green machine.

## Reversibility

Nothing here is a data change and nothing needs rolling back. The issue adds a
module, a management command, a test file, a Makefile target, and a document;
removing them removes the feature. The single edit to existing code is the
`_write_targets` -> `write_targets` rename, reversible by the same means.

## Follow-up issues

- **#907** deletes the `TEST_COMMAND_*` members. This issue no longer touches
  them: with a real workload there is no synthetic command to name.
- **#917** stays open. The harness names it in a failure rather than fixing it.
- A concurrency harness has no issue and needs none until a phase states a
  contended budget.
- The 200 ms Journal page query budget belongs to phase 14. This issue measures
  neither it nor any query path.
