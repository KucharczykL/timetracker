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

from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from typing import cast

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
