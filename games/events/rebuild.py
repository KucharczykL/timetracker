"""Rebuild projections into shadow tables, then swap."""

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
    """Every projection table in `apps`, sorted."""
    found = [
        model
        for model in apps.get_models()
        if issubclass(model, ProjectionModel) and model._meta.managed
    ]
    #: `managed` is what excludes the manufactured twins.
    return tuple(sorted(found, key=lambda model: model._meta.db_table))


def shadow_table_name(model: type[ProjectionModel]) -> TableName:
    return f"{model._meta.db_table}{SHADOW_SUFFIX}"


@contextmanager
def shadow_tables(models: Iterable[type[ProjectionModel]]) -> Iterator[None]:
    """An empty temp twin per table, block-scoped."""
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
    """Every column an `INSERT` can carry."""
    return tuple(
        #: A model's field always has a column.
        cast("ColumnName", field.column)
        for field in model._meta.concrete_fields
        if not isinstance(field, GeneratedField)
    )


# --- The write guard --------------------------------------------------------


class LiveWriteRefused(RuntimeError):
    """A statement wrote outside the shadow tables."""


#: A statement opening with these writes.
_WRITE_KEYWORDS = frozenset({"INSERT", "UPDATE", "DELETE", "COPY", "TRUNCATE", "MERGE"})

#: A CTE hides its writes behind the first keyword.
_CTE_KEYWORD = "WITH"

#: Leading comments hide the first keyword too.
_LEADING_COMMENTS = re.compile(r"^\s*(?:/\*.*?\*/|--[^\n]*(?:\n|$))+", re.DOTALL)

#: The first identifier: the table written.
_WRITE_TARGET = re.compile(
    r"""
    \b
    (?: INSERT \s+ INTO
      | UPDATE
      | DELETE \s+ FROM
      | TRUNCATE (?: \s+ TABLE )?
      | COPY
      | MERGE \s+ INTO
    )
    \s+ (?: ONLY \s+ )?
    (?P<table> [^\s(]+ )
    """,
    re.IGNORECASE | re.VERBOSE,
)


def only_shadow_writes() -> AbstractContextManager[None]:
    """Refuse every write outside a shadow table."""
    return connection.execute_wrapper(_refuse_a_live_write)


def _refuse_a_live_write(
    execute: Any, sql: str, params: Any, many: bool, context: Any
) -> Any:
    for target in write_targets(sql):
        if not target.endswith(SHADOW_SUFFIX):
            raise LiveWriteRefused(
                f"This statement writes {target!r}, which is not a shadow table. "
                "A rebuild writes nothing but its own shadow copies, so a family "
                "that reaches a live table is stopped on the statement rather "
                f"than after it commits: {sql[:200]}"
            )
    return execute(sql, params, many, context)


def write_targets(statement: str) -> tuple[TableName, ...]:
    """Every table written; unreadable means refused.

    Public because the benchmark counts the same statements this guard
    refuses, and two regexes for one job would drift.
    """
    stripped = _LEADING_COMMENTS.sub("", statement).lstrip()
    keyword = stripped.split(maxsplit=1)[0].upper() if stripped else ""
    if keyword == _CTE_KEYWORD:
        #: A CTE writes any number of tables, or none.
        return tuple(
            _bare_name(match["table"]) for match in _WRITE_TARGET.finditer(stripped)
        )
    if keyword not in _WRITE_KEYWORDS:
        return ()
    match = _WRITE_TARGET.match(stripped)
    if match is None:
        return ("",)
    return (_bare_name(match["table"]),)


def _bare_name(identifier: str) -> TableName:
    """`pg_temp."games_x__shadow";` -> `games_x__shadow`."""
    return identifier.rsplit(".", maxsplit=1)[-1].rstrip(";").strip('"')


# --- Phase 2: the replay ----------------------------------------------------


def replay_into_shadow(
    library: UserLibrary,
    models: Iterable[type[ProjectionModel]],
    *,
    wiring: EventWiring = DEFAULT_WIRING,
) -> ReplayResult:
    """Replay the stream into the shadow tables."""
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

#: How many keys a table's diff carries.
DIFF_SAMPLE_LIMIT = 20


