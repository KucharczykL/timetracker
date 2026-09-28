"""Every stated endpoint, and the columns and events each names.

An endpoint is one act a projection row states at most once at a
time: that it happened, on a day or on none, with a note, and for
an endpoint with ways, in one way. The act is stated, corrected,
and voided; the descriptor names what each touches.
"""

from dataclasses import dataclass, fields

from django.apps import apps
from django.db import models

from games.endpoint_fields import EndpointColumns
from games.events.endpoint import EndpointEvents
from games.events.playthrough import (
    PLAYTHROUGH_COMPLETION_EVENTS,
    PLAYTHROUGH_START_EVENTS,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class Endpoint(EndpointColumns):
    """One endpoint's columns and its three events."""

    events: EndpointEvents

    @classmethod
    def over(cls, columns: EndpointColumns, events: EndpointEvents) -> Endpoint:
        """The endpoint a model's columns and a module's events make."""
        return cls(
            **{field.name: getattr(columns, field.name) for field in fields(columns)},
            events=events,
        )

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

ENDPOINTS: tuple[Endpoint, ...] = (PLAYTHROUGH_START, PLAYTHROUGH_COMPLETION)
