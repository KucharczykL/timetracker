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
from collections.abc import Iterable, Iterator
from contextlib import AbstractContextManager, contextmanager
from typing import Any, cast

from django.apps import apps as global_apps
from django.apps.registry import Apps
from django.db import connection
from django.db.models.fields.generated import GeneratedField

from games.events.targets import SHADOW_SUFFIX
from games.models import ProjectionModel

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
