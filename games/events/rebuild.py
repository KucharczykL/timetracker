"""Rebuild a library's projections into shadow tables, then swap them in.

One attempt is five phases: create an empty shadow table for every projection
table, replay the stream into a registry pointed at those tables, diff the
result against the live rows, swap under the stream lock, and drop the shadows
on every path. The sections below follow that order.

Everything here runs on **one connection** -- the default one. The shadow
tables are temp tables, so they live on the session that made them: a second
alias, or a `connection.close()` between phases, and the phase after it finds
nothing to write to.
"""

import re
import uuid
from collections.abc import Iterable, Iterator, Sequence
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass, replace
from enum import StrEnum
from time import monotonic
from typing import Any, cast

from django.apps import apps as global_apps
from django.apps.registry import Apps
from django.db import connection, transaction
from django.db.models.fields.generated import GeneratedField

from games.events.append import StreamSequenceMismatch, lock_stream
from games.events.replay import ReplayResult, replay
from games.events.targets import SHADOW_SUFFIX, ShadowTarget
from games.events.wiring import DEFAULT_WIRING, EventWiring
from games.models import LibraryEventStreamHead, ProjectionModel, UserLibrary

type ColumnName = str  # e.g. "library_id"
type TableName = str  # e.g. "games_playergamestate"


# --- Phase 1: which tables, and their shadows -------------------------------


def projection_models(apps: Apps = global_apps) -> tuple[type[ProjectionModel], ...]:
    """Every projection table in `apps`, in a stable order.

    Structural discovery: a table is a projection because it inherits
    `ProjectionModel`, not because a family remembered to list it. The
    registry is read rather than `ProjectionModel.__subclasses__()`, which
    sees only what has been imported and would make a rebuild's scope depend
    on import order.

    `apps` is a parameter because `isolate_apps` -- how this repo declares
    test-local models -- patches `Options.default_apps` and leaves the global
    registry untouched.
    """
    found = [
        model
        for model in apps.get_models()
        if issubclass(model, ProjectionModel) and model._meta.managed
    ]
    #: `get_models` includes the manufactured twins, which name a temp table
    #: and are nobody's projection table; `managed` is what excludes them.
    return tuple(sorted(found, key=lambda model: model._meta.db_table))


def shadow_table_name(model: type[ProjectionModel]) -> TableName:
    return f"{model._meta.db_table}{SHADOW_SUFFIX}"


@contextmanager
def shadow_tables(models: Iterable[type[ProjectionModel]]) -> Iterator[None]:
    """An empty twin of every table given, for the length of the block.

    Temp tables, so two libraries rebuild at once with no lock, no name
    collision and no reaper, and a crashed rebuild leaves nothing behind. They
    are dropped here anyway rather than left to the disconnect, because a
    persistent connection outlives one rebuild.

    `INCLUDING ALL` brings the defaults, the check constraints, the
    generated-column expressions and the indexes, and leaves the foreign keys
    behind.
    """
    pairs = [(model._meta.db_table, shadow_table_name(model)) for model in models]
    shadows = [shadow for _table, shadow in pairs]
    try:
        with connection.cursor() as cursor:
            for table, shadow in pairs:
                cursor.execute(
                    f"CREATE TEMP TABLE {connection.ops.quote_name(shadow)} "
                    f"(LIKE {connection.ops.quote_name(table)} INCLUDING ALL)"
                )
        yield
    finally:
        with connection.cursor() as cursor:
            for shadow in shadows:
                cursor.execute(
                    f"DROP TABLE IF EXISTS {connection.ops.quote_name(shadow)}"
                )


def insertable_columns(model: type[ProjectionModel]) -> tuple[ColumnName, ...]:
    """Every column the swap can hand to an `INSERT`, in table order.

    A generated column is refused by PostgreSQL -- "cannot insert a
    non-DEFAULT value" -- and recomputes identically from the columns that
    are carried, so leaving it out is both required and free.
    """
    return tuple(
        #: `column` is typed optional because a field has none until it joins a
        #: model; every field here came off one.
        cast("ColumnName", field.column)
        for field in model._meta.concrete_fields
        if not isinstance(field, GeneratedField)
    )


# --- The write guard --------------------------------------------------------


class LiveWriteRefused(RuntimeError):
    """A statement wrote something other than a shadow table.

    Raised out of whatever the family was doing, on the statement, so nothing
    is written and the traceback points at the line that tried.
    """


#: A statement opening with one of these writes something.
_WRITE_KEYWORDS = frozenset({"INSERT", "UPDATE", "DELETE", "COPY", "TRUNCATE", "MERGE"})

