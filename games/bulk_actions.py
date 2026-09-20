"""One act on many rows, declared once.

Making the value declares it; `games/views/bulk.py` runs any of them.

An act may write two aggregates: the reclassification appends a created
record beside the session that became it, under one correlation id. An
Undo reading every aggregate of the batch would hand a record's key to
a command that reads sessions, and refuse every row of its own batch.
"""

import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from django.contrib.auth.models import User
from django.db.models import QuerySet

from common.returns import UrlName
from games.events.dispatch import CommandOutcome, CommandResult
from games.events.idempotency import IdempotencyKey
from games.events.vocabulary import DEFAULT_EVENT_TYPES, AggregateType
from games.models import UserLibrary
from games.writes.answers import SubjectNoun

#: An act's name, and its route segment.
type BulkActionName = str  # "session.reclassify"

#: A row key as posted.
type RowKey = str

#: A list's `?filter=` JSON.
type FilterJson = str


class Cardinality(StrEnum):
    """How many rows an act offers."""

    ONE = "one"
    MANY = "many"


class RowOutcome(StrEnum):
    """What a dispatch did to one row."""

    MOVED = "moved"
    UNCHANGED = "unchanged"

    @classmethod
    def of(cls, result: CommandResult) -> RowOutcome:
        """What one dispatch answered.

        A replay is moved: the key was this batch's own, so the row is
        where the batch put it.
        """
        return (
            cls.UNCHANGED if result.outcome is CommandOutcome.UNCHANGED else cls.MOVED
        )


@dataclass(frozen=True, slots=True)
class Refused:
    """A key the act leaves alone."""

    key: RowKey
    sentence: str
    #: Gone since the confirmation, not refused.
    lost: bool = False


@dataclass(frozen=True, slots=True)
class Resolution:
    """Rows to act on, and sentences."""

    rows: tuple[Any, ...]
    refused: tuple[Refused, ...]


#: What an "all" statement names, before exclusions.
type Scope = Callable[[UserLibrary, FilterJson], QuerySet[Any]]
#: Keys to rows, or to sentences.
type Resolve = Callable[[UserLibrary, Sequence[uuid.UUID]], Resolution]
#: One row, through its `games/writes/` wrapper.
type RunRow = Callable[[User, Any, IdempotencyKey, uuid.UUID], RowOutcome]
#: One row's opposite, by key.
type UndoRow = Callable[[User, uuid.UUID, IdempotencyKey, uuid.UUID], RowOutcome]

_TABLE: dict[BulkActionName, BulkAction] = {}


@dataclass(frozen=True, slots=True)
class BulkAction:
    """One act, run and undone."""

    name: BulkActionName
    #: The act in a person's words.
    label: str
    #: The confirmation's heading.
    title: str
    #: Its submit.
    confirm_label: str
    #: The noun `answered()` speaks of.
    subject: SubjectNoun
    cardinality: Cardinality
    #: Which half a mixed batch's Undo reads.
    inverse_aggregate: AggregateType
    #: Where the act returns without an origin.
    fallback: UrlName
    scope: Scope
    resolve: Resolve
    run: RunRow
    inverse: UndoRow

    def __post_init__(self) -> None:
        """Refuse a declaration that cannot run."""
        if self.name in _TABLE:
            raise ValueError(
                f"{self.name!r} is already declared. An act names itself once."
            )
        if not DEFAULT_EVENT_TYPES.event_types_for(self.inverse_aggregate):
            raise ValueError(
                f"{self.name!r} names {self.inverse_aggregate!r} as the "
                "aggregate its inverse takes, and no event type speaks about "
                "it. Its Undo would read an empty batch."
            )
        _TABLE[self.name] = self


def bulk_action(name: BulkActionName) -> BulkAction | None:
    """The act that name declares, or none."""
    return _TABLE.get(name)


#: Every act, keyed by name. Read-only.
BULK_ACTIONS: Mapping[BulkActionName, BulkAction] = MappingProxyType(_TABLE)


#: Imported last: each module declares one act.
from games import bulk_reclassification  # noqa: F401
