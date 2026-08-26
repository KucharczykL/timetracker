"""What a command costs, what a rebuild costs, and what one event costs.

The charter fixes two numbers -- 100 ms at p95 for an ordinary command, 60
seconds for a 100,000-event rebuild -- and asks that write amplification be
recorded after every new projector family without fixing a limit for it. This
module measures all three against the real workload, and this module is the
only place those numbers are written down.

It names things and decides things; it never does work. Nothing here imports
benchmark_workload or benchmark_run, and that is what keeps the three modules
acyclic.
"""

import math
from collections.abc import Container, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from games.events.rebuild import TableName, projection_models, write_targets
from games.events.targets import SHADOW_SUFFIX
from games.models import (
    LibraryEvent,
    LibraryEventReference,
    LibraryEventStreamHead,
    LibraryIdempotencyRecord,
)

#: A wall-clock interval, from time.monotonic().
type Seconds = float

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


@dataclass(frozen=True, slots=True)
class WorkPerEvent:
    """What one event cost, in rows and in statements."""

    events: int
    #: Every statement in the window, savepoints included.
    statements: int
    rows_per_table: Mapping[TableName, int]
    #: Only statements that name a table they write; shadow names kept raw.
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
                self.rows_per_table[table] = (
                    self.rows_per_table.get(table, 0) + rowcount
                )
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
        #: A replay writes games_x__shadow, which is games_x's cost.
        return sum(
            count
            for table, count in counts.items()
            if table.removesuffix(SHADOW_SUFFIX) in tables
        )
