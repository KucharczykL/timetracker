"""What a row states about one endpoint."""

from dataclasses import dataclass
from datetime import datetime

from django.db import models

from games.end_ways import EndWay
from games.endpoint_fields import EndpointColumns
from timetracker.temporal import TemporalValue


@dataclass(frozen=True, slots=True)
class StatedEndpoint:
    """An act that occurred, and what was said about it.

    The act is this object's existence, which is why the date never
    has to carry it: `when` is None for a day nobody knows, and a row
    that never reached this endpoint has no `StatedEndpoint` at all.
    """

    recorded_at: datetime
    when: TemporalValue | None
    note: str
    #: None for an endpoint without ways.
    way: EndWay | None = None


def way_of(ended: StatedEndpoint) -> EndWay:
    """The way a way endpoint's act states."""
    if ended.way is None:
        raise TypeError("An endpoint without ways states no way.")
    return ended.way


def stated(row: models.Model, endpoint: EndpointColumns) -> StatedEndpoint | None:
    """What the row states about the endpoint, or nothing."""
    recorded_at = getattr(row, endpoint.marker)
    if recorded_at is None:
        return None
    return StatedEndpoint(
        recorded_at,
        getattr(row, endpoint.when),
        getattr(row, endpoint.note),
        None if endpoint.way is None else EndWay(getattr(row, endpoint.way.column)),
    )
