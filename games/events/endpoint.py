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
    """The acts on one endpoint; a resume is optional."""

    stated: EventSpec[PayloadT]
    corrected: EventSpec[PayloadT]
    voided: EventSpec[Any]
    #: Access again after an end; the row reads as voided.
    resumed: EventSpec[Any] | None = None

    @property
    def specs(self) -> tuple[EventSpec[Any], ...]:
        """Every act this endpoint has."""
        acts = (self.stated, self.corrected, self.voided, self.resumed)
        return tuple(spec for spec in acts if spec is not None)

    @property
    def family(self) -> tuple[EventType, ...]:
        """The types whose latest owns the endpoint's value."""
        return tuple(spec.event_type for spec in self.specs)


class OpeningEndpointEvents[PayloadT](NamedTuple):
    """An opening endpoint's one act: correction."""

    corrected: EventSpec[PayloadT]

    @property
    def specs(self) -> tuple[EventSpec[PayloadT]]:
        return (self.corrected,)

    @property
    def family(self) -> tuple[EventType]:
        return (self.corrected.event_type,)


def opening_endpoint_events[PayloadT](
    aggregate_type: AggregateType,
    *,
    corrected: EventType,
    payload: type[PayloadT],
) -> OpeningEndpointEvents[PayloadT]:
    """Register the correction; creation states the day."""
    events = OpeningEndpointEvents(
        corrected=EventSpec(corrected, aggregate_type=aggregate_type, payload=payload),
    )
    DEFAULT_EVENT_TYPES.register(events.corrected)
    return events


def endpoint_events[PayloadT](
    aggregate_type: AggregateType,
    *,
    stated: EventType,
    corrected: EventType,
    voided: EventType,
    payload: type[PayloadT],
    voided_payload: type,
    resumed: EventType | None = None,
) -> EndpointEvents[PayloadT]:
    """Register every spec; callers spell every type."""
    events = EndpointEvents(
        stated=EventSpec(stated, aggregate_type=aggregate_type, payload=payload),
        corrected=EventSpec(corrected, aggregate_type=aggregate_type, payload=payload),
        voided=EventSpec(voided, aggregate_type=aggregate_type, payload=voided_payload),
        resumed=(
            None
            if resumed is None
            else EventSpec(
                resumed, aggregate_type=aggregate_type, payload=EndpointPayload
            )
        ),
    )
    for spec in events.specs:
        DEFAULT_EVENT_TYPES.register(spec)
    return events
