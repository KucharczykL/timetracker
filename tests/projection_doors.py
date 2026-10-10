"""The test door: test seeding may write a projection table.

A test seeds projection rows directly. A statement that writes a guarded
table, with no door open, opens `TEST_SEEDING` when the nearest source frame
is under `tests/` or `e2e/`, or when no source frame is on the stack at all
(Django's flush between transactional tests). Application code a test runs
stays guarded.
"""

import contextvars
import sys
from collections.abc import Callable
from pathlib import Path
from types import FrameType
from typing import Any, Literal

import pytest
from django.conf import settings
from django.db import connections
from django.db.backends.signals import connection_created

from games.projection_writers import (
    ProjectionWriter,
    guarded_kinds_written,
    install_guard,
    open_writer,
    projection_writes,
    refuse_unpermitted_writes,
)

type SourceClass = Literal["test", "app"]

#: Top directories under the repository root that hold source.
SOURCE_TREES: dict[str, SourceClass] = {
    "tests": "test",
    "e2e": "test",
    "games": "app",
    "common": "app",
    "timetracker": "app",
    "contrib": "app",
    "scripts": "app",
}

_THIS_FILE = __file__

_strict: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "projection_guard_strict", default=False
)


def classify(relative_parts: tuple[str, ...]) -> SourceClass | None:
    """Whether a path under the root is test or app source; None if neither."""
    if not relative_parts:
        return None
    return SOURCE_TREES.get(relative_parts[0])


def _relative_parts(filename: str) -> tuple[str, ...] | None:
    """The path's parts under the repository root, or None outside it."""
    try:
        return Path(filename).relative_to(settings.BASE_DIR).parts
    except ValueError:
        return None


def _frame_permits_seeding() -> bool:
    """The nearest source frame decides; no source frame permits."""
    frame: FrameType | None = sys._getframe(1)
    while frame is not None:
        if frame.f_code.co_filename != _THIS_FILE:
            parts = _relative_parts(frame.f_code.co_filename)
            classification = classify(parts) if parts is not None else None
            if classification is not None:
                return classification == "test"
        frame = frame.f_back
    return True


def _seed_from_tests(
    execute: Callable[..., Any], sql: str, params: Any, many: bool, context: Any
) -> Any:
    """Execute wrapper: open the test door for one seeding statement."""
    if (
        open_writer() is None
        and not _strict.get()
        and guarded_kinds_written(sql)
        and _frame_permits_seeding()
    ):
        with projection_writes(ProjectionWriter.TEST_SEEDING):
            return execute(sql, params, many, context)
    return execute(sql, params, many, context)


def _install_on_connection(connection, **kwargs: Any) -> None:
    """Put the seeding wrapper directly before the guard, once."""
    install_guard(connection)
    wrappers = connection.execute_wrappers
    if _seed_from_tests in wrappers:
        return
    guard_index = (
        wrappers.index(refuse_unpermitted_writes)
        if refuse_unpermitted_writes in wrappers
        else 0
    )
    wrappers.insert(guard_index, _seed_from_tests)


def install() -> None:
    """Connect the seeding wrapper to every connection, present and future."""
    connection_created.connect(
        _install_on_connection, dispatch_uid="tests.projection_doors"
    )
    for connection in connections.all(initialized_only=True):
        _install_on_connection(connection)


@pytest.fixture
def projection_guard_strict():
    """Shut the seeding door for the test: a seed must go through a command."""
    token = _strict.set(True)
    try:
        yield
    finally:
        _strict.reset(token)
