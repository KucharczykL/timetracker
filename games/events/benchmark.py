"""The vocabulary, and the charter's numbers."""

import json
import math
import os
import platform as platform_module
from collections.abc import Container, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

from django.conf import settings
from django.db import connection

from games.events.rebuild import (
    RebuildReport,
    TableName,
    projection_models,
    write_targets,
)
from games.events.targets import SHADOW_SUFFIX
from games.models import (
    LibraryEvent,
    LibraryEventReference,
    LibraryEventStreamHead,
    LibraryIdempotencyRecord,
)

#: A wall-clock interval, from time.monotonic().
type Seconds = float

#: The four tables outside the projections.
EVENT_STORE_TABLES: frozenset[TableName] = frozenset(
    model._meta.db_table
    for model in (
        LibraryEvent,
        LibraryEventReference,
        LibraryEventStreamHead,
        LibraryIdempotencyRecord,
    )
)


@dataclass(frozen=True, slots=True)
class Timings:
    """One scenario's latency distribution."""

    samples: int
    p50: Seconds
    p95: Seconds
    maximum: Seconds


def nearest_rank(samples: Sequence[Seconds], percentile: int) -> Seconds:
    """The observation at `percentile`, never between two.

    `statistics.quantiles` interpolates, which invents a latency nothing
    measured. A budget is a claim about observations.
    """
    if not samples:
        raise ValueError("A percentile needs at least one sample.")
    ordered = sorted(samples)
    index = math.ceil(percentile / 100 * len(ordered)) - 1
    return ordered[max(index, 0)]


def summarize(samples: Sequence[Seconds]) -> Timings:
    """Three numbers; the mean hides the tail."""
    return Timings(
        samples=len(samples),
        p50=nearest_rank(samples, 50),
        p95=nearest_rank(samples, 95),
        maximum=max(samples),
    )


@dataclass(frozen=True, slots=True)
class WorkPerEvent:
    """What one event cost: rows and statements."""

    events: int
    #: Every statement in the window, savepoints included.
    statements: int
    rows_per_table: Mapping[TableName, int]
    #: Only statements that name a table.
    statements_per_table: Mapping[TableName, int]
    projection_rows: int
    projection_statements: int
    event_store_rows: int
    event_store_statements: int


@dataclass(slots=True)
class StatementCounter:
    """Every statement, and the rows writes touched.

    Counting statements rather than diffing COUNT(*) is what makes an update
    visible: a family that rewrites one row an event amplifies by one, and a
    before-and-after count reports zero. The total matters as much as the
    per-table breakdown, because a statement that names no table -- a
    savepoint, a lock, a transaction control -- is absent from the breakdown
    and present in the cost.

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
            #: Unparseable; the guard refuses, we skip.
            if not table:
                continue
            self.statements_per_table[table] = (
                self.statements_per_table.get(table, 0) + 1
            )
            if rowcount > 0:
                self.rows_per_table[table] = (
                    self.rows_per_table.get(table, 0) + rowcount
                )
        return result

    def work(self, *, events: int) -> WorkPerEvent:
        """Freeze the totals, classified by owner."""
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
        #: A shadow write is its projection's cost.
        return sum(
            count
            for table, count in counts.items()
            if table.removesuffix(SHADOW_SUFFIX) in tables
        )


@dataclass(frozen=True, slots=True)
class Environment:
    """The machine a number belongs to."""

    platform: str
    #: Empty on Linux, where processor() says nothing.
    processor: str
    cpu_count: int
    #: None where the platform declines.
    total_memory_bytes: int | None
    python_version: str
    postgresql_version: str
    shared_buffers: str
    work_mem: str
    debug: bool


def environment() -> Environment:
    """What is needed to reproduce a number."""
    with connection.cursor() as cursor:
        settings_read = {}
        for name in ("server_version", "shared_buffers", "work_mem"):
            #: SHOW takes no parameter; these are literals.
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
    except AttributeError, ValueError, OSError:
        #: Windows, and any POSIX that declines.
        return None


#: The charter's numbers. Nowhere else.
COMMAND_BUDGET_SECONDS: Seconds = 0.100
REBUILD_BUDGET_SECONDS: Seconds = 60.0
REBUILD_BUDGET_EVENTS = 100_000

#: Scaling is verified linear from here up.
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
    """The charter's 100 ms at p95."""
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


def one_pass_seconds(report: RebuildReport) -> Seconds:
    """The last attempt's phases, not every retry.

    A budget of 60 seconds per rebuild is a claim about one pass.
    `elapsed_seconds` sums the retries, and charging a rebuild three
    contended passes fails one that met the budget three times.
    """
    if not report.attempts:
        return report.elapsed_seconds
    last = report.attempts[-1]
    return last.replay_seconds + last.diff_seconds + (last.swap_seconds or 0.0)


def rebuild_budget(report: RebuildReport) -> Budget:
    """60 s per 100,000 events, scaled."""
    events = report.folded_through
    limit = REBUILD_BUDGET_SECONDS * events / REBUILD_BUDGET_EVENTS
    measured = one_pass_seconds(report)
    return Budget(
        name="rebuild",
        limit=limit,
        unit="s",
        measured=measured,
        verdict=_verdict(
            measured=measured,
            limit=limit,
            gated=events >= MINIMUM_GATED_EVENTS,
        ),
    )


@dataclass(frozen=True, slots=True)
class SeedReport:
    """Setup, timed apart from the measurement."""

    catalog_rows: int
    catalog_seconds: Seconds
    events: int
    append_seconds: Seconds
    #: The bulk-write number; no bulk command exists.
    events_per_second: float


class RebuildDiffNotEmpty(RuntimeError):
    """The run's parity claim is false."""


REPORT_SCHEMA = 1


@dataclass(frozen=True, slots=True)
class BenchmarkReport:
    schema: int
    environment: Environment
    #: None in --library mode; --keep prints it.
    scratch_username: str | None
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
