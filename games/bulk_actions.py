"""What one act on many rows is, declared once per act.

The readable inventory, as the command vocabulary is: one grep, and no
entry that is not a thing the app does. An act is a value here and a
route nowhere; `games/views/bulk.py` runs any of them.

A declaration states five callables, and the aggregate its inverse
takes. That last one is not decoration: one act may write more than one
aggregate. The reclassification appends a created record beside the
session that became it, under one correlation id, so a batch's Undo
that read every aggregate of the batch would hand a record's key to a
command that reads sessions, and refuse every row of its own batch.
"""

import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from django.contrib.auth.models import User
from django.db.models import QuerySet

from common.returns import UrlName
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
type RunRow = Callable[[User, Any, IdempotencyKey, uuid.UUID], None]
#: One row's opposite, by key: the row itself may be unreadable by now.
type UndoRow = Callable[[User, uuid.UUID, uuid.UUID], None]

_TABLE: dict[BulkActionName, BulkAction] = {}


@dataclass(frozen=True, slots=True)
class BulkAction:
    """One act, and everything the runner needs to run and undo it."""

    name: BulkActionName
    #: What the tray's control says.
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

    @classmethod
    def on(cls, **stated: Any) -> BulkAction:
        """The one construction path; refuses a declaration that cannot run.

        Both refusals state themselves at import rather than at the
        press: a batch that discovers its own declaration is wrong has
        already written half its rows.
        """
        action = cls(**stated)
        if action.name in _TABLE:
            raise ValueError(
                f"{action.name!r} is already declared. An act names itself once."
            )
        if not DEFAULT_EVENT_TYPES.event_types_for(action.inverse_aggregate):
            raise ValueError(
                f"{action.name!r} names {action.inverse_aggregate!r} as the "
                "aggregate its inverse takes, and no event type speaks about "
                "it. Its Undo would read an empty batch."
            )
        _TABLE[action.name] = action
        return action


def bulk_action(name: BulkActionName) -> BulkAction | None:
    """The act that name declares, or none."""
    return _TABLE.get(name)


#: Every act, keyed by its name. Filled by the imports below.
BULK_ACTIONS: dict[BulkActionName, BulkAction] = _TABLE


#: Last, and this is the whole inventory: each module below declares one
#: act through `BulkAction.on`. It imports the value types above, so the
#: import waits until they exist rather than sitting at the top.
from games import bulk_reclassification  # noqa: F401
