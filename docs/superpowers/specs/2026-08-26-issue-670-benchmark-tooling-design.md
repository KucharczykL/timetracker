# Command, replay, and projector benchmark tooling

Issue [#670](https://github.com/KucharczykL/timetracker/issues/670), phase
[#601](https://github.com/KucharczykL/timetracker/issues/601). Architecture: the
[overhaul charter](https://github.com/KucharczykL/timetracker/blob/codex/player-history-architecture/docs/superpowers/specs/2026-08-09-timetracker-overhaul-design.md).

## Status: parked until #671

**This specification is not ready to implement.** The dependency is
`#671 -> #670`: the benchmark harness is built against #671's real commands,
projector families, and projection tables, not against a synthetic stand-in.

An adversarial review of the draft below found that most of its complexity, and
one bias in its numbers, come from having no real consumer to measure. #601
already required this tooling to be reviewed with a real command/projector
consumer; sequencing it after #671 satisfies that by construction instead of by
promising a later re-record.

What changes when #671 lands:

| Draft section | Effect of #671 |
| --- | --- |
| The synthetic workload and its `CommandName` members | **Deleted.** All six `TEST_COMMAND_*` members are already claimed by `tests/test_command_dispatch.py`, and a second definition site raises `TypeError`, so a synthetic workload would need new placeholders in production code. Real commands need none |
| The workload's projection table | **Deleted.** #671 ships real projection tables by migration. The draft's isolated `Apps` registry, its runtime `schema_editor` DDL, and the clash with `test_the_application_declares_no_projection_table_yet` all go with it |
| The `--workload` plug point | **Deleted.** With a real default it is unused generality |
| Scratch teardown | **Shrinks** to the scratch user, which `delete_user_library` already handles |
| `--library` read-only mode | **Becomes worth having.** A real library holds real projections, so `CHECK` on a production copy is genuine parity evidence rather than an empty diff |
| Reference-carrying events | **Required.** #671's events reference Devices and catalog rows, so seeding must create resolvable ones. A reference-free stream understates both measurements: `LibraryEventReference` rows are written on every append, and `require_resolvable_references` runs before every fold |

What survives unchanged: the four scenarios, nearest-rank percentiles, the
scaled-and-withheld budget rule, the row counter, the `--gate` contract, the
environment block, and `docs/event-benchmarks.md`.

Six review findings are independent of #671 and still apply to the draft:
`rebuild._write_targets()` is private and reusing it does change #667's module;
teardown of a large scratch library cannot go through the ORM collector, because
`LibraryEventReference` blocks a fast delete; `--iterations` and the bulk event
count have no defaults; `Budget.passed` is meaningless when `gated` is false and
should be a three-way verdict; the environment block omits RAM and PostgreSQL
`shared_buffers`/`work_mem`; and no scenario measures concurrency, which is a
limit to state rather than to fix.

Everything below this section is the parked draft.

## What it is

One management command, `manage.py benchmark_events`, and the measurement module
behind it. It answers three questions the charter asks and nothing else answers
today:

- does an ordinary synchronous command finish within **100 ms at p95**;
- does a complete library rebuild of **100,000 events finish within 60 seconds**;
- **how many rows** does one event write, per projector family.

The first two are budgets the charter fixes and this issue makes measurable. The
third is a number the charter demands be *recorded* after every new projector
family, and fixes no limit for; the harness therefore reports it and never gates
on it.

The workload is a plug point rather than a fixture. Before #671 there is no real
command and no real projector family, so the default workload is synthetic and
every number it produces is labelled provisional. #671 supplies the first real
workload and re-records the table. That is the review constraint #601 states:
this tooling is not an independently proven foundation.

## Ownership boundary

| Not here | Owner |
| --- | --- |
| Real commands, projector families, and projection tables | #671 |
| The 200 ms Journal page query budget and its read model | phase 14 (#601) |
| Deleting the `TEST_COMMAND_*` allowlist members | #907 |
| A lever to disable server-side cursors under a pooler | #917 |
| Blocking direct writes to event-sourced projections | #737 |
| The shadow rebuild, the diff, and the swap | #667 |
| The bounded ordered fold | #666 |

This issue owns the measurement core, the workload protocol, the four scenarios,
the command that prints them, the budget declarations, and the recorded results
document.

**It changes no event-path code.** `dispatch`, `append`, `replay`, and
`rebuild_projections` are called exactly as they stand. `RebuildAttempt` already
carries `replay_seconds`, `diff_seconds`, and `swap_seconds`, so the rebuild
scenario needs no new instrumentation inside #667's code.

**It adds no migration and no model.**

## Preconditions

| Depends on | For |
| --- | --- |
| #664 `dispatch()` | the command-latency scenario |
| #666 `replay()` | folded through the rebuild |
| #667 `rebuild_projections()` and its per-phase timings | the rebuild scenario |
| #665 `ProjectorRegistry` and `EventWiring` | the workload plug point |
| #661 `lock_stream().append()` | batch seeding |
| `games/retention.py` `purging_library()` | scratch teardown |

PostgreSQL is required, as everywhere else. A run against SQLite is not a
supported measurement and the command does not attempt one.

## Design

### Four scenarios, three of which write

| Scenario | What it calls | Budget |
| --- | --- | --- |
| `command` | `dispatch()`, N times, each with its own idempotency key | 100 ms p95 |
| `bulk` | `dispatch()` of the workload's bulk command, N times | 100 ms p95 |
| `rebuild` | `rebuild_projections(CHECK)` then `rebuild_projections(REBUILD)` | 60 s per 100,000 events |
| `amplification` | the `command` and `bulk` scenarios again, under the row counter | recorded, never gated |

`--library <uuid>` runs the `rebuild` scenario alone, in `CHECK` mode, against a
library that already exists. It seeds nothing, creates nothing, and writes
nothing. It is how a production copy gets measured.

### Timing and percentiles

Every sample is one `monotonic()` interval around one call. A run discards
`--warmup` samples (default 10) before recording, because the first dispatch of a
process pays for connection setup, query-plan caching, and Python imports that no
later one pays for.

The percentile is **nearest rank** on the sorted samples: index
`ceil(p / 100 * n) - 1`. Not `statistics.quantiles`, whose interpolation invents a
value between two observations; a latency budget is a claim about observations.

p50, p95, and max are reported. The mean is not: it hides the tail the budget is
about.

### The rebuild scenario is also a parity proof

The seeded library is filled through the real append path, so its live
projections are what the write path produced. `rebuild_projections` replays the
same events into shadow tables and diffs them against those live rows. A run
whose `TableDiff` reports zero `only_live`, zero `only_rebuilt`, and zero
`differing` is replay parity demonstrated at 100,000 events, which is the
evidence the issue's acceptance criteria asks for. A non-zero diff fails the run
regardless of how fast it was: a rebuild that is quick and wrong is not a passing
benchmark.

`CHECK` runs first and writes nothing, so its `replay_seconds` is the fold cost
without the swap. `REBUILD` then gives the full five-phase wall clock, which is
the number the 60-second budget is stated against.

### The budget is scaled, and refuses to be scaled too far

The charter fixes 60 seconds at 100,000 events. A smaller run is compared against
`60 s x events / 100_000`.

Below **10,000 events** the gate does not apply the rebuild budget at all, and
says so. Temp-table creation, the `FULL OUTER JOIN` diff, and the swap have a
fixed cost that dominates a small stream, so a scaled budget there measures
overhead rather than throughput. The measured time, the event count, and the
events-per-second are printed in every case; only the pass/fail verdict is
withheld.

The same rule guards the latency budgets: fewer than 20 recorded samples reports
p95 without gating it.

### Write amplification, counted from the statements

A `connection.execute_wrapper` reuses `rebuild._write_targets()` to name the
table each statement writes, and adds `context["cursor"].rowcount` to a per-table
total. Rows are then classified by whether the table belongs to
`projection_models()`, the event store, or neither.

Counting statements rather than diffing `COUNT(*)` before and after is what makes
an update or a delete visible: a family that rewrites a row every event has an
amplification of one, and a before/after count would report zero.

Two limits, stated rather than hidden:

- the wrapper sees one connection, so a family that opens its own is not counted;
- under `executemany`, `rowcount` is the total across the batch, not per row,
  which is what the report wants anyway.

The report gives rows per event, rows per command, and the per-table breakdown.

### Seeding: a scratch library, purged on every exit path

`--seed N` (default 100,000):

1. create a `User` named `benchmark-<uuid4>`, and its `UserLibrary`;
2. append `N` events in batches of 1,000, each batch one transaction taking
   `lock_stream()` once and calling `append()` with the whole batch;
3. run the scenarios;
4. delete the user inside `purging_library()`, in a `finally`.

Batching is the difference between ~100 locked transactions and ~100,000 of them.
Seeding is timed and reported, and its time is never inside a measured window.

The command refuses to start if the scratch username already exists. `--keep`
skips the teardown for debugging and prints the exact `delete_user_library`
invocation that cleans up after it. `--seed` and `--library` are mutually
exclusive.

A scratch user is a real row in whatever database `DATABASE_URL` names. The
command prints what it is about to create before creating it.

### The workload plug point

```python
class BenchmarkWorkload(Protocol):
    name: str
    wiring: EventWiring
    events_per_command: int

    def command(self, index: int) -> Command: ...
    def bulk_command(self, index: int, *, events: int) -> Command: ...
    def seed_events(self, count: int) -> Iterator[NewEvent]: ...
```

`--workload <module>:<attribute>` imports it. There is **no default in production
code**. The synthetic workload lives in `tests/benchmark_workload.py`, and
`make bench` names it explicitly.

That placement is deliberate. A synthetic command still needs a `CommandName`
member, and `CommandName` is a closed allowlist in production code — but the
`TEST_COMMAND_*` members it needs already exist, shipped by #664 and already
tracked for removal by #907. Defining the workload in `tests/` therefore adds
**no new placeholder to production code**, which is the mistake #907 exists to
undo. `tests/` imports as a namespace package from the repository root, so
`manage.py` can load it without a package marker. The implementation proves that
first, before anything is built on it: if `manage.py` or mypy refuses the path,
the workload moves into `games/events/` and joins #907's list instead.

When #671 lands a real workload, `make bench` names that one instead, the numbers
stop being provisional, and #907 can delete the members and the synthetic
workload together.

### A pooled connection fails here first

`replay()` opens the longest-lived server-side cursor the application has. Under a
transaction-pooling connection pooler the following `FETCH` fails, and
`DISABLE_SERVER_SIDE_CURSORS` cannot currently be set — that is #917. A benchmark
is the first thing likely to be pointed at a pooled production copy, so a cursor
error out of the fold is caught and re-raised with a message naming #917 and the
pooler, rather than reading as a replay bug.

## API contract

```python
# games/events/benchmark.py

type Seconds = float
type TableName = str

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
    gated: bool

    @property
    def passed(self) -> bool: ...

@dataclass(frozen=True, slots=True)
class BenchmarkReport:
    schema: int  # 1
    workload: str
    environment: Environment
    seeded_events: int
    seed_seconds: Seconds
    command: Timings | None
    bulk: Timings | None
    rebuild: RebuildReport | None
    amplification: RowsWritten | None
    budgets: tuple[Budget, ...]

    def as_json(self) -> str: ...

def run_benchmark(
    workload: BenchmarkWorkload,
    *,
    seed: int,
    iterations: int,
    warmup: int,
    library: UserLibrary | None = None,
) -> BenchmarkReport: ...
```

`library=None` seeds a scratch one and runs all four scenarios. A `library`
given runs the read-only `rebuild` scenario against it and ignores `seed`; the
mutual exclusion of the two flags is enforced one layer up, where the operator
can be told which argument was wrong.

`Environment` records what the numbers are only true of: platform string,
processor, CPU count, Python version, PostgreSQL `version()`, and the Django
`DEBUG` flag.

The management command holds arguments and printing, the way
`rebuild_projections` does. It exits non-zero when `--gate` is given and a gated
budget was missed, and always exits non-zero on a non-empty rebuild diff.

## Where the behaviour is pinned

`tests/test_event_benchmark.py`, at event counts small enough for the ordinary
suite:

- nearest-rank percentiles against a known sample list, including `n == 1` and a
  list whose p95 index lands exactly on the last element;
- warmup samples are excluded from the recorded ones;
- the row counter attributes an insert, an update, and a delete to the right
  table, and separates projection rows from event-store rows;
- a run purges its scratch user, and purges it after a scenario raises;
- `--keep` leaves it and names the cleanup command;
- `--library` mode leaves every row of that library untouched, asserted by
  comparing projection contents and the stream head before and after;
- `--seed` and `--library` together are refused;
- a rebuild diff that is not empty fails the run;
- a budget below the gating threshold is reported and not gated;
- `--gate` exits non-zero on a missed budget and zero on a met one;
- `--json` parses and carries `schema == 1` and every scenario key;
- an unimportable `--workload` path is a `CommandError` naming the path.

## Verification

- `make check` is green, including the new tests.
- `make bench` is run once on the development machine at the full 100,000 events,
  and its output is committed to `docs/event-benchmarks.md` together with the
  `Environment` block that produced it. That document is where the charter's
  "documented development machine" is finally documented; nothing in the
  repository defines it today.
- The recorded numbers are labelled provisional against the synthetic workload.
- `make bench` is **not** part of `make check`. CI is 4 vCPU, where a timing gate
  produces a red build on a green machine.

## Follow-up issues

- **#671** re-records `docs/event-benchmarks.md` against its real commands and
  projector families, and supplies the workload `make bench` then defaults to.
  Until it does, no number here is evidence about production shapes.
- **#907** deletes the `TEST_COMMAND_*` members and, with them, the synthetic
  workload. It must follow #671 for that reason.
- **#917** stays open. The harness names it in a failure rather than fixing it.
- The 200 ms Journal page query budget has no read model to measure and belongs
  to phase 14. This issue measures neither it nor any query path.
