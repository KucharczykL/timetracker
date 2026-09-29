"""One fact, before a batch and as it stated."""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from games.events.dispatch import RowUnreadable
from games.events.vocabulary import EventSpec
from games.models import LibraryEvent, UserLibrary
from games.reads.events import aggregate_events

#: A payload's key for one fact.
type PayloadKey = str  # "status"


@dataclass(frozen=True, slots=True)
class FactChange[T]:
    """One fact, before a batch and as it stated."""

    before: T
    stated: T


@dataclass(frozen=True, slots=True)
class Fact[T]:
    """One fact's events, payload key and reading.

    `initial` is its value at creation; None reads the
    creation's payload under `key`.
    """

    created: EventSpec[Any]
    changed: EventSpec[Any]
    key: PayloadKey
    read: Callable[[object], T | None]
    initial: T | None = None


def _value[T](fact: Fact[T], event: LibraryEvent) -> T:
    value = fact.read(event.payload.get(fact.key))
    if value is None:
        raise RowUnreadable(
            f"event {event.pk} at sequence {event.sequence} of library "
            f"{event.library_id} states {fact.key} {event.payload.get(fact.key)!r}"
        )
    return value


def fact_change[T](
    fact: Fact[T],
    library: UserLibrary,
    aggregate_id: uuid.UUID,
    batch_id: uuid.UUID,
) -> FactChange[T] | None:
    """None where the batch stated no such fact.

    `RowUnreadable` where nothing precedes the batch's event.
    """
    created, changed = fact.created.event_type, fact.changed.event_type
    events = list(
        aggregate_events(library, aggregate_id).filter(
            event_type__in=(created, changed)
        )
    )
    ours = next(
        (
            event
            for event in events
            if event.correlation_id == batch_id and event.event_type == changed
        ),
        None,
    )
    if ours is None:
        return None
    earlier = [event for event in events if event.sequence < ours.sequence]
    if not earlier:
        raise RowUnreadable(
            f"{fact.created.aggregate_type} {aggregate_id} of library {library.pk} "
            f"states {changed} at sequence {ours.sequence} and nothing before it"
        )
    latest = earlier[-1]
    before = (
        fact.initial
        if latest.event_type == created and fact.initial is not None
        else _value(fact, latest)
    )
    return FactChange(before=before, stated=_value(fact, ours))
