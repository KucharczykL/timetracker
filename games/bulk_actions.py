"""What one act on many rows is, declared once per act.

The readable inventory, as the command vocabulary is: one grep, and no
entry that is not a thing the app does. An act is a value here and a
route nowhere; `games/views/bulk.py` runs any of them. Making the value
is declaring it, so the table holds every act and nothing else.

A declaration states four callables, and the aggregate its inverse
takes. That last one is not decoration: one act may write more than one
aggregate. The reclassification appends a created record beside the
session that became it, under one correlation id, so a batch's Undo
that read every aggregate of the batch would hand a record's key to a
command that reads sessions, and refuse every row of its own batch.
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

#: An act's stable name, and the segment its route carries.
type BulkActionName = str  # "session.reclassify"

#: A row key as posted, before anything parses it.
type RowKey = str

#: A list's `?filter=` JSON, as the statement carries it.
type FilterJson = str


class Cardinality(StrEnum):
    """How many rows an act is offered on.

    The tray reads it; the runner does not, because a person who posts
    a wider selection than an act is offered on is told by the
    confirmation rather than refused a route.
    """

    ONE = "one"
    MANY = "many"


class RowOutcome(StrEnum):
    """What a dispatch did to one row the act reached.

    A refusal is no outcome, whether the resolution met it or the
    dispatch did. These two are what a dispatch that ran answers, and
    the tally counts them apart because "done" should not claim work
    nobody did.
    """

    MOVED = "moved"
    UNCHANGED = "unchanged"

    @classmethod
    def of(cls, result: CommandResult) -> RowOutcome:
        """What one dispatch answered, as the runner counts it.

        A replay is moved: the key was this batch's own, so the row is
        where the batch put it.
        """
        return (
            cls.UNCHANGED if result.outcome is CommandOutcome.UNCHANGED else cls.MOVED
        )


@dataclass(frozen=True, slots=True)
class Refused:
    """A key the act leaves alone, and why."""

    key: RowKey
    sentence: str
    #: Gone since the confirmation resolved it, rather than refused on
    #: its merits. The answer counts the two apart, because one is the
    #: person's doing and the other is not.
    lost: bool = False


@dataclass(frozen=True, slots=True)
class Resolution:
    """The rows an act may run on, and a sentence for each it may not."""

    rows: tuple[Any, ...]
    refused: tuple[Refused, ...]


#: The whole set an "all" statement names, before its exclusions.
type Scope = Callable[[UserLibrary, FilterJson], QuerySet[Any]]
#: Keys to rows, or to sentences.
type Resolve = Callable[[UserLibrary, Sequence[uuid.UUID]], Resolution]
#: One row, dispatched through its wrapper in games/writes/.
type RunRow = Callable[[User, Any, IdempotencyKey, uuid.UUID], RowOutcome]
#: One row's opposite, by key: the row itself may be unreadable by now.
#: Keyed like the act, because an Undo is a batch of its own.
type UndoRow = Callable[[User, uuid.UUID, IdempotencyKey, uuid.UUID], RowOutcome]

_TABLE: dict[BulkActionName, BulkAction] = {}


@dataclass(frozen=True, slots=True)
class BulkAction:
    """One act, and everything the runner needs to run and undo it.

    Constructing one declares it. There is no second path that reaches
    the table, and none that skips the two refusals below.
    """

    name: BulkActionName
    #: The act in a person's words. The confirmation asks with it, and
    #: the tray's control will say it.
    label: str
    #: The confirmation's heading.
    title: str
    #: Its submit.
    confirm_label: str
    #: The noun `answered()` speaks of.
    subject: SubjectNoun
    cardinality: Cardinality
    #: The aggregate `inverse` takes, so the Undo reads the right half
    #: of a batch that wrote more than one.
    inverse_aggregate: AggregateType
    #: Where the act returns when it carries no origin.
    fallback: UrlName
    scope: Scope
    resolve: Resolve
    run: RunRow
    inverse: UndoRow

    def __post_init__(self) -> None:
        """Refuse a declaration that cannot run, then declare it.

        Both refusals state themselves at import rather than at the
        press: a batch that discovers its own declaration is wrong has
        already written half its rows.
        """
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


#: Every act, keyed by its name. A live view of the table the imports
#: below fill, so a reader sees every act and writes none.
BULK_ACTIONS: Mapping[BulkActionName, BulkAction] = MappingProxyType(_TABLE)


#: Last, and this is the whole inventory: each module below makes one
#: `BulkAction`, which is what declaring one is. It imports the value
#: types above, so the import waits until they exist rather than
#: sitting at the top.
from games import bulk_reclassification  # noqa: F401
