"""One act on many rows, declared once.

Making the value declares it; `games/views/bulk.py` runs any of them.

An act may write two aggregates: the reclassification appends a created
record beside the session that became it, under one correlation id. An
Undo reading every aggregate of the batch would hand a record's key to
a command that reads sessions, and refuse every row of its own batch.
"""

import inspect
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Protocol

from django.contrib.auth.models import User
from django.db.models import Model, QuerySet
from django.http import QueryDict

from common.components.core import Node
from common.components.primitives import Align, ButtonColor, Cell
from common.date_time_presentation import DateTimePresentation
from common.duration_presentation import DurationPresentation
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

#: What an act asks for, as one string.
type ChoiceValue = str  # a run's key, a batch's id, an instant and its zone

#: The form field a choice is posted under.
type FieldName = str


@dataclass(frozen=True, slots=True)
class ActTitle:
    """The confirmation's heading, in either count.

    A whole clause, not a noun with a suffix.
    """

    one: str
    many: str

    def __post_init__(self) -> None:
        if not self.one or not self.many:
            raise ValueError(
                "An act states both halves of its title: "
                f"{self.one!r} for one row and {self.many!r} for several."
            )
        if self.one == self.many:
            raise ValueError(
                f"{self.one!r} is both halves of a title. An act reading the "
                "same over one row and over several states no count."
            )

    def for_count(self, count: int) -> str:
        """The half this many rows reads in; none is plural."""
        return self.one if count == 1 else self.many


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
class Resolution[RowT: Model]:
    """Rows to act on, and sentences."""

    rows: tuple[RowT, ...]
    refused: tuple[Refused, ...]


@dataclass(frozen=True, slots=True)
class Presentations:
    """How this request writes days and durations."""

    dates: DateTimePresentation
    durations: DurationPresentation


#: One fact of one row, written for a person.
type PreviewCell[RowT: Model] = Callable[[RowT, Presentations], Cell]


@dataclass(frozen=True, slots=True)
class PreviewColumn[RowT: Model]:
    """One column of the confirmation's table.

    Generic in the row, so an act cannot state the columns of another
    act's rows: nothing reads a preview until a person stands on the
    confirmation, which is the one screen before the write.
    """

    heading: str
    cell: PreviewCell[RowT]
    align: Align = "left"


#: What an "all" statement names, before exclusions.
type Scope[RowT: Model] = Callable[[UserLibrary, FilterJson], QuerySet[RowT]]
#: Keys to rows, or to sentences.
type Resolve[RowT: Model] = Callable[
    [UserLibrary, Sequence[uuid.UUID]], Resolution[RowT]
]


class RunRow[RowT: Model](Protocol):
    """One row, through its `games/writes/` wrapper.

    A protocol, not a `Callable` alias, so the three facts
    are keywords: `ChoiceValue` and `IdempotencyKey` are
    both text, and no check refuses them in each other's
    place. The row is positional-only because every act
    calls it something of its own.
    """

    def __call__(
        self,
        actor: User,
        row: RowT,
        /,
        *,
        choice: ChoiceValue | None,
        idempotency_key: IdempotencyKey,
        correlation_id: uuid.UUID,
    ) -> RowOutcome: ...


class UndoRow(Protocol):
    """One row's opposite, by key.

    Takes the batch it undoes, not a choice: the forward
    slot answers a person's question, and this one never
    does. Two facts in one slot would let a run's key and a
    batch's id stand in for each other, and both are text.
    """

    def __call__(
        self,
        actor: User,
        row_id: uuid.UUID,
        /,
        *,
        undoes: uuid.UUID,
        idempotency_key: IdempotencyKey,
        correlation_id: uuid.UUID,
    ) -> RowOutcome: ...


class BoundRow(Protocol):
    """One batch's row callable, its own fact bound."""

    def __call__(
        self,
        actor: User,
        row: Any,
        /,
        *,
        idempotency_key: IdempotencyKey,
        correlation_id: uuid.UUID,
    ) -> RowOutcome: ...