#: The identifier a write statement names first, which is the table it writes.
#: Reading the target out of the statement text is not parsing SQL, and is
#: stated as a limit rather than papered over: a family reaching a second
#: connection or a psycopg handle of its own is not covered either.
_WRITE_TARGET = re.compile(
    r"""
    ^\s*
    (?: INSERT \s+ INTO
      | UPDATE
      | DELETE \s+ FROM
      | TRUNCATE (?: \s+ TABLE )?
      | COPY
      | MERGE \s+ INTO
    )
    \s+
    (?P<table> [^\s(]+ )
    """,
    re.IGNORECASE | re.VERBOSE,
)


def only_shadow_writes() -> AbstractContextManager[None]:
    """Refuse every write on this connection that is not to a shadow table.

    Armed for the length of the replay phase, which is when a rebuild is
    supposed to be invisible.

    Signals were the obvious mechanism and they do not work: a `pre_save`
    receiver sees `save()` and `create()` and misses `bulk_create`,
    `QuerySet.update`, `bulk_update` and raw SQL -- precisely how a family
    projecting a stream writes rows. `execute_wrapper` is Django's hook around
    every statement on a connection, so it sees all of them, in their final SQL.

    The rule is an allowlist rather than a list of the tables being rebuilt,
    which is what makes "check mode writes nothing" true by construction. It
    also catches the side effect nobody would have listed -- a family bumping a
    counter row, filling a cache table, or recording an audit row outside its
    target -- which on a discarded attempt would otherwise commit and stay.

    Reads are untouched: the phase after this one reads live rows, and a family
    may read whatever it likes.
    """
    return connection.execute_wrapper(_refuse_a_live_write)


def _refuse_a_live_write(
    execute: Any, sql: str, params: Any, many: bool, context: Any
) -> Any:
    target = _write_target(sql)
    if target is not None and not target.endswith(SHADOW_SUFFIX):
        raise LiveWriteRefused(
            f"This statement writes {target!r}, which is not a shadow table. A "
            "rebuild writes nothing but its own shadow copies, so a family that "
            "reaches a live table is stopped on the statement rather than after "
            f"it commits: {sql[:200]}"
        )
    return execute(sql, params, many, context)


def _write_target(statement: str) -> TableName | None:
    """The table a statement writes, or `None` if it writes nothing.

    A write whose target cannot be read comes back as the empty string, which
    ends with no shadow suffix and so is refused: an unrecognised write is the
    case where guessing wrong is expensive.
    """
    stripped = statement.lstrip()
    keyword = stripped.split(maxsplit=1)[0] if stripped else ""
    if keyword.upper() not in _WRITE_KEYWORDS:
        return None
    match = _WRITE_TARGET.match(stripped)
    if match is None:
        return ""
    return _bare_name(match["table"])


def _bare_name(identifier: str) -> TableName:
    """`pg_temp."games_x__shadow"` -> `games_x__shadow`."""
    return identifier.rsplit(".", maxsplit=1)[-1].strip('"').rstrip(";")


# --- Phase 2: the replay ----------------------------------------------------


def replay_into_shadow(
    library: UserLibrary,
    models: Iterable[type[ProjectionModel]],
    *,
    wiring: EventWiring = DEFAULT_WIRING,
) -> ReplayResult:
    """Fold the library's stream into the shadow tables the caller created.

    The same families over the same events, pointed elsewhere -- there is no
    second fold loop, because a rebuilt projection is only equal to the one the
    write path produced if the same code wrote both.

    One transaction, which #666's replay deliberately does not open for itself:
    in autocommit every shadow row would be its own commit, and the shadow is
    private and dropped on every path, so the wrap discards nothing a rollback
    would have kept. It also turns the replay's cursor from `WITH HOLD` into an
    ordinary one.

    The head read at the start bounds the fold, and comes back as
    `folded_through` -- the sequence the swap will assert the stream is still
    at. An event appended while this runs sits above that bound and belongs to
    a later replay.

    Everything the replay refuses, this refuses with it: `StreamNotContiguous`,
    `PayloadVersionUnsupported`, and a family's own exception carrying the note
    naming the family, the event type and the sequence.
    """
    tables = list(models)
    _require_shadow_tables(tables)
    shadow_wiring = replace(
        wiring, projectors=wiring.projectors.for_target(ShadowTarget())
    )
    with transaction.atomic(), only_shadow_writes():
        return replay(library, wiring=shadow_wiring)


