"""The events of a stated endpoint: stated, corrected, voided."""

from dataclasses import dataclass
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


@dataclass(frozen=True, slots=True)
class EndpointEvents[PayloadT]:
    """The three acts on one endpoint."""

    stated: EventSpec[PayloadT]
    corrected: EventSpec[PayloadT]
    voided: EventSpec[Any]

    @property
    def specs(self) -> tuple[EventSpec[Any], ...]:
        """Every act this endpoint has."""
        return (self.stated, self.corrected, self.voided)

    @property
    def family(self) -> tuple[EventType, ...]:
        """The types whose latest owns the endpoint's value."""
        return tuple(spec.event_type for spec in self.specs)


@dataclass(frozen=True, slots=True)
class ResumableEndpointEvents[PayloadT](EndpointEvents[PayloadT]):
    """The three acts, and a resume."""

    #: Projects as a void does.
    resumed: EventSpec[EndpointPayload]

    @property
    def specs(self) -> tuple[EventSpec[Any], ...]:
        return (self.stated, self.corrected, self.voided, self.resumed)


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


def _registered[EventsT: EndpointEvents[Any]](events: EventsT) -> EventsT:
    for spec in events.specs:
        DEFAULT_EVENT_TYPES.register(spec)
    return events


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
    return _registered(
        EndpointEvents(
            stated=EventSpec(stated, aggregate_type=aggregate_type, payload=payload),
            corrected=EventSpec(
                corrected, aggregate_type=aggregate_type, payload=payload
            ),
            voided=EventSpec(
                voided, aggregate_type=aggregate_type, payload=voided_payload
            ),
        )
    )


def resumable_endpoint_events[PayloadT](
    aggregate_type: AggregateType,
    *,
    stated: EventType,
    corrected: EventType,
    voided: EventType,
    resumed: EventType,
    payload: type[PayloadT],
    voided_payload: type,
) -> ResumableEndpointEvents[PayloadT]:
    """Register four specs; callers spell every type."""
    return _registered(
        ResumableEndpointEvents(
            stated=EventSpec(stated, aggregate_type=aggregate_type, payload=payload),
            corrected=EventSpec(
                corrected, aggregate_type=aggregate_type, payload=payload
            ),
            voided=EventSpec(
                voided, aggregate_type=aggregate_type, payload=voided_payload
            ),
            resumed=EventSpec(
                resumed, aggregate_type=aggregate_type, payload=EndpointPayload
            ),
        )
    )