@dataclass(frozen=True, slots=True)
class Control:
    """The control the confirmation hosts."""

    node: Node


@dataclass(frozen=True, slots=True)
class RefusedAct:
    """One sentence, and no press."""

    sentence: str


@dataclass(frozen=True, slots=True)
class AsksNothing:
    """No rows, so no question to put."""


#: What `offer` answers.
#: Named, because `Child` is `Node | str`: bare
#: text is a control as well as a refusal, and one
#: return type cannot say which was meant.
type Offered = Control | RefusedAct | AsksNothing


@dataclass(frozen=True, slots=True)
class BulkChoice[RowT: Model]:
    """A fact the act asks for, before it runs.

    `offer` draws the control, or refuses the whole act.
    `settle` answers the one string every row is handed, and
    raises `CommandRejected` for a post it cannot read.
    """

    offer: Callable[[UserLibrary, Sequence[RowT], FieldName], Offered]
    settle: Callable[[UserLibrary, QueryDict], ChoiceValue]


_TABLE: dict[BulkActionName, BulkAction[Any]] = {}


@dataclass(frozen=True, slots=True)
class BulkAction[RowT: Model]:
    """One act, run and undone."""

    name: BulkActionName
    #: The act in a person's words.
    label: str
    #: Its heading, in both counts.
    title: ActTitle
    #: Its submit.
    confirm_label: str
    #: The noun `answered()` speaks of.
    subject: SubjectNoun
    #: What the act does to a row, in the button's colours.
    color: ButtonColor
    #: Which half a mixed batch's Undo reads.
    inverse_aggregate: AggregateType
    #: Where the act returns without an origin.
    fallback: UrlName
    scope: Scope[RowT]
    resolve: Resolve[RowT]
    run: RunRow[RowT]
    inverse: UndoRow
    #: What the confirmation shows of each row.
    preview: tuple[PreviewColumn[RowT], ...]
    #: What the act asks for first, or nothing.
    choice: BulkChoice[RowT] | None = None

    def __post_init__(self) -> None:
        """Refuse a declaration that cannot run."""
        if self.name in _TABLE:
            raise ValueError(
                f"{self.name!r} is already declared. An act names itself once."
            )
        for role, callable_, facts in (
            ("run", self.run, ("choice", "idempotency_key", "correlation_id")),
            ("inverse", self.inverse, ("undoes", "idempotency_key", "correlation_id")),
        ):
            called = getattr(callable_, "__name__", repr(callable_))
            stated = inspect.signature(callable_).parameters
            for fact in facts:
                if fact not in stated:
                    raise ValueError(
                        f"{self.name!r} states a {called} that takes no {fact}."
                    )
                if stated[fact].kind is not inspect.Parameter.KEYWORD_ONLY:
                    raise ValueError(
                        f"{self.name!r}'s {role} ({called}) takes {fact} "
                        "by position. Two of the three facts are text, so "
                        "position cannot tell them apart."
                    )
        if not DEFAULT_EVENT_TYPES.event_types_for(self.inverse_aggregate):
            raise ValueError(
                f"{self.name!r} names {self.inverse_aggregate!r} as the "
                "aggregate its inverse takes, and no event type speaks about "
                "it. Its Undo would read an empty batch."
            )
        _TABLE[self.name] = self


def bulk_action(name: BulkActionName) -> BulkAction[Any] | None:
    """The act that name declares, or none."""
    return _TABLE.get(name)


#: Every act, keyed by name. Read-only.
BULK_ACTIONS: Mapping[BulkActionName, BulkAction[Any]] = MappingProxyType(_TABLE)


#: Imported last: each module declares its acts.
from games import (  # noqa: F401
    bulk_finish,
    bulk_move,
    bulk_playthrough_acts,
    bulk_reclassification,
    bulk_removal,
)
