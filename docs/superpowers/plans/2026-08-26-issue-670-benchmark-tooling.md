# Command, replay, and projector benchmark tooling — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `manage.py benchmark_events`, which measures command latency,
rebuild time, and per-event write cost against the real `TrackGame` workload, and
record one full run in the repository.

**Architecture:** Two new modules under `games/events/` — `benchmark.py` holds the
report types, the percentile helper, the statement counter, the environment
capture, the budget rules, and `run_benchmark()`; `benchmark_workload.py` holds
seeding, the three scenarios, and teardown. A thin management command owns
arguments, printing, and exit codes, the way `rebuild_projections` does. One
existing private helper in `games/events/rebuild.py` becomes public so the
statement parser is shared rather than copied.

**Tech Stack:** Django 6, Python 3.14, PostgreSQL 18, pytest + pytest-django.

**Spec:** `docs/superpowers/specs/2026-08-26-issue-670-benchmark-tooling-design.md`

## Global Constraints

- **Every command goes through `make`.** Never `direnv exec .`, never a raw
  `uv run` / `pytest` / `pnpm`. Focused runs are `make test ARGS="…"`.
- **Iterate with `make check-fast`. The gate is the full `make check`**, including
  `e2e/`. `ARGS` is for iterating, never for the gate.
- **Python 3.14.** A `SyntaxError` in an `except A, B:` means the wrong
  interpreter, not broken code.
- Set `PYTEST_WORKERS=0` when debugging; parallel output interleaves.
- **Name variables with complete words** — `element` not `el`, `statement` not
  `stmt`, `index` not `i`, in Python and TypeScript alike.
- **Name compound types explicitly** (`TypedDict` / `NamedTuple` / `type` alias)
  and **name primitive roles too** with PEP 695 transparent aliases
  (`type Seconds = float`).