def _require_shadow_tables(models: Sequence[type[ProjectionModel]]) -> None:
    expected = [shadow_table_name(model) for model in models]
    if not expected:
        return
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT name FROM unnest(%s::text[]) AS name
            WHERE to_regclass(quote_ident(name)) IS NULL
            """,
            [expected],
        )
        missing = [name for (name,) in cursor.fetchall()]
    if missing:
        raise RuntimeError(
            f"This replay has no shadow table to write: {', '.join(missing)}. "
            "Phase 2 writes tables phase 1 created on this connection, so a "
            "caller that skipped `shadow_tables` -- or closed the connection "
            "between the phases -- reaches here rather than a family's first "
            "insert."
        )


# --- Phase 3: the diff ------------------------------------------------------

#: How many keys a table's diff carries out. Enough to act on, bounded so a
#: wholly-drifted table cannot produce a report nobody can read.
DIFF_SAMPLE_LIMIT = 20


@dataclass(frozen=True, slots=True)
class TableDiff:
    """One projection table's live rows against the rebuilt ones.

    Both row counts are carried rather than one difference, because "1000 live,
    0 rebuilt" and "1000 live, 999 rebuilt" are different situations and a
    single number tells them apart only by arithmetic nobody does under
    pressure.
    """

    table: TableName
    live_rows: int
    rebuilt_rows: int
    #: Rows the rebuild did not produce.
    only_live: int
    #: Rows the live table has lost.
    only_rebuilt: int
    #: Rows present on both sides whose columns disagree.
    differing: int
    #: The primary keys of the rows above, truncated to DIFF_SAMPLE_LIMIT.
    sample: tuple[str, ...]


#: The counts and the sample in one pass. Two spellings here are load-bearing
#: and were probed:
#:
#: - the comparison is whole-row `IS DISTINCT FROM`, which is composite
#:   comparison and null-safe. The row-constructor form
#:   `ROW(live.a, ...) <> ROW(shadow.a, ...)` returns NULL when either side
#:   holds a NULL and the row is silently dropped, so a column that drifted to
#:   or from NULL would be reported as matching.
#: - the per-library scope sits in a subquery on the live side. In `WHERE` it
#:   degrades the outer join to an inner one and hides the rebuilt-only rows.
#: - the sample's `ORDER BY` repeats the expression. Inside an aggregate a
#:   number is an ordinary constant rather than an output-column reference, so
#:   `ORDER BY 1` would sort by nothing and hand back an arbitrary sample.
_DIFF = """
SELECT
    count(live.{pk}) AS live_rows,
    count(shadow.{pk}) AS rebuilt_rows,
    count(*) FILTER (WHERE shadow.{pk} IS NULL) AS only_live,
    count(*) FILTER (WHERE live.{pk} IS NULL) AS only_rebuilt,
    count(*) FILTER (
        WHERE live.{pk} IS NOT NULL AND shadow.{pk} IS NOT NULL
          AND (live.*) IS DISTINCT FROM (shadow.*)
    ) AS differing,
    (
        array_agg(
            coalesce(live.{pk}, shadow.{pk})::text
            ORDER BY coalesce(live.{pk}, shadow.{pk})::text
        )
        FILTER (
            WHERE live.{pk} IS NULL OR shadow.{pk} IS NULL
               OR (live.*) IS DISTINCT FROM (shadow.*)
        )
    )[1:%s::int] AS sample
