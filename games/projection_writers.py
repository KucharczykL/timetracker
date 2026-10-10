"""Which code may write a projection table, and the door it opens."""

import contextlib
import functools
from collections.abc import Callable, Iterator, Mapping
from contextvars import ContextVar
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from django.db.backends.base.base import BaseDatabaseWrapper

from games.sql_writes import TableName, write_targets

type ModulePath = str  # repo-relative, e.g. "games/events/projection.py"


class GuardedKind(StrEnum):
    """A family of guarded tables, named by what it holds."""

    PROJECTION = "projection"
    VALUATION = "valuation"


class ProjectionWriter(StrEnum):
    """One permitted writer, one member per door."""

    PROJECTOR = "projector"
    REBUILD_SWAP = "rebuild_swap"
    LIBRARY_PURGE = "library_purge"
    SAMPLE_ANONYMIZER = "sample_anonymizer"
    VALUATION_PUBLISHER = "valuation_publisher"
    MIGRATE = "migrate"
    TEST_SEEDING = "test_seeding"


@dataclass(frozen=True, slots=True)
class PermittedWriter:
    """The module that opens a door, and the kinds the door may write."""

    module: ModulePath
    kinds: frozenset[GuardedKind]


PERMITTED_WRITERS: Mapping[ProjectionWriter, PermittedWriter] = {
    ProjectionWriter.PROJECTOR: PermittedWriter(
        "games/events/projection.py", frozenset({GuardedKind.PROJECTION})
    ),
    ProjectionWriter.REBUILD_SWAP: PermittedWriter(
        "games/events/rebuild.py", frozenset({GuardedKind.PROJECTION})
    ),
    ProjectionWriter.LIBRARY_PURGE: PermittedWriter(
        "games/retention.py",
        frozenset({GuardedKind.PROJECTION, GuardedKind.VALUATION}),
    ),
    ProjectionWriter.SAMPLE_ANONYMIZER: PermittedWriter(
        "games/management/commands/anonymize_sample.py",
        frozenset({GuardedKind.PROJECTION, GuardedKind.VALUATION}),
    ),
    ProjectionWriter.VALUATION_PUBLISHER: PermittedWriter(
        "games/valuations.py", frozenset({GuardedKind.VALUATION})
    ),
    ProjectionWriter.MIGRATE: PermittedWriter(
        "games/apps.py",
        frozenset({GuardedKind.PROJECTION, GuardedKind.VALUATION}),
    ),
    ProjectionWriter.TEST_SEEDING: PermittedWriter(
        "tests/projection_doors.py",
        frozenset({GuardedKind.PROJECTION, GuardedKind.VALUATION}),
    ),
}


@functools.cache
def guarded_tables() -> Mapping[TableName, GuardedKind]:
    """Every projection table and the valuation table, lower-cased."""
    #: Lazy: a module-level import risks a cycle through the models.
    from games.models import PurchaseValuation
    from games.projections import projection_models

    tables: dict[TableName, GuardedKind] = {
        model._meta.db_table.lower(): GuardedKind.PROJECTION
        for model in projection_models()
    }
    tables[PurchaseValuation._meta.db_table.lower()] = GuardedKind.VALUATION
    return tables


_open: ContextVar[ProjectionWriter | None] = ContextVar(
    "projection_writer_open", default=None
)


@contextlib.contextmanager
def projection_writes(writer: ProjectionWriter) -> Iterator[None]:
    """Open the door of `writer` for the block; the innermost door decides."""
    token = _open.set(writer)
    try:
        yield
    finally:
        _open.reset(token)


def open_writer() -> ProjectionWriter | None:
    """The innermost open door, or none."""
    return _open.get()


class ProjectionWriteRefused(RuntimeError):
    """A statement wrote a guarded table outside a door that permits it."""


def _guarded_writes(sql: str) -> tuple[tuple[TableName, GuardedKind], ...]:
    """Each guarded table a statement writes, with its kind.

    An unreadable write names no table, so it writes every kind.
    """
    tables = guarded_tables()
    writes: list[tuple[TableName, GuardedKind]] = []
    for target in write_targets(sql):
        if target == "":
            writes.extend(("", kind) for kind in GuardedKind)
            continue
        kind = tables.get(target)
        if kind is not None:
            writes.append((target, kind))
    return tuple(writes)


def guarded_kinds_written(sql: str) -> frozenset[GuardedKind]:
    """The kinds of guarded table a statement writes."""
    return frozenset(kind for _table, kind in _guarded_writes(sql))


def refuse_unpermitted_writes(
    execute: Callable[..., Any], sql: str, params: Any, many: bool, context: Any
) -> Any:
    """Django execute wrapper: a guarded write needs a door that permits it."""
    writer = open_writer()
    permitted = PERMITTED_WRITERS[writer].kinds if writer is not None else frozenset()
    for table, kind in _guarded_writes(sql):
        if kind not in permitted:
            named = table or "a table it cannot read"
            raise ProjectionWriteRefused(
                f"This statement writes {named}, a {kind} table, but the open "
                f"writer is {writer if writer is not None else 'none'}, which "
                f"does not permit {kind} writes. Statement: {sql[:200]}"
            )
    return execute(sql, params, many, context)


def install_guard(connection: BaseDatabaseWrapper) -> None:
    """Put the guard first on `connection`, once."""
    if refuse_unpermitted_writes not in connection.execute_wrappers:
        connection.execute_wrappers.insert(0, refuse_unpermitted_writes)