- **Never write to `GeneratedField`s** (`duration_calculated`, `duration_total`,
  `price_per_game`, `days_to_finish`, and `Game`'s `original_release_date_*`).
- Comments in this codebase are terse and use the `#:` marker for a note attached
  to the line below. Match the surrounding density; do not narrate.
- This issue **adds no migration and no model**.
- The only edit to existing production code is the `_write_targets` ->
  `write_targets` rename and its one call site.

## Budgets and constants, copied from the spec

| Constant | Value |
| --- | --- |
| `COMMAND_BUDGET_SECONDS` | `0.100` |
| `REBUILD_BUDGET_SECONDS` | `60.0` |
| `REBUILD_BUDGET_EVENTS` | `100_000` |
| `MINIMUM_GATED_EVENTS` | `2_000` |
| `MINIMUM_GATED_SAMPLES` | `20` |
| `CATALOG_BATCH` / `APPEND_BATCH` | `1_000` |
| `--seed` default | `100_000` |
| `--iterations` default | `200` |
| `--warmup` default | `10` |

Scenario order is part of the contract: **seed -> `command` -> `amplification`
-> `rebuild`**, and the rebuild budget scales on `RebuildReport.folded_through`,
never on `--seed`.

## File Structure

**Create:**

- `games/events/benchmark.py` — `Seconds`, `BudgetVerdict`, `Timings`,
  `WorkPerEvent`, `Budget`, `Environment`, `SeedReport`, `BenchmarkReport`,
  `nearest_rank`, `summarize`, `StatementCounter`, `environment`,
  `command_budget`, `rebuild_budget`, `run_benchmark`. Everything the spec's API
  contract names lives here.
- `games/events/benchmark_workload.py` — `seed_library`, `run_command_scenario`,
  `run_amplification_scenario`, `run_rebuild_scenario`, `purge_scratch_user`.
  The bulk that `benchmark.py` orchestrates.
- `games/management/commands/benchmark_events.py` — arguments, printing, exit
  codes. No decisions.
- `tests/test_event_benchmark.py` — everything the spec's "Where the behaviour is
  pinned" section lists, at small event counts.
- `docs/event-benchmarks.md` — the recorded run and the machine that produced it.

**Modify:**

- `games/events/rebuild.py:129` — `_write_targets` -> `write_targets`, and its one
  call site at `games/events/rebuild.py:118`.
- `tests/test_projection_rebuild.py` — direct tests of the now-public parser.
- `tests/test_retention.py` — purging a library that holds a projection row.
- `Makefile` — a `bench` target beside `audit-uuid-identity` (around line 269).

---

### Task 1: Publish the statement parser

The harness and the shadow-write guard must not carry two regexes for one job.
This task is first because Task 3 imports the result.

**Files:**
- Modify: `games/events/rebuild.py:118`, `games/events/rebuild.py:129`
- Test: `tests/test_projection_rebuild.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `write_targets(statement: str) -> tuple[TableName, ...]`, importable
  from `games.events.rebuild`. Returns every table a statement writes; `()` for a
  statement that writes nothing; `("",)` for a write it could not parse, which
  the guard treats as a refusal.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_projection_rebuild.py`. Import `write_targets` alongside the
other names already imported from `games.events.rebuild` (the import block starts
at line 29).

```python
@pytest.mark.parametrize(
    ("statement", "expected"),
    [
        ('INSERT INTO "games_playergame" (id) VALUES (%s)', ("games_playergame",)),
        (
            '/* a comment */ INSERT INTO "games_playergame" (id) VALUES (%s)',
            ("games_playergame",),
        ),
        (
            'WITH moved AS (DELETE FROM "old" RETURNING *) '
            'INSERT INTO "new" SELECT * FROM moved',
            ("old", "new"),
        ),
        ('SELECT 1 FROM "games_playergame"', ()),
        ("SAVEPOINT s1", ()),
        ('UPDATE ONLY pg_temp."games_playergame__shadow" SET id = id', 
         ("games_playergame__shadow",)),
    ],
)
def test_write_targets_names_every_table_a_statement_writes(statement, expected):
    assert write_targets(statement) == expected


def test_write_targets_refuses_a_write_it_cannot_parse():
    #: An empty name is the guard's refusal, not a miss.
    assert write_targets("INSERT INTO (broken") == ("",)
```

- [ ] **Step 2: Run the tests to verify they fail**

```
make test ARGS="tests/test_projection_rebuild.py -k write_targets"
```

Expected: FAIL with `ImportError: cannot import name 'write_targets'`.

- [ ] **Step 3: Rename the function and its call site**

In `games/events/rebuild.py`, rename `_write_targets` to `write_targets` and give
it a docstring that says it is shared:

```python
def write_targets(statement: str) -> tuple[TableName, ...]:
    """Every table written; unreadable means refused.

    Public because the benchmark counts the same statements this guard
    refuses, and two regexes for one job would drift.
    """
```

Update the single call site inside `_refuse_a_live_write`:

```python
    for target in write_targets(sql):
```

- [ ] **Step 4: Run the tests to verify they pass**

```
make test ARGS="tests/test_projection_rebuild.py"
```

Expected: PASS, the whole file, including the pre-existing `only_shadow_writes`
tests that reach the parser indirectly.

- [ ] **Step 5: Commit**

```bash
git add games/events/rebuild.py tests/test_projection_rebuild.py
git commit -m "Share the statement parser instead of copying it"
```

---

### Task 2: Nearest-rank percentiles

**Files:**
- Create: `games/events/benchmark.py`
- Test: `tests/test_event_benchmark.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `type Seconds = float`; `Timings(samples: int, p50: Seconds,
  p95: Seconds, maximum: Seconds)`; `nearest_rank(samples: Sequence[Seconds],
  percentile: int) -> Seconds`; `summarize(samples: Sequence[Seconds]) ->
  Timings`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_event_benchmark.py`:

```python
"""The benchmark harness: percentiles, counting, budgets, scenarios."""

import pytest

from games.events.benchmark import Timings, nearest_rank, summarize


def test_nearest_rank_returns_an_observation_for_one_sample():
    assert nearest_rank([0.5], 95) == 0.5


def test_nearest_rank_never_interpolates_between_two_observations():
    #: statistics.quantiles would answer 0.15 here.
    assert nearest_rank([0.1, 0.2], 50) == 0.1


def test_nearest_rank_can_land_on_the_last_observation():
    samples = [float(value) for value in range(1, 11)]
    assert nearest_rank(samples, 95) == 10.0


def test_nearest_rank_sorts_before_ranking():
    assert nearest_rank([0.3, 0.1, 0.2], 50) == 0.2


def test_nearest_rank_refuses_an_empty_sample_set():
    with pytest.raises(ValueError, match="at least one sample"):
        nearest_rank([], 95)


def test_summarize_reports_the_count_the_tail_and_the_worst():
    samples = [float(value) for value in range(1, 21)]
    assert summarize(samples) == Timings(samples=20, p50=10.0, p95=19.0, maximum=20.0)
```

- [ ] **Step 2: Run the tests to verify they fail**

```
make test ARGS="tests/test_event_benchmark.py"
```

Expected: FAIL, `ModuleNotFoundError: No module named 'games.events.benchmark'`.

- [ ] **Step 3: Write the module**

Create `games/events/benchmark.py`:

```python
"""What a command costs, what a rebuild costs, and what one event costs.

The charter fixes two numbers -- 100 ms at p95 for an ordinary command, 60
seconds for a 100,000-event rebuild -- and asks that write amplification be
recorded after every new projector family without fixing a limit for it. This
module measures all three against the real workload, and this module is the
only place those numbers are written down.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass

#: A wall-clock interval, from time.monotonic().
type Seconds = float


@dataclass(frozen=True, slots=True)
class Timings:
    """One scenario's latency distribution."""

    samples: int
    p50: Seconds
    p95: Seconds
    maximum: Seconds


def nearest_rank(samples: Sequence[Seconds], percentile: int) -> Seconds:
    """The observation at `percentile`, never a value between two.

    `statistics.quantiles` interpolates, which invents a latency nothing
    measured. A budget is a claim about observations.
    """
    if not samples:
        raise ValueError("A percentile needs at least one sample.")
    ordered = sorted(samples)
    index = math.ceil(percentile / 100 * len(ordered)) - 1
    return ordered[max(index, 0)]


def summarize(samples: Sequence[Seconds]) -> Timings:
    """The three numbers worth reading; the mean hides the tail."""
    return Timings(
        samples=len(samples),
        p50=nearest_rank(samples, 50),
        p95=nearest_rank(samples, 95),
        maximum=max(samples),
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

```
make test ARGS="tests/test_event_benchmark.py"
```

Expected: PASS, 6 tests.

- [ ] **Step 5: Commit**

```bash
git add games/events/benchmark.py tests/test_event_benchmark.py
git commit -m "Rank the samples rather than interpolate between them"
```

---

### Task 3: The statement counter

**Files:**
- Modify: `games/events/benchmark.py`
- Test: `tests/test_event_benchmark.py`

**Interfaces:**
- Consumes: `write_targets` from Task 1; `TableName` and `projection_models` from
  `games.events.rebuild`.
- Produces: `EVENT_STORE_TABLES: frozenset[TableName]`;
  `WorkPerEvent(events, statements, rows_per_table, statements_per_table,
  projection_rows, projection_statements, event_store_rows,
  event_store_statements)`; `StatementCounter` — a callable suitable for
  `connection.execute_wrapper`, with `.work(events: int) -> WorkPerEvent`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_event_benchmark.py`:

```python
from django.db import connection

from games.events.benchmark import StatementCounter
from games.models import PlayerGame


@pytest.mark.django_db
def test_the_counter_attributes_a_write_to_the_table_it_names(owned_library):
    counter = StatementCounter()
    table = PlayerGame._meta.db_table
    with connection.execute_wrapper(counter):
        with connection.cursor() as cursor:
            cursor.execute(f'SELECT count(*) FROM "{table}"')
    assert counter.statements_per_table == {}
    assert counter.statements == 1


@pytest.mark.django_db
def test_the_counter_separates_projections_from_the_event_store(owned_library):
    #: One tracked game: one projection row, one event, one reference.
    counter = StatementCounter()
    with connection.execute_wrapper(counter):
        track_one_game(owned_library)
    work = counter.work(events=1)
    assert work.projection_rows == 1
    assert work.projection_statements == 1
    assert work.event_store_rows >= 3
    assert work.statements > work.projection_statements


@pytest.mark.django_db
def test_the_counter_counts_statements_that_name_no_table(owned_library):
    counter = StatementCounter()
    with connection.execute_wrapper(counter):
        with connection.cursor() as cursor:
            cursor.execute("SAVEPOINT benchmark_probe")
            cursor.execute("RELEASE SAVEPOINT benchmark_probe")
    assert counter.statements == 2
    assert counter.statements_per_table == {}
```

`track_one_game` is a helper this test file needs from here on. Add it near the
top of the file, below the imports:

```python
import uuid

from games.commands.playergame import TrackGame
from games.events.dispatch import dispatch
from games.models import Game


def track_one_game(library, *, name: str = "Benchmark probe") -> Game:
    """Dispatch one real TrackGame against a fresh catalog row."""
    game = Game.objects.create(library=library, name=name)
    dispatch(
        TrackGame(game_id=game.pk),
        actor=library.user,
        library=library,
        idempotency_key=str(uuid.uuid7()),
    )
    return game
```

- [ ] **Step 2: Run the tests to verify they fail**

```
make test ARGS="tests/test_event_benchmark.py -k counter" PYTEST_WORKERS=0
```

Expected: FAIL, `ImportError: cannot import name 'StatementCounter'`.

- [ ] **Step 3: Write the counter**

Add to `games/events/benchmark.py`. Extend the imports at the top:

```python
from dataclasses import dataclass, field
from typing import Any

from games.events.rebuild import TableName, projection_models, write_targets
from games.models import (
    LibraryEvent,
    LibraryEventReference,
    LibraryEventStreamHead,
    LibraryIdempotencyRecord,
)

#: The four tables an append writes outside the projections.
EVENT_STORE_TABLES: frozenset[TableName] = frozenset(
    model._meta.db_table
    for model in (
        LibraryEvent,
        LibraryEventReference,
        LibraryEventStreamHead,
        LibraryIdempotencyRecord,
    )
)
```

```python
@dataclass(frozen=True, slots=True)
class WorkPerEvent:
    """What one event cost, in rows and in statements."""

    events: int
    #: Every statement in the window, savepoints included.
    statements: int
    rows_per_table: Mapping[TableName, int]
    #: Only statements that name a table they write.
    statements_per_table: Mapping[TableName, int]
    projection_rows: int
    projection_statements: int
    event_store_rows: int
    event_store_statements: int


@dataclass(slots=True)
class StatementCounter:
    """Every statement, and the rows the writing ones touched.

    Counting statements rather than diffing COUNT(*) is what makes an update
    visible: a family that rewrites one row an event amplifies by one, and a
    before-and-after count would report zero. The total matters as much as the
    per-table breakdown, because four of the current fold's six statements are
    savepoints and name no table at all.

    Two limits: this sees one connection, so a family that opens its own is
    not counted, and under executemany `rowcount` is the batch's total.
    """

    statements: int = 0
    rows_per_table: dict[TableName, int] = field(default_factory=dict)
    statements_per_table: dict[TableName, int] = field(default_factory=dict)

    def __call__(
        self, execute: Any, sql: str, params: Any, many: bool, context: Any
    ) -> Any:
        result = execute(sql, params, many, context)
        self.statements += 1
        rowcount = context["cursor"].rowcount
        for table in write_targets(sql):
            #: An unparseable write; the guard refuses it, we skip it.
            if not table:
                continue
            self.statements_per_table[table] = (
                self.statements_per_table.get(table, 0) + 1
            )
            if rowcount > 0:
                self.rows_per_table[table] = self.rows_per_table.get(table, 0) + rowcount
        return result

    def work(self, *, events: int) -> WorkPerEvent:
        """Freeze the totals, classified by what owns each table."""
        projection_tables = {model._meta.db_table for model in projection_models()}
        return WorkPerEvent(
            events=events,
            statements=self.statements,
            rows_per_table=dict(self.rows_per_table),
            statements_per_table=dict(self.statements_per_table),
            projection_rows=self._total(self.rows_per_table, projection_tables),
            projection_statements=self._total(
                self.statements_per_table, projection_tables
            ),
            event_store_rows=self._total(self.rows_per_table, EVENT_STORE_TABLES),
            event_store_statements=self._total(
                self.statements_per_table, EVENT_STORE_TABLES
            ),
        )

    @staticmethod
    def _total(counts: Mapping[TableName, int], tables: Container[TableName]) -> int:
        return sum(count for table, count in counts.items() if table in tables)
```

Add `Container` and `Mapping` to the `collections.abc` import.

- [ ] **Step 4: Run the tests to verify they pass**

```
make test ARGS="tests/test_event_benchmark.py" PYTEST_WORKERS=0
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add games/events/benchmark.py tests/test_event_benchmark.py
git commit -m "Count the statements, not only the rows they wrote"
```

---

### Task 4: What the numbers are true of

**Files:**
- Modify: `games/events/benchmark.py`
- Test: `tests/test_event_benchmark.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `Environment(platform, processor, cpu_count, total_memory_bytes,
  python_version, postgresql_version, shared_buffers, work_mem, debug)` and
  `environment() -> Environment`.

- [ ] **Step 1: Write the failing test**

```python
from games.events.benchmark import Environment, environment


@pytest.mark.django_db
def test_the_environment_records_what_the_numbers_are_true_of():
    captured = environment()
    assert isinstance(captured, Environment)
    assert captured.cpu_count >= 1
    assert captured.python_version.startswith("3.14")
    #: Same hardware, two tunings, two rebuild times.
    assert captured.shared_buffers
    assert captured.work_mem
    assert captured.postgresql_version
```

- [ ] **Step 2: Run it to verify it fails**

```
make test ARGS="tests/test_event_benchmark.py -k environment" PYTEST_WORKERS=0
```

Expected: FAIL, `cannot import name 'Environment'`.

- [ ] **Step 3: Implement**

```python
import os
import platform as platform_module

from django.conf import settings
from django.db import connection


@dataclass(frozen=True, slots=True)
class Environment:
    """The machine and the tuning a measurement belongs to."""

    platform: str
    #: Empty on the Linux systems where platform.processor() says nothing.
    processor: str
    cpu_count: int
    #: None where the platform does not report it.
    total_memory_bytes: int | None
    python_version: str
    postgresql_version: str
    shared_buffers: str
    work_mem: str
    debug: bool


def environment() -> Environment:
    """Everything needed to reproduce a number, or to distrust it."""
    with connection.cursor() as cursor:
        settings_read = {}
        for name in ("server_version", "shared_buffers", "work_mem"):
            cursor.execute(f"SHOW {name}")
            settings_read[name] = cursor.fetchone()[0]
    return Environment(
        platform=platform_module.platform(),
        processor=platform_module.processor(),
        cpu_count=os.cpu_count() or 0,
        total_memory_bytes=_total_memory(),
        python_version=platform_module.python_version(),
        postgresql_version=settings_read["server_version"],
        shared_buffers=settings_read["shared_buffers"],
        work_mem=settings_read["work_mem"],
        debug=settings.DEBUG,
    )


def _total_memory() -> int | None:
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (AttributeError, ValueError, OSError):
        #: Windows, and any POSIX that declines to answer.
        return None
```

The `SHOW` name is interpolated rather than parameterized because PostgreSQL
does not accept a parameter there; the three names are literals in this file and
never reach it from input.

- [ ] **Step 4: Run it to verify it passes**

```
make test ARGS="tests/test_event_benchmark.py" PYTEST_WORKERS=0
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add games/events/benchmark.py tests/test_event_benchmark.py
git commit -m "Record the machine a number belongs to"
```

---

### Task 5: Budgets with three outcomes

A boolean forces a run that was too small to judge into one of two answers it did
not earn.

**Files:**
- Modify: `games/events/benchmark.py`
- Test: `tests/test_event_benchmark.py`

**Interfaces:**
- Consumes: `Timings` from Task 2; `RebuildReport` from `games.events.rebuild`.
- Produces: `BudgetVerdict` (`PASSED` / `MISSED` / `NOT_GATED`);
  `Budget(name, limit, unit, measured, verdict)`; the constants table above;
  `command_budget(timings: Timings) -> Budget`;
  `rebuild_budget(report: RebuildReport) -> Budget`.

- [ ] **Step 1: Write the failing tests**

```python
from dataclasses import replace

from games.events.benchmark import (
    BudgetVerdict,
    command_budget,
    rebuild_budget,
)
from games.events.rebuild import RebuildMode, RebuildReport


def timings(p95: float, *, samples: int = 200) -> Timings:
    return Timings(samples=samples, p50=p95 / 2, p95=p95, maximum=p95 * 2)


def rebuild_report(*, folded_through: int, elapsed_seconds: float) -> RebuildReport:
    return RebuildReport(
        library_id=uuid.uuid7(),
        stream_id=uuid.uuid7(),
        mode=RebuildMode.REBUILD,
        swapped=True,
        folded_through=folded_through,
        head_at_diff=folded_through,
        tables=(),
        attempts=(),
        elapsed_seconds=elapsed_seconds,
    )


def test_a_command_inside_the_budget_passes():
    assert command_budget(timings(0.05)).verdict is BudgetVerdict.PASSED


def test_a_command_over_the_budget_misses():
    assert command_budget(timings(0.15)).verdict is BudgetVerdict.MISSED


def test_too_few_samples_is_not_gated_but_is_still_measured():
    budget = command_budget(timings(0.15, samples=19))
    assert budget.verdict is BudgetVerdict.NOT_GATED
    assert budget.measured == 0.15


def test_the_rebuild_budget_scales_to_the_events_actually_folded():
    #: 60s per 100k, so 10k gets 6s.
    budget = rebuild_budget(rebuild_report(folded_through=10_000, elapsed_seconds=5.9))
    assert budget.limit == pytest.approx(6.0)
    assert budget.verdict is BudgetVerdict.PASSED


def test_a_rebuild_over_its_scaled_budget_misses():
    budget = rebuild_budget(rebuild_report(folded_through=10_000, elapsed_seconds=6.5))
    assert budget.verdict is BudgetVerdict.MISSED


def test_a_rebuild_below_the_gating_floor_is_not_gated():
    #: Scaling is verified linear from 2,000 up, not below.
    budget = rebuild_budget(rebuild_report(folded_through=1_999, elapsed_seconds=99.0))
    assert budget.verdict is BudgetVerdict.NOT_GATED
    assert budget.measured == 99.0
```

- [ ] **Step 2: Run them to verify they fail**

```
make test ARGS="tests/test_event_benchmark.py -k budget" PYTEST_WORKERS=0
```

Expected: FAIL, `cannot import name 'BudgetVerdict'`.

- [ ] **Step 3: Implement**

```python
from enum import StrEnum

from games.events.rebuild import RebuildReport

#: The charter's numbers. Nowhere else.
COMMAND_BUDGET_SECONDS: Seconds = 0.100
REBUILD_BUDGET_SECONDS: Seconds = 60.0
REBUILD_BUDGET_EVENTS = 100_000

#: Scaling is verified linear from here up, not below.
MINIMUM_GATED_EVENTS = 2_000
MINIMUM_GATED_SAMPLES = 20


class BudgetVerdict(StrEnum):
    """A budget has three outcomes, not two."""

    PASSED = "passed"
    MISSED = "missed"
    #: The run was too small to judge.
    NOT_GATED = "not_gated"


@dataclass(frozen=True, slots=True)
class Budget:
    name: str
    limit: float
    unit: str
    #: Always recorded; only the verdict is withheld.
    measured: float
    verdict: BudgetVerdict


def _verdict(*, measured: float, limit: float, gated: bool) -> BudgetVerdict:
    if not gated:
        return BudgetVerdict.NOT_GATED
    return BudgetVerdict.PASSED if measured <= limit else BudgetVerdict.MISSED


def command_budget(timings: Timings) -> Budget:
    """The charter's 100 ms at p95, for an ordinary command."""
    return Budget(
        name="command p95",
        limit=COMMAND_BUDGET_SECONDS,
        unit="s",
        measured=timings.p95,
        verdict=_verdict(
            measured=timings.p95,
            limit=COMMAND_BUDGET_SECONDS,
            gated=timings.samples >= MINIMUM_GATED_SAMPLES,
        ),
    )


def rebuild_budget(report: RebuildReport) -> Budget:
    """60 s per 100,000 events, scaled to what was actually folded."""
    events = report.folded_through
    limit = REBUILD_BUDGET_SECONDS * events / REBUILD_BUDGET_EVENTS
    return Budget(
        name="rebuild",
        limit=limit,
        unit="s",
        measured=report.elapsed_seconds,
        verdict=_verdict(
            measured=report.elapsed_seconds,
            limit=limit,
            gated=events >= MINIMUM_GATED_EVENTS,
        ),
    )
```

- [ ] **Step 4: Run them to verify they pass**

```
make test ARGS="tests/test_event_benchmark.py" PYTEST_WORKERS=0
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add games/events/benchmark.py tests/test_event_benchmark.py
git commit -m "Withhold a verdict a run was too small to earn"
```

---

### Task 6: Seeding — the catalog first, then the stream

**Files:**
- Create: `games/events/benchmark_workload.py`
- Modify: `games/events/benchmark.py` (add `SeedReport`)
- Test: `tests/test_event_benchmark.py`

**Interfaces:**
- Consumes: `lock_stream` from `games.events.append`, `capture_reference` from
  `games.events.references`, `PLAYERGAME_CREATED` from
  `games.events.playergame`, `Game`/`UserLibrary` from `games.models`.
- Produces: `SEEDED_NAME_PREFIX`, `SPARE_NAME_PREFIX`, `CATALOG_BATCH`,
  `APPEND_BATCH`, `SEED_IDEMPOTENCY_KEY`;
  `seed_library(library, *, actor, events: int, spares: int) -> SeedReport`;
  `spare_games(library) -> Iterator[Game]`.
  `SeedReport(catalog_rows, catalog_seconds, events, append_seconds,
  events_per_second)` lives in `games/events/benchmark.py`.

Batching is the difference between ~100 locked transactions and ~100,000 of them.
Seeding goes through `LockedStream.append` rather than `dispatch`, so it skips
the idempotency record and the duplicate check, but the same validation runs, the
same `LibraryEventReference` rows are written, and `append()` folds the same
projectors inline — which is what makes Task 8's rebuild a parity proof.

Reusing one idempotency key across batches is safe: `LibraryEvent` carries only a
not-empty check on that column, and the `(library, idempotency_key)` uniqueness
lives on `LibraryIdempotencyRecord`, which a direct `append()` never writes.

- [ ] **Step 1: Write the failing tests**

```python
from games.events.benchmark import SeedReport
from games.events.benchmark_workload import seed_library, spare_games
from games.models import LibraryEvent


@pytest.mark.django_db
def test_seeding_writes_the_events_and_the_projection_rows(owned_library):
    report = seed_library(owned_library, actor=owned_library.user, events=25, spares=4)
    assert isinstance(report, SeedReport)
    assert report.events == 25
    assert report.catalog_rows == 29
    assert LibraryEvent.objects.filter(library=owned_library).count() == 25
    #: append() folds inline, so the live rows exist already.
    assert PlayerGame.objects.filter(library=owned_library).count() == 25


@pytest.mark.django_db
def test_seeding_batches_the_stream_rather_than_locking_per_event(owned_library):
    counter = StatementCounter()
    with connection.execute_wrapper(counter):
        seed_library(owned_library, actor=owned_library.user, events=25, spares=0)
    head = LibraryEventStreamHead._meta.db_table
    #: One batch, so the head advances once.
    assert counter.statements_per_table[head] == 1


@pytest.mark.django_db
def test_seeding_leaves_the_spare_games_untracked(owned_library):
    seed_library(owned_library, actor=owned_library.user, events=5, spares=3)
    spares = list(spare_games(owned_library))
    assert len(spares) == 3
    assert not PlayerGame.objects.filter(game__in=spares).exists()


@pytest.mark.django_db
def test_seeding_reports_append_throughput(owned_library):
    report = seed_library(owned_library, actor=owned_library.user, events=25, spares=0)
    assert report.events_per_second > 0
    assert report.append_seconds > 0
    #: Setup is timed apart from the measurement.
    assert report.catalog_seconds > 0
```

- [ ] **Step 2: Run them to verify they fail**

```
make test ARGS="tests/test_event_benchmark.py -k seeding" PYTEST_WORKERS=0
```

Expected: FAIL, `No module named 'games.events.benchmark_workload'`.

- [ ] **Step 3a: Add `SeedReport` to `games/events/benchmark.py`**

```python
@dataclass(frozen=True, slots=True)
class SeedReport:
    """Setup, timed apart from the measurement."""

    catalog_rows: int
    catalog_seconds: Seconds
    events: int
    append_seconds: Seconds
    #: The bulk-write number, in place of a bulk command.
    events_per_second: float
```

- [ ] **Step 3b: Write `games/events/benchmark_workload.py`**

```python
"""Seeding, the three scenarios, and the scratch teardown.

Everything here works on a real library through the real write path. There is
no workload protocol and no plug point: #671 shipped one command, one event
type and one projector family, and this module names them.
"""

import uuid
from collections.abc import Iterator, Sequence
from io import StringIO
from time import monotonic

from django.contrib.auth.models import User
from django.core.management import call_command
from django.db import transaction

from games.events.append import lock_stream
from games.events.benchmark import Seconds, SeedReport
from games.events.playergame import PLAYERGAME_CREATED
from games.events.references import capture_reference
from games.models import Game, UserLibrary

#: The seeded catalog rows, and the untracked ones scenarios consume.
SEEDED_NAME_PREFIX = "Benchmark game "
SPARE_NAME_PREFIX = "Benchmark spare "

CATALOG_BATCH = 1_000
APPEND_BATCH = 1_000

#: One key for every batch: only LibraryIdempotencyRecord is unique on it,
#: and a direct append() never writes one.
SEED_IDEMPOTENCY_KEY = "benchmark-seed"

#: capture_reference reads exactly these three.
_CAPTURED_FIELDS = ("id", "name", "year_released")


def seed_library(
    library: UserLibrary, *, actor: User, events: int, spares: int
) -> SeedReport:
    """Fill `library` with `events` real events, plus `spares` untracked games."""
    catalog_started = monotonic()
    _create_catalog(library, prefix=SEEDED_NAME_PREFIX, count=events)
    _create_catalog(library, prefix=SPARE_NAME_PREFIX, count=spares)
    catalog_seconds = monotonic() - catalog_started

    append_started = monotonic()
    correlation_id = uuid.uuid7()
    for batch in _batched(_seeded_games(library), APPEND_BATCH):
        with transaction.atomic():
            lock_stream(library).append(
                [
                    PLAYERGAME_CREATED.new(
                        aggregate_id=uuid.uuid7(),
                        payload={"game": capture_reference(game)},
                    )
                    for game in batch
                ],
                actor=actor,
                correlation_id=correlation_id,
                idempotency_key=SEED_IDEMPOTENCY_KEY,
            )
    append_seconds = monotonic() - append_started

    return SeedReport(
        catalog_rows=events + spares,
        catalog_seconds=catalog_seconds,
        events=events,
        append_seconds=append_seconds,
        events_per_second=events / append_seconds if append_seconds else 0.0,
    )


def _create_catalog(library: UserLibrary, *, prefix: str, count: int) -> None:
    """Rows nothing has tracked, named so a scenario can find them."""
    for start in range(0, count, CATALOG_BATCH):
        Game.objects.bulk_create(
            Game(library=library, name=f"{prefix}{index}")
            for index in range(start, min(start + CATALOG_BATCH, count))
        )


def _seeded_games(library: UserLibrary) -> Iterator[Game]:
    return _catalog(library, SEEDED_NAME_PREFIX)


def spare_games(library: UserLibrary) -> Iterator[Game]:
    """The untracked rows the command scenarios consume, one each."""
    return _catalog(library, SPARE_NAME_PREFIX)


def _catalog(library: UserLibrary, prefix: str) -> Iterator[Game]:
    #: An iterator, because 100,000 model instances is not a list.
    return (
        Game.objects.filter(library=library, name__startswith=prefix)
        .only(*_CAPTURED_FIELDS)
        .order_by("id")
        .iterator(chunk_size=CATALOG_BATCH)
    )


def _batched[T](items: Iterator[T], size: int) -> Iterator[Sequence[T]]:
    batch: list[T] = []
    for item in items:
        batch.append(item)
        if len(batch) == size:
            yield batch
            batch = []
    if batch:
        yield batch
```

Use `itertools.batched` instead of `_batched` if it accepts an iterator cleanly —
it does, and it is the standard-library spelling. Prefer it:

```python
from itertools import batched
```

and drop `_batched`, calling `batched(_seeded_games(library), APPEND_BATCH)`.

- [ ] **Step 4: Run them to verify they pass**

```
make test ARGS="tests/test_event_benchmark.py" PYTEST_WORKERS=0
```

Expected: PASS. If `bulk_create` refuses the `Game` model over its
`GeneratedField`s, stop and report — the probe run during specification did this
successfully, so a failure here is new information.

- [ ] **Step 5: Commit**

```bash
git add games/events/benchmark.py games/events/benchmark_workload.py tests/test_event_benchmark.py
git commit -m "Seed a library the way a library is really written"
```

---

### Task 7: Teardown, and the retention claim it rests on

**Files:**
- Modify: `games/events/benchmark_workload.py`
- Test: `tests/test_retention.py`, `tests/test_event_benchmark.py`

**Interfaces:**
- Consumes: the existing `manage.py delete_user_library`.
- Produces: `purge_scratch_user(username: str) -> Seconds`.

`PlayerGame.game` is `RESTRICT`, so the collector could refuse. It does not,
because `ProjectionModel.library` is `CASCADE`: the projection rows are collected
through the library, and Django clears a restriction whose objects are themselves
being deleted. No existing test covers a purge of a library holding a projection
row, and the claim belongs in the retention tests rather than the benchmark ones.

- [ ] **Step 1: Write the failing retention test**

Add to `tests/test_retention.py`, following that file's existing fixture style:

```python
@pytest.mark.django_db
def test_purging_a_library_takes_its_projection_rows_with_it(owned_library):
    """PlayerGame.game is RESTRICT; CASCADE through the library clears it."""
    user = owned_library.user
    game = Game.objects.create(library=owned_library, name="Purged")
    dispatch(
        TrackGame(game_id=game.pk),
        actor=user,
        library=owned_library,
        idempotency_key=str(uuid.uuid7()),
    )
    assert PlayerGame.objects.filter(library=owned_library).exists()

    with transaction.atomic(), purging_library():
        user.delete()

    assert not PlayerGame.objects.filter(library=owned_library).exists()
    assert not Game.objects.filter(pk=game.pk).exists()
```

- [ ] **Step 2: Run it**

```
make test ARGS="tests/test_retention.py -k projection" PYTEST_WORKERS=0
```

Expected: PASS immediately — this test documents existing behaviour rather than
driving new code. If it FAILS with `RestrictedError`, stop: the spec's teardown
design is wrong and the issue needs re-scoping, not a workaround.

- [ ] **Step 3: Write the failing benchmark teardown test**

```python
@pytest.mark.django_db
def test_the_scratch_user_is_purged_and_the_purge_is_timed(owned_library):
    username = owned_library.user.username
    track_one_game(owned_library, name="Purged by the harness")
    elapsed = purge_scratch_user(username)
    assert elapsed > 0
    assert not User.objects.filter(username=username).exists()
```

- [ ] **Step 4: Run it to verify it fails, then implement**

```
make test ARGS="tests/test_event_benchmark.py -k purged" PYTEST_WORKERS=0
```

Expected: FAIL, `cannot import name 'purge_scratch_user'`.

Add to `games/events/benchmark_workload.py`:

```python
def purge_scratch_user(username: str) -> Seconds:
    """Delete the scratch user through the command that already knows how.

    At 100,000 events this collects roughly 400,000 rows -- the events, their
    reference rows, the catalog, and the projections -- and takes about a sixth
    of the run. A second, raw-SQL copy of the cascade would be faster and would
    be a second thing that can drift from `on_delete`.

    delete_user_library walks the collector twice, once to print the scope and
    once to delete. Both walks are inside this number.
    """
    started = monotonic()
    call_command(
        "delete_user_library",
        user=username,
        confirm=username,
        stdout=StringIO(),
    )
    return monotonic() - started
```

- [ ] **Step 5: Run both files, then commit**

```
make test ARGS="tests/test_event_benchmark.py tests/test_retention.py" PYTEST_WORKERS=0
```

```bash
git add games/events/benchmark_workload.py tests/test_event_benchmark.py tests/test_retention.py
git commit -m "Purge the scratch library through the cascade, and prove it works"
```

---

### Task 8: The three scenarios, and the run that orders them

**Files:**
- Modify: `games/events/benchmark_workload.py`, `games/events/benchmark.py`
- Test: `tests/test_event_benchmark.py`

**Interfaces:**
- Consumes: everything above; `dispatch`, `TrackGame`, `rebuild_projections`,
  `RebuildMode`.
- Produces, in `benchmark_workload.py`:
  `run_command_scenario(library, *, actor, games, iterations, warmup) -> Timings`;
  `run_amplification_scenario(library, *, actor, games, iterations) -> WorkPerEvent`;
  `run_rebuild_scenario(library, *, mode, count_fold) -> tuple[RebuildReport, WorkPerEvent | None]`.
  In `benchmark.py`: `BenchmarkReport`, `RebuildDiffNotEmpty`, `run_benchmark`.

Order is the contract. The rebuild runs **last** so its diff covers events written
by `LockedStream.append` *and* by `dispatch`, and its budget therefore scales on
`RebuildReport.folded_through` rather than on `--seed`, which by then it exceeds
by `2 * iterations + warmup`.

- [ ] **Step 1: Write the failing tests**

```python
from games.events.benchmark import BenchmarkReport, RebuildDiffNotEmpty, run_benchmark


@pytest.mark.django_db
def test_warmup_samples_are_additional_and_are_not_recorded(owned_library):
    seed_library(owned_library, actor=owned_library.user, events=5, spares=7)
    timings = run_command_scenario(
        owned_library,
        actor=owned_library.user,
        games=spare_games(owned_library),
        iterations=5,
        warmup=2,
    )
    #: 7 dispatched, 5 recorded.
    assert timings.samples == 5
    assert PlayerGame.objects.filter(library=owned_library).count() == 12


@pytest.mark.django_db
def test_one_dispatch_writes_one_projection_row_through_one_statement(owned_library):
    seed_library(owned_library, actor=owned_library.user, events=0, spares=1)
    work = run_amplification_scenario(
        owned_library,
        actor=owned_library.user,
        games=spare_games(owned_library),
        iterations=1,
    )
    assert work.projection_rows == 1
    assert work.projection_statements == 1
    assert work.event_store_rows == 4


@pytest.mark.django_db
def test_folding_one_event_costs_six_statements(owned_library):
    """The number #930 exists to reduce."""
    seed_library(owned_library, actor=owned_library.user, events=10, spares=0)
    _, fold = run_rebuild_scenario(
        owned_library, mode=RebuildMode.REBUILD, count_fold=True
    )
    assert fold is not None
    assert fold.statements / fold.events == pytest.approx(6.0, abs=0.5)


@pytest.mark.django_db
def test_a_run_folds_the_events_both_write_paths_produced(owned_library):
    report = run_benchmark(seed=30, iterations=3, warmup=1, keep=True)
    #: 30 seeded, 3 + 1 by the command scenario, 3 by amplification.
    assert report.rebuild.folded_through == 37
    assert all(
        table.only_live == table.only_rebuilt == table.differing == 0
        for table in report.rebuild.tables
    )


@pytest.mark.django_db
def test_a_run_purges_its_scratch_user_after_a_scenario_raises(owned_library, monkeypatch):
    """Deleting the workload plug point left a monkeypatch as the only seam."""
    from games.events import benchmark as benchmark_module

    def explode(*args, **kwargs):
        raise RuntimeError("the scenario failed")

    monkeypatch.setattr(benchmark_module, "run_command_scenario", explode)
    before = set(User.objects.values_list("username", flat=True))
    with pytest.raises(RuntimeError, match="the scenario failed"):
        run_benchmark(seed=5, iterations=2, warmup=0)
    assert set(User.objects.values_list("username", flat=True)) == before


@pytest.mark.django_db
def test_no_count_fold_leaves_the_fold_unmeasured(owned_library):
    report = run_benchmark(seed=5, iterations=1, warmup=0, count_fold=False)
    assert report.fold is None
    assert report.rebuild is not None


@pytest.mark.django_db
def test_library_mode_writes_no_persistent_row(owned_library):
    seed_library(owned_library, actor=owned_library.user, events=6, spares=0)
    before = set(PlayerGame.objects.filter(library=owned_library).values_list("id", flat=True))
    head_before = LibraryEventStreamHead.objects.get(library=owned_library).sequence
    report = run_benchmark(seed=0, iterations=0, warmup=0, library=owned_library)
    assert report.seed is None
    assert report.command is None
    assert set(
        PlayerGame.objects.filter(library=owned_library).values_list("id", flat=True)
    ) == before
    assert LibraryEventStreamHead.objects.get(library=owned_library).sequence == head_before


@pytest.mark.django_db
def test_a_non_empty_rebuild_diff_fails_the_run(owned_library, monkeypatch):
    seed_library(owned_library, actor=owned_library.user, events=6, spares=0)
    #: A row the replay will not produce.
    PlayerGame.objects.create(
        id=uuid.uuid7(),
        library=owned_library,
        game=Game.objects.create(library=owned_library, name="Unfolded"),
        tracked_at=timezone.now(),
    )
    with pytest.raises(RebuildDiffNotEmpty):
        run_benchmark(seed=0, iterations=0, warmup=0, library=owned_library)


@pytest.mark.django_db
def test_the_report_carries_every_scenario_and_a_schema(owned_library):
    report = run_benchmark(seed=25, iterations=3, warmup=1)
    assert isinstance(report, BenchmarkReport)
    assert report.schema == 1
    assert report.seed is not None
    assert report.command is not None
    assert report.amplification is not None
    assert report.fold is not None
    assert report.teardown_seconds is not None
    parsed = json.loads(report.as_json())
    assert parsed["schema"] == 1
    assert set(parsed) >= {
        "environment", "seed", "command", "amplification", "fold", "rebuild",
        "teardown_seconds", "budgets",
    }
```

The stream head's sequence attribute name must match
`LibraryEventStreamHead`'s field — read it before writing this test and use the
real name.

- [ ] **Step 2: Run them to verify they fail**

```
make test ARGS="tests/test_event_benchmark.py" PYTEST_WORKERS=0
```

- [ ] **Step 3a: The scenarios, in `benchmark_workload.py`**

```python
from itertools import islice

from games.commands.playergame import TrackGame
from games.events.benchmark import StatementCounter, Timings, WorkPerEvent, summarize
from games.events.dispatch import dispatch
from games.events.rebuild import RebuildMode, RebuildReport, rebuild_projections


def _track(library: UserLibrary, *, actor: User, game: Game) -> None:
    dispatch(
        TrackGame(game_id=game.pk),
        actor=actor,
        library=library,
        idempotency_key=str(uuid.uuid7()),
    )


def run_command_scenario(
    library: UserLibrary,
    *,
    actor: User,
    games: Iterator[Game],
    iterations: int,
    warmup: int,
) -> Timings:
    """Dispatch against a library that already holds its seeded rows.

    TrackGame's duplicate check queries the projection, so measuring it
    against a full library is the measurement worth having. The warmup
    dispatches are additional to `iterations` and are discarded: the first
    one pays for connection setup and query planning no later one pays for.
    """
    for game in islice(games, warmup):
        _track(library, actor=actor, game=game)
    samples: list[Seconds] = []
    for game in islice(games, iterations):
        started = monotonic()
        _track(library, actor=actor, game=game)
        samples.append(monotonic() - started)
    return summarize(samples)


def run_amplification_scenario(
    library: UserLibrary, *, actor: User, games: Iterator[Game], iterations: int
) -> WorkPerEvent:
    """What one whole command costs: append, idempotency, and the fold.

    Counted in its own pass rather than during the command scenario, so the
    wrapper's per-statement cost stays out of the latency being gated.
    """
    counter = StatementCounter()
    dispatched = 0
    with connection.execute_wrapper(counter):
        for game in islice(games, iterations):
            _track(library, actor=actor, game=game)
            dispatched += 1
    return counter.work(events=dispatched)


def run_rebuild_scenario(
    library: UserLibrary, *, mode: RebuildMode, count_fold: bool
) -> tuple[RebuildReport, WorkPerEvent | None]:
    """Replay, diff, and -- in REBUILD mode -- swap.

    No CHECK pass runs first: a REBUILD already separates replay, diff and
    swap in its RebuildAttempt, and already diffs before swapping, so the
    second pass bought nothing and cost a third of the run.

    The counter is installed for the whole rebuild, so the gated time carries
    its own instrumentation. That makes a PASSED verdict conservative; pass
    count_fold=False to re-measure a verdict that lands inside the overhead.
    """
    if not count_fold:
        return rebuild_projections(library, mode=mode), None
    counter = StatementCounter()
    with connection.execute_wrapper(counter):
        report = rebuild_projections(library, mode=mode)
    return report, counter.work(events=report.folded_through)
```

Add `from django.db import connection, transaction` to the imports.

- [ ] **Step 3b: `run_benchmark`, in `benchmark.py`**

```python
class RebuildDiffNotEmpty(RuntimeError):
    """The parity claim the run exists to make is false."""


@dataclass(frozen=True, slots=True)
class BenchmarkReport:
    schema: int
    environment: Environment
    #: None in --library mode.
    seed: SeedReport | None
    command: Timings | None
    #: Per command: the whole write path.
    amplification: WorkPerEvent | None
    #: Per event: the fold alone.
    fold: WorkPerEvent | None
    rebuild: RebuildReport | None
    #: None when --keep was given.
    teardown_seconds: Seconds | None
    budgets: tuple[Budget, ...]

    def as_json(self) -> str:
        return json.dumps(asdict(self), indent=2, default=str)


REPORT_SCHEMA = 1


def run_benchmark(
    *,
    seed: int,
    iterations: int,
    warmup: int,
    library: UserLibrary | None = None,
    keep: bool = False,
    count_fold: bool = True,
) -> BenchmarkReport:
    """Seed a scratch library, measure it, and take it away again.

    With `library`, run the read-only rebuild scenario against one that
    already exists and ignore `seed`.
    """
    if library is not None:
        return _measure_existing(library, count_fold=count_fold)
    username = f"benchmark-{uuid.uuid7()}"
    user = User.objects.create_user(username=username)
    try:
        return _measure_scratch(
            user,
            seed=seed,
            iterations=iterations,
            warmup=warmup,
            count_fold=count_fold,
            keep=keep,
        )
    finally:
        if not keep:
            #: The report is already built; this time is stamped onto it
            #: by _measure_scratch, which owns the happy path.
            purge_scratch_user(username)
```

The `finally` above must not lose the teardown time on the happy path. Structure
it so the happy path purges and records, and the `finally` only catches the
failure case:

```python
    purged = False
    try:
        report = _measure_scratch(...)
        teardown = None if keep else purge_scratch_user(username)
        purged = True
        return replace(report, teardown_seconds=teardown)
    finally:
        if not purged and not keep:
            purge_scratch_user(username)
```

`_measure_scratch` runs the scenarios in order and builds the report:

```python
def _measure_scratch(
    user: User, *, seed: int, iterations: int, warmup: int, count_fold: bool, keep: bool
) -> BenchmarkReport:
    library = user.library
    spares = 2 * iterations + warmup
    seeded = seed_library(library, actor=user, events=seed, spares=spares)
    games = spare_games(library)
    command = run_command_scenario(
        library, actor=user, games=games, iterations=iterations, warmup=warmup
    )
    amplification = run_amplification_scenario(
        library, actor=user, games=games, iterations=iterations
    )
    rebuild, fold = run_rebuild_scenario(
        library, mode=RebuildMode.REBUILD, count_fold=count_fold
    )
    _refuse_a_diff(rebuild)
    return BenchmarkReport(
        schema=REPORT_SCHEMA,
        environment=environment(),
        seed=seeded,
        command=command,
        amplification=amplification,
        fold=fold,
        rebuild=rebuild,
        teardown_seconds=None,
        budgets=(command_budget(command), rebuild_budget(rebuild)),
    )
```

Note that `games` is one iterator shared by both command scenarios, so
`islice` advances it: the command scenario takes `warmup + iterations` rows and
amplification takes the next `iterations`. That is exactly the `2 * iterations +
warmup` spares seeded.

```python
def _measure_existing(library: UserLibrary, *, count_fold: bool) -> BenchmarkReport:
    rebuild, fold = run_rebuild_scenario(
        library, mode=RebuildMode.CHECK, count_fold=count_fold
    )
    _refuse_a_diff(rebuild)
    return BenchmarkReport(
        schema=REPORT_SCHEMA,
        environment=environment(),
        seed=None,
        command=None,
        amplification=None,
        fold=fold,
        rebuild=rebuild,
        teardown_seconds=None,
        budgets=(rebuild_budget(rebuild),),
    )


def _refuse_a_diff(report: RebuildReport) -> None:
    """A rebuild that is quick and wrong is not a passing benchmark."""
    drifted = sum(
        table.only_live + table.only_rebuilt + table.differing
        for table in report.tables
    )
    if drifted:
        raise RebuildDiffNotEmpty(
            f"{drifted} row(s) differ from the replay, so the parity this run "
            "exists to demonstrate does not hold. The timings above are real "
            "and the claim they support is not."
        )
```

- [ ] **Step 4: Run them to verify they pass**

```
make test ARGS="tests/test_event_benchmark.py" PYTEST_WORKERS=0
```

Expected: PASS. Two likely snags, both worth stopping over rather than working
around:

- `run_command_scenario` monkeypatched in `benchmark.py` requires `benchmark.py`
  to call it through the module attribute it imported. Import the names into
  `benchmark.py` normally; `monkeypatch.setattr(benchmark_module, "run_command_scenario", …)`
  then patches the binding `benchmark.py` actually calls.
- The `--library` mode test asserts no persistent write. If it fails because
  `CHECK` mode swapped, re-read `rebuild.py` — `CHECK` must not swap.

- [ ] **Step 5: Commit**

```bash
git add games/events/benchmark.py games/events/benchmark_workload.py tests/test_event_benchmark.py
git commit -m "Run the scenarios in the order the evidence needs"
```

---

### Task 9: The management command

**Files:**
- Create: `games/management/commands/benchmark_events.py`
- Test: `tests/test_event_benchmark.py`

**Interfaces:**
- Consumes: `run_benchmark`, `BenchmarkReport`, `BudgetVerdict`,
  `RebuildDiffNotEmpty`.
- Produces: `manage.py benchmark_events [--seed N] [--library UUID]
  [--iterations N] [--warmup N] [--gate] [--json] [--keep] [--no-count-fold]`.

Arguments and printing only; the decisions are in `benchmark.py`. Mirror
`games/management/commands/rebuild_projections.py` for structure and tone.

- [ ] **Step 1: Write the failing tests**

```python
def run_command(**options) -> str:
    output = StringIO()
    call_command("benchmark_events", stdout=output, **options)
    return output.getvalue()


@pytest.mark.django_db
def test_seed_and_library_together_are_refused(owned_library):
    with pytest.raises(CommandError, match="--seed and --library"):
        run_command(seed=10, library=str(owned_library.pk))


@pytest.mark.django_db
def test_an_unknown_library_is_named():
    with pytest.raises(CommandError, match="No library"):
        run_command(library=str(uuid.uuid7()))


@pytest.mark.django_db
def test_the_command_prints_what_it_will_create_before_creating_it():
    output = run_command(seed=25, iterations=2, warmup=1)
    assert "25" in output
    #: A three-minute default says so where it is read.
    assert "estimate" in output.lower()


@pytest.mark.django_db
def test_gate_raises_on_a_missed_budget(monkeypatch):
    monkeypatch.setattr(benchmark_module, "COMMAND_BUDGET_SECONDS", 0.0)
    with pytest.raises(CommandError, match="budget"):
        run_command(seed=2_500, iterations=25, warmup=1, gate=True)


@pytest.mark.django_db
def test_gate_is_silent_when_every_budget_passes():
    #: Below both floors: NOT_GATED is not MISSED.
    run_command(seed=25, iterations=2, warmup=1, gate=True)


@pytest.mark.django_db
def test_json_output_parses_and_carries_the_schema():
    parsed = json.loads(run_command(seed=25, iterations=2, warmup=1, json=True))
    assert parsed["schema"] == 1


@pytest.mark.django_db
def test_keep_leaves_the_user_and_prints_the_cleanup(monkeypatch):
    output = run_command(seed=10, iterations=1, warmup=0, keep=True)
    assert "delete_user_library" in output
    assert User.objects.filter(username__startswith="benchmark-").exists()
```

`--gate` uses `dest="gate"`, `--json` uses `dest="json"`, `--no-count-fold` uses
`dest="count_fold"` with `action="store_false"`.

- [ ] **Step 2: Run them to verify they fail**

```
make test ARGS="tests/test_event_benchmark.py -k command" PYTEST_WORKERS=0
```

Expected: FAIL, `Unknown command: 'benchmark_events'`.

- [ ] **Step 3: Write the command**

```python
"""Arguments and printing; the decisions are elsewhere."""

from uuid import UUID

from django.core.management.base import BaseCommand, CommandError
from django.db.utils import DatabaseError

from games.events.benchmark import (
    BenchmarkReport,
    Budget,
    BudgetVerdict,
    RebuildDiffNotEmpty,
    WorkPerEvent,
    run_benchmark,
)
from games.models import UserLibrary

#: Measured on the development machine; see docs/event-benchmarks.md.
SECONDS_PER_SEEDED_EVENT = 65 / 100_000
SECONDS_PER_REBUILT_EVENT = 59 / 100_000
SECONDS_PER_PURGED_EVENT = 52 / 100_000

CURSOR_UNDER_A_POOLER = (
    "The replay's server-side cursor did not survive. A transaction-pooling "
    "connection pooler closes it between statements, and "
    "DISABLE_SERVER_SIDE_CURSORS cannot be set yet -- that is issue #917. "
    "Point this at a direct connection, not the pooler."
)


class Command(BaseCommand):
    help = (
        "Measure command latency, rebuild time, and per-event write cost "
        "against the real TrackGame workload. Seeds a scratch library and "
        "removes it again, unless --library names one to check read-only. "
        "Exits non-zero on a rebuild diff, and -- with --gate -- on a missed "
        "budget."
    )

    def add_arguments(self, parser):
        parser.add_argument("--seed", type=int, default=100_000, help="Events to seed.")
        parser.add_argument("--library", help="Check this library instead; read-only.")
        parser.add_argument("--iterations", type=int, default=200)
        parser.add_argument("--warmup", type=int, default=10, help="Additional, discarded.")
        parser.add_argument("--gate", action="store_true", help="Exit non-zero on a missed budget.")
        parser.add_argument("--json", action="store_true", help="Print the report as JSON.")
        parser.add_argument("--keep", action="store_true", help="Leave the scratch library.")
        parser.add_argument(
            "--no-count-fold",
            dest="count_fold",
            action="store_false",
            help="Do not instrument the rebuild; use for a verdict inside the overhead.",
        )
```

`handle()`:

```python
    def handle(self, *args, **options):
        library = self._resolve_library(options)
        if library is None:
            self._write_estimate(options)
        try:
            report = run_benchmark(
                seed=options["seed"],
                iterations=options["iterations"],
                warmup=options["warmup"],
                library=library,
                keep=options["keep"],
                count_fold=options["count_fold"],
            )
        except RebuildDiffNotEmpty as error:
            raise CommandError(str(error)) from error
        except DatabaseError as error:
            if "cursor" in str(error).lower():
                raise CommandError(CURSOR_UNDER_A_POOLER) from error
            raise

        if options["json"]:
            self.stdout.write(report.as_json())
        else:
            self._write_report(report)
        if options["keep"]:
            self.stdout.write(
                "Kept. Remove it with: manage.py delete_user_library "
                f"--user {report.username} --confirm {report.username}"
            )
        if options["gate"]:
            self._gate(report)
```

`report.username` requires `BenchmarkReport` to carry the scratch username. Add
`scratch_username: str | None` to the dataclass in Task 8's module and set it —
`--keep` cannot print the cleanup invocation otherwise. Make this edit as part of
this task and re-run Task 8's tests.

`_resolve_library` refuses both flags and resolves the UUID, copying
`rebuild_projections._get_library`:

```python
    @staticmethod
    def _resolve_library(options) -> UserLibrary | None:
        raw_id = options["library"]
        if raw_id is None:
            return None
        #: --seed's default is not a choice the operator made.
        if options["seed"] != 100_000:
            raise CommandError("--seed and --library cannot both be given.")
        try:
            library_id = UUID(raw_id)
        except ValueError as error:
            raise CommandError(f"{raw_id!r} is not a library id.") from error
        try:
            return UserLibrary.objects.get(pk=library_id)
        except UserLibrary.DoesNotExist as error:
            raise CommandError(f"No library {library_id}.") from error
```

The default-sentinel comparison is fragile. Prefer `default=None` on `--seed` and
resolve the 100,000 default after the mutual-exclusion check:

```python
        if options["library"] is not None and options["seed"] is not None:
            raise CommandError("--seed and --library cannot both be given.")
        seed = 100_000 if options["seed"] is None else options["seed"]
```

Use this second form; it is honest about what the operator typed.

`_write_estimate` prints the scaled expectation before anything is created:

```python
    def _write_estimate(self, options) -> None:
        events = options["seed"]
        estimate = events * (
            SECONDS_PER_SEEDED_EVENT
            + SECONDS_PER_REBUILT_EVENT
            + SECONDS_PER_PURGED_EVENT
        )
        self.stdout.write(
            f"About to create a scratch user, {events} events and "
            f"{events + 2 * options['iterations'] + options['warmup']} catalog "
            f"rows, then remove them. Estimate: {estimate / 60:.1f} minute(s)."
        )
```

`_write_report` prints, in order: the environment, the seed (with
events-per-second, labelled an append measurement with no budget and a line
saying no bulk command exists to measure), the command timings, the two
`WorkPerEvent` blocks divided by their event counts, the rebuild's per-phase
timings and diff, the teardown, and the budgets. `_gate` raises `CommandError`
naming every `MISSED` budget and says nothing about `NOT_GATED` ones:

```python
    def _gate(self, report: BenchmarkReport) -> None:
        missed = [b for b in report.budgets if b.verdict is BudgetVerdict.MISSED]
        if not missed:
            return
        raise CommandError(
            "Missed budget(s): "
            + "; ".join(
                f"{b.name} {b.measured:.3f}{b.unit} over {b.limit:.3f}{b.unit}"
                for b in missed
            )
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

```
make test ARGS="tests/test_event_benchmark.py" PYTEST_WORKERS=0
```

- [ ] **Step 5: Commit**

```bash
git add games/management/commands/benchmark_events.py games/events/benchmark.py tests/test_event_benchmark.py
git commit -m "Print the measurement, and refuse a diff that makes it a lie"
```

---

### Task 10: The target, the run, and the record

**Files:**
- Modify: `Makefile` (beside `audit-uuid-identity`, around line 269)
- Create: `docs/event-benchmarks.md`

**Interfaces:**
- Consumes: everything above.
- Produces: `make bench`, and the recorded run.

`make bench` is **not** part of `make check`: CI is 4 vCPU, where a timing gate
produces a red build on a green machine, and a three-minute command has no
business in the gate.

- [ ] **Step 1: Add the Makefile target**

```make
# Usage: make bench ARGS="--seed 10000 --gate"
bench: ensure-postgres
	uv run --frozen python manage.py benchmark_events $(ARGS)
```

Place it directly after `audit-uuid-identity`. Do not add it to any aggregate.

- [ ] **Step 2: Verify the target runs at a small size**

```
make bench ARGS="--seed 2000 --iterations 25"
```

Expected: a printed report, an empty rebuild diff, a `PASSED` or `MISSED` rebuild
verdict (2,000 clears the floor), and `NOT_GATED` for the command p95 if fewer
than 20 samples were recorded — with 25 iterations it is gated.

- [ ] **Step 3: Run the full `make check` gate**

```
make check
```

Expected: green. This is the gate: lint, format-check, mypy, ts-check, vitest,
and the whole pytest suite **including `e2e/`**. Do not substitute `check-fast`
and do not narrow it with `ARGS`.

- [ ] **Step 4: Record one full run**

```
make bench ARGS="--gate"
```

This takes about three minutes and **is expected to report the rebuild budget as
met by a small margin or missed**. Either is a valid result. A `MISSED` verdict
within about 2% is inside the instrumentation's own cost; re-run it once with
`ARGS="--gate --no-count-fold"` and record both numbers.

Write `docs/event-benchmarks.md` containing:

- what the document is, and that it is regenerated by `make bench`, not edited;
- the `Environment` block verbatim — this is where the charter's "documented
  development machine" finally gets documented, since nothing in the repository
  defines it today;
- the full report output;
- the rebuild verdict, stated plainly, and if `MISSED`, a paragraph naming the
  charter's clause ("a phase may revise a number only with a recorded benchmark
  and an explicit design review") and #930 as the cheaper-fold lead;
- the empty rebuild diff, called out as the parity evidence #601 asks for, over
  events written by both `LockedStream.append` and `dispatch`;
- the seed's events-per-second, labelled an append measurement with no budget,
  with one line saying no bulk command exists to measure yet.

- [ ] **Step 5: Commit**

```bash
git add Makefile docs/event-benchmarks.md
git commit -m "Record what the machine actually does"
```

- [ ] **Step 6: Finish the branch**

**REQUIRED SUB-SKILL:** Use superpowers:finishing-a-development-branch.

---

## Self-Review

**Spec coverage.** Every section of the spec maps to a task: the workload and the
absence of a bulk scenario -> Task 6 and Task 10's document; the ownership
boundary -> nothing (it is a list of what is *not* built); preconditions ->
Tasks 6 and 8's imports; the three scenarios and their order -> Task 8; seeding ->
Task 6; teardown -> Task 7; timing and percentiles -> Tasks 2 and 8; the rebuild
as a parity proof -> Task 8's diff test and Task 10's record; the scaled budget
and its floors -> Task 5; cost per event -> Tasks 1 and 3; the pooled-connection
message -> Task 9; the API contract -> Tasks 2-8; where the behaviour is pinned ->
the test steps throughout; verification -> Task 10; reversibility -> nothing to
build.

**Two spec bullets deliberately not given their own task**, because they are
assertions inside tasks that already exist: "`--library` mode leaves every
persistent row untouched" is a Task 8 test, and "the rebuild budget scales on
`folded_through`" is a Task 5 test plus a Task 8 test.

**Known rough edges an implementer will hit**, called out rather than hidden:

- Task 8's shared `games` iterator is load-bearing. If the command scenario and
  the amplification scenario are given separate `spare_games()` calls, both start
  at the first spare and the second one dispatches against already-tracked games,
  which `TrackGame` refuses. One iterator, advanced by `islice`.
- Task 9's `--seed` default must be resolved *after* the mutual-exclusion check,
  or `--library` alone trips the check against its own default.
- Task 3's counter reads `context["cursor"].rowcount` after `execute` returns.
  Reading it before would report the previous statement's count.
- Task 8's `_refuse_a_diff` runs before the teardown, so a failing run still
  purges — that is what Task 8's monkeypatch test proves.