FROM (SELECT * FROM {table} WHERE library_id = %s) AS live
FULL OUTER JOIN {shadow} AS shadow ON live.{pk} = shadow.{pk}
"""


def _primary_key_column(model: type[ProjectionModel]) -> ColumnName:
    """The column the two sides are joined on.

    Both annotations in the way are optional for reasons a concrete projection
    model is past: `Options.pk` because a model has none until its fields are
    assembled, `Field.column` because a field has none until it joins a model.
    """
    return cast("ColumnName", cast("Any", model._meta.pk).column)


def diff_table(model: type[ProjectionModel], library: UserLibrary) -> TableDiff:
    """One table's rebuilt rows against the library's live ones.

    The shadow needs no scope of its own: a rebuild replays one library, so
    every row in it belongs to that library.
    """
    statement = _DIFF.format(
        pk=connection.ops.quote_name(_primary_key_column(model)),
        table=connection.ops.quote_name(model._meta.db_table),
        shadow=connection.ops.quote_name(shadow_table_name(model)),
    )
    with connection.cursor() as cursor:
        cursor.execute(statement, [DIFF_SAMPLE_LIMIT, library.pk])
        live_rows, rebuilt_rows, only_live, only_rebuilt, differing, sample = (
            cursor.fetchone()
        )
    return TableDiff(
        table=model._meta.db_table,
        live_rows=live_rows,
        rebuilt_rows=rebuilt_rows,
        only_live=only_live,
        only_rebuilt=only_rebuilt,
        differing=differing,
        sample=tuple(sample or ()),
    )


def diff_tables(
    models: Iterable[type[ProjectionModel]], library: UserLibrary
) -> tuple[TableDiff, ...]:
    return tuple(diff_table(model, library) for model in models)


# --- Phase 4: the swap ------------------------------------------------------

_DELETE_LIVE_ROWS = 'DELETE FROM {table} WHERE "library_id" = %s'
_INSERT_REBUILT_ROWS = "INSERT INTO {table} ({columns}) SELECT {columns} FROM {shadow}"


def swap_in(
    library: UserLibrary,
    models: Iterable[type[ProjectionModel]],
    folded_through: int,
) -> None:
    """Put the rebuilt rows in place of this library's live ones.

    The lock pauses writes for this library and no other, and
    `require_sequence` runs before any statement that writes: an event that
    landed while the rebuild worked leaves the shadow a projection of a prefix,
    so the swap refuses with `StreamSequenceMismatch` having written nothing and
    the attempt is redone from a fresh shadow.

    Raw DML rather than `QuerySet.delete()`, which collects the objects, walks
    the cascades and fires a signal per object -- all of it wrong for replacing
    a table's contents, and all of it proportional to the rows.

    The tables are swapped in the order given and the order does not matter:
    every foreign key Django's schema editor emits is `DEFERRABLE INITIALLY
    DEFERRED`, so a reference that is briefly dangling mid-swap is checked at
    `COMMIT`, by which time every table has been refilled.
    """
    with transaction.atomic():
        stream = lock_stream(library)
        stream.require_sequence(folded_through)
        with connection.cursor() as cursor:
            for model in models:
                table = connection.ops.quote_name(model._meta.db_table)
                columns = ", ".join(
                    connection.ops.quote_name(column)
                    for column in insertable_columns(model)
                )
                cursor.execute(_DELETE_LIVE_ROWS.format(table=table), [library.pk])
                cursor.execute(
                    _INSERT_REBUILT_ROWS.format(
                        table=table,
                        columns=columns,
                        shadow=connection.ops.quote_name(shadow_table_name(model)),
                    )
                )


# --- The attempt loop and the report ----------------------------------------


class RebuildMode(StrEnum):
    """What an invocation is allowed to do with what it finds."""

    #: Replay and diff, take no lock, write nothing.
    CHECK = "check"
    #: Replay, diff, and swap regardless of the diff -- drift is the reason a
    #: rebuild is being run, so refusing on it would refuse the case the tool
    #: exists for.
    REBUILD = "rebuild"


@dataclass(frozen=True, slots=True)
class RebuildAttempt:
    """One pass through the phases, timed, and how it ended."""

    folded_through: int
    replay_seconds: float
    diff_seconds: float
    #: None when the attempt did not reach the swap: check mode, or a conflict.
    swap_seconds: float | None
    #: The conflict that sent the attempt back, as its message.
    conflict: str | None


@dataclass(frozen=True, slots=True)
class RebuildReport:
    """What an operator reads, and what every test asserts on."""

    library_id: uuid.UUID
    #: None when the library never appended and nothing provisioned a stream --
    #: which `check` never does and a `rebuild` always does, through the lock.
    stream_id: uuid.UUID | None
    mode: RebuildMode
    swapped: bool
    folded_through: int
    #: The head when the diff ran. In check mode a difference from
    #: `folded_through` means an event landed mid-check and the diff is
    #: advisory; in rebuild mode the same race is a redo instead.
    head_at_diff: int
    tables: tuple[TableDiff, ...]
    attempts: tuple[RebuildAttempt, ...]
    elapsed_seconds: float


@dataclass(frozen=True, slots=True)
class _StagedRebuild:
    """One attempt's shadow, folded and diffed, before anything is swapped.

    A value rather than five locals so the two things built from it -- the
    attempt and the report -- are built the same way at each of the loop's
    exits, and so neither is a closure over a loop variable.
    """

    replayed: ReplayResult
    replay_seconds: float
    tables: tuple[TableDiff, ...]
    diff_seconds: float
    head_at_diff: int

    def attempt(
        self, *, swap_seconds: float | None, conflict: str | None
    ) -> RebuildAttempt:
        return RebuildAttempt(
            folded_through=self.replayed.folded_through,
            replay_seconds=self.replay_seconds,
            diff_seconds=self.diff_seconds,
            swap_seconds=swap_seconds,
            conflict=conflict,
        )

    def report(
        self,
        *,
        library: UserLibrary,
        mode: RebuildMode,
        swapped: bool,
        stream_id: uuid.UUID | None,
        attempts: Sequence[RebuildAttempt],
        elapsed_seconds: float,
    ) -> RebuildReport:
        return RebuildReport(
            library_id=library.pk,
            stream_id=stream_id,
            mode=mode,
            swapped=swapped,
            folded_through=self.replayed.folded_through,
            head_at_diff=self.head_at_diff,
            tables=self.tables,
            attempts=tuple(attempts),
            elapsed_seconds=elapsed_seconds,
        )


def _stage(
    library: UserLibrary,
    models: Sequence[type[ProjectionModel]],
    wiring: EventWiring,
) -> _StagedRebuild:
    """Phases 2 and 3, timed, inside shadow tables the caller has created."""
    replay_started = monotonic()
    replayed = replay_into_shadow(library, models, wiring=wiring)
    replay_seconds = monotonic() - replay_started

    diff_started = monotonic()
    tables = diff_tables(models, library)
    diff_seconds = monotonic() - diff_started

    #: After the diff, so a check mode report can say whether an event landed
    #: while it ran. The rebuild path asserts the same number under the lock.
    _, head_at_diff = _stream_head(library)
    return _StagedRebuild(
        replayed=replayed,
        replay_seconds=replay_seconds,
        tables=tables,
        diff_seconds=diff_seconds,
        head_at_diff=head_at_diff,
    )


def rebuild_projections(
    library: UserLibrary,
    *,
    mode: RebuildMode = RebuildMode.CHECK,
    wiring: EventWiring = DEFAULT_WIRING,
    apps: Apps = global_apps,
) -> RebuildReport:
    """Rebuild one library's projections, or report what a rebuild would change.

    Checking is the default: an invocation that writes is the one that says so.

    A `StreamSequenceMismatch` redoes the whole attempt -- fresh shadow, fresh
    replay, fresh expectation -- because what went stale is the expectation, and
    a shadow folded from a prefix of the stream is not a thing to swap in.
    `run_in_transaction` is not the loop for this: it classifies on SQLSTATE and
    would decline this exception, correctly, since what needs redoing is the
    replay outside the transaction rather than the transaction.

    Everything else propagates on the first attempt: a hole in the stream, a
    payload no schema can read, and a family's own exception are none of them
    fixed by folding the same events again.
    """
    models = projection_models(apps)
    policy = wiring.retry_policy
    attempts: list[RebuildAttempt] = []
    started = monotonic()

    for attempt_number in range(policy.retries + 1):
        with shadow_tables(models):
            staged = _stage(library, models, wiring)
            stream_id = staged.replayed.stream_id

            if mode is RebuildMode.CHECK:
                attempts.append(staged.attempt(swap_seconds=None, conflict=None))
                return staged.report(
                    library=library,
                    mode=mode,
                    swapped=False,
                    stream_id=stream_id,
                    attempts=attempts,
                    elapsed_seconds=monotonic() - started,
                )

            swap_started = monotonic()
            try:
                swap_in(library, models, staged.replayed.folded_through)
            except StreamSequenceMismatch as conflict:
                attempts.append(
                    staged.attempt(swap_seconds=None, conflict=str(conflict))
                )
                if attempt_number == policy.retries:
                    return staged.report(
                        library=library,
                        mode=mode,
                        swapped=False,
                        stream_id=stream_id,
                        attempts=attempts,
                        elapsed_seconds=monotonic() - started,
                    )
            else:
                attempts.append(
                    staged.attempt(
                        swap_seconds=monotonic() - swap_started, conflict=None
                    )
                )
                if stream_id is None:
                    #: The lock provisions the head a never-appended library has
                    #: none of, so by here there is a real stream to name.
                    stream_id, _ = _stream_head(library)
                return staged.report(
                    library=library,
                    mode=mode,
                    swapped=True,
                    stream_id=stream_id,
                    attempts=attempts,
                    elapsed_seconds=monotonic() - started,
                )

        #: Outside the shadow block: the tables this attempt staged are dropped
        #: before the next one recreates them, and nothing is held over the wait.
        policy.sleep(policy.delay_for(attempt_number))

    raise AssertionError("The loop returns on its last attempt, conflict or not.")


def _stream_head(library: UserLibrary) -> tuple[uuid.UUID | None, int]:
    """The library's stream and how far it has advanced, or `(None, 0)`."""
    head = (
        LibraryEventStreamHead.objects.filter(library=library)
        .values_list("id", "current_sequence")
        .first()
    )
    return head if head is not None else (None, 0)
