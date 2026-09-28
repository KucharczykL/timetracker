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
    """The note of an endpoint without ways.

    No note is the empty string: an optional key would ask
    whether absent and empty differ, and here they do not.
    """

    note: str


class EndpointEvents[PayloadT](NamedTuple):
    """The three acts on one endpoint."""

    stated: EventSpec[PayloadT]
    corrected: EventSpec[PayloadT]
    voided: EventSpec[Any]

    @property
    def family(self) -> tuple[EventType, EventType, EventType]:
        """The types whose latest owns the endpoint's value."""
        return (
            self.stated.event_type,
            self.corrected.event_type,
            self.voided.event_type,
        )


def endpoint_events[PayloadT](
    aggregate_type: AggregateType,
    *,
    stated: EventType,
    corrected: EventType,
    voided: EventType,
    payload: type[PayloadT],
    voided_payload: type,
) -> EndpointEvents[PayloadT]:
    """Register three specs; callers spell every type."""
    events = EndpointEvents(
        stated=EventSpec(stated, aggregate_type=aggregate_type, payload=payload),
        corrected=EventSpec(corrected, aggregate_type=aggregate_type, payload=payload),
        voided=EventSpec(voided, aggregate_type=aggregate_type, payload=voided_payload),
    )
    for spec in events:
        DEFAULT_EVENT_TYPES.register(spec)
    return events
