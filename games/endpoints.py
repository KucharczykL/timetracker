"""Every stated endpoint: its columns and events."""

from dataclasses import dataclass, fields
from typing import Any

from django.apps import apps
from django.db import models

from games.endpoint_fields import (
    EndpointColumns,
    EndpointColumnsBase,
    OpeningEndpointColumns,
)
from games.events.device import DEVICE_ACCESS_END_EVENTS
from games.events.endpoint import EndpointEvents, OpeningEndpointEvents
from games.events.libraryentry import ENTRY_ACQUISITION_EVENTS
from games.events.playthrough import (
    PLAYTHROUGH_COMPLETION_EVENTS,
    PLAYTHROUGH_START_EVENTS,
)
from games.models import DEVICE_ACCESS_END_COLUMNS, ENTRY_ACQUISITION_COLUMNS


def _column_values(columns: EndpointColumnsBase) -> dict[str, Any]:
    return {field.name: getattr(columns, field.name) for field in fields(columns)}


@dataclass(frozen=True, slots=True, kw_only=True)
class Endpoint(EndpointColumns):
    """One endpoint's columns and its three events."""

    events: EndpointEvents[Any]

    @classmethod
    def over(cls, columns: EndpointColumns, events: EndpointEvents[Any]) -> Endpoint:
        """Columns joined with their events."""
        return cls(**_column_values(columns), events=events)

    @property
    def model(self) -> type[models.Model]:
        return apps.get_model(self.model_label)


@dataclass(frozen=True, slots=True, kw_only=True)
class OpeningEndpoint(OpeningEndpointColumns):
    """One opening endpoint's columns and its correction."""

    events: OpeningEndpointEvents[Any]

    @classmethod
    def over(
        cls, columns: OpeningEndpointColumns, events: OpeningEndpointEvents[Any]
    ) -> OpeningEndpoint:
        """Columns joined with their events."""
        return cls(**_column_values(columns), events=events)

    @property
    def model(self) -> type[models.Model]:
        return apps.get_model(self.model_label)


PLAYTHROUGH_START = Endpoint(
    name="start",
    model_label="games.Playthrough",
    when="started",
    lower="started_lower",
    upper="started_upper",
    marker="start_recorded_at",
    note="start_note",
    events=PLAYTHROUGH_START_EVENTS,
)

PLAYTHROUGH_COMPLETION = Endpoint(
    name="completion",
    model_label="games.Playthrough",
    when="completed",
    lower="completed_lower",
    upper="completed_upper",
    marker="completion_recorded_at",
    note="completion_note",
    events=PLAYTHROUGH_COMPLETION_EVENTS,
)

DEVICE_ACCESS_END = Endpoint.over(DEVICE_ACCESS_END_COLUMNS, DEVICE_ACCESS_END_EVENTS)

ENTRY_ACQUISITION = OpeningEndpoint.over(
    ENTRY_ACQUISITION_COLUMNS, ENTRY_ACQUISITION_EVENTS
)

ENDPOINTS: tuple[Endpoint | OpeningEndpoint, ...] = (
    PLAYTHROUGH_START,
    PLAYTHROUGH_COMPLETION,
    DEVICE_ACCESS_END,
    ENTRY_ACQUISITION,
)
