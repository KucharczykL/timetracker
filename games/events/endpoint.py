"""The events of a stated endpoint: stated, corrected, voided."""

from typing import Any, NamedTuple, TypedDict

from pydantic import with_config

from games.events.references import STRICT_SCHEMA
from games.events.vocabulary import (
    DEFAULT_EVENT_TYPES,
    AggregateType,
    EventSpec,
    EventType,
)


@with_config(STRICT_SCHEMA)
class EndpointPayload(TypedDict):
    """The note of one endpoint, and only that.

    The date is `effective_time`, which is where the charter puts what
    a player says happened. No note is the empty string: an optional
    key would ask a reader whether a value is absent or empty, and
    here the two mean one thing.
    """

    note: str


class EndpointEvents(NamedTuple):
    """The three acts on one endpoint."""

    stated: EventSpec[Any]
    corrected: EventSpec[Any]
    voided: EventSpec[Any]

    @property
    def family(self) -> tuple[EventType, EventType, EventType]:
        """The types whose latest owns the endpoint's value."""
        return (
            self.stated.event_type,
            self.corrected.event_type,
            self.voided.event_type,
        )


def endpoint_events(
    aggregate_type: AggregateType,
    *,
    stated: EventType,
    corrected: EventType,
    voided: EventType,
    payload: type,
    voided_payload: type,
) -> EndpointEvents:
    """Declare and register one endpoint's three specs.

    Every type is spelled by the caller: a recorded type never
    moves, so none is derived from a stem.
    """
    events = EndpointEvents(
        stated=EventSpec(stated, aggregate_type=aggregate_type, payload=payload),
        corrected=EventSpec(corrected, aggregate_type=aggregate_type, payload=payload),
        voided=EventSpec(voided, aggregate_type=aggregate_type, payload=voided_payload),
    )
    for spec in events:
        DEFAULT_EVENT_TYPES.register(spec)
    return events