@dataclass(frozen=True, slots=True)
class TableDiff:
    """One table's live rows against the rebuilt."""

    table: TableName
    live_rows: int
    rebuilt_rows: int
    #: Rows the rebuild did not produce.
    only_live: int
    #: Rows the live table has lost.
    only_rebuilt: int
    #: Rows on both sides that disagree.
    differing: int
    #: Those rows' keys, bounded.
    sample: tuple[str, ...]


#: Three spellings are necessary.
#: `(live.*) IS DISTINCT FROM (shadow.*)` compares full rows and is null-safe.
#: `ROW(...) <> ROW(...)` gives NULL when a column is NULL.
#: The library scope stays in the subquery. A `WHERE` clause removes the rows
#: that only the shadow table has.
#: In the aggregate, `ORDER BY 1` is the constant 1, not the first column.
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
    """The join column, past two optional annotations."""
    return cast("ColumnName", cast("Any", model._meta.pk).column)


def diff_table(model: type[ProjectionModel], library: UserLibrary) -> TableDiff:
    """One table's rebuilt rows against live."""
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
#: Scoped like the delete: the lock covers one library.
_INSERT_REBUILT_ROWS = (
    "INSERT INTO {table} ({columns}) "
    'SELECT {columns} FROM {shadow} WHERE "library_id" = %s'
)


def swap_in(
    library: UserLibrary,
    models: Iterable[type[ProjectionModel]],
    replayed_through: int,
) -> None:
    """Put the rebuilt rows in place."""
    with transaction.atomic():
        stream = lock_stream(library)
        stream.require_sequence(replayed_through)
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
                    ),
                    [library.pk],
                )


# --- The attempt loop and the report ----------------------------------------


class RebuildMode(StrEnum):
    """What an invocation may do."""

    #: Replay and diff, take no lock.
    CHECK = "check"
    #: Replay, diff, and swap regardless.
    REBUILD = "rebuild"


@dataclass(frozen=True, slots=True)
class RebuildAttempt:
    """One pass through the phases, timed."""

    replayed_through: int
    replay_seconds: float
    diff_seconds: float
    #: None when the swap was not reached.
    swap_seconds: float | None
    #: The conflict message, if there was one.
    conflict: str | None


@dataclass(frozen=True, slots=True)
class RebuildReport:
    """What an operator reads."""

    library_id: uuid.UUID
    #: None until something provisions a stream.
    stream_id: uuid.UUID | None
    mode: RebuildMode
    swapped: bool
    replayed_through: int
    #: A moved head makes a check advisory.
    head_at_diff: int
    tables: tuple[TableDiff, ...]
    attempts: tuple[RebuildAttempt, ...]
    elapsed_seconds: float


@dataclass(frozen=True, slots=True)
class _StagedRebuild:
    """One attempt, replayed and diffed, not swapped."""

    replayed: ReplayResult
    replay_seconds: float
    tables: tuple[TableDiff, ...]
    diff_seconds: float
    head_at_diff: int

    def attempt(
        self, *, swap_seconds: float | None, conflict: str | None
    ) -> RebuildAttempt:
        return RebuildAttempt(
            replayed_through=self.replayed.replayed_through,
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
            replayed_through=self.replayed.replayed_through,
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
    """Phases 2 and 3, timed."""
    replay_started = monotonic()
    replayed = replay_into_shadow(library, models, wiring=wiring)
    replay_seconds = monotonic() - replay_started

    diff_started = monotonic()
    tables = diff_tables(models, library)
    diff_seconds = monotonic() - diff_started

    #: After the diff, for the check report.
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
    """Rebuild one library's projections, or check them."""
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
                swap_in(library, models, staged.replayed.replayed_through)
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
                    #: The lock provisioned a head to name.
                    stream_id, _ = _stream_head(library)
                return staged.report(
                    library=library,
                    mode=mode,
                    swapped=True,
                    stream_id=stream_id,
                    attempts=attempts,
                    elapsed_seconds=monotonic() - started,
                )

        #: Nothing is held while it waits.
        policy.sleep(policy.delay_for(attempt_number))

    raise AssertionError("The loop returns on its last attempt, conflict or not.")


def _stream_head(library: UserLibrary) -> tuple[uuid.UUID | None, int]:
    """The stream and sequence, or `(None, 0)`."""
    head = (
        LibraryEventStreamHead.objects.filter(library=library)
        .values_list("id", "current_sequence")
        .first()
    )
    return head if head is not None else (None, 0)
