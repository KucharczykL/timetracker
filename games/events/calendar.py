"""The zone a library counts days in."""

import uuid
from typing import TypedDict

from pydantic import with_config

from games.events.playersession import ZoneName, ZoneText
from games.events.references import STRICT_SCHEMA
from games.events.vocabulary import DEFAULT_EVENT_TYPES, EventSpec, NewEvent


@with_config(STRICT_SCHEMA)
class CalendarDayZoneChangedPayload(TypedDict):
    """The library now counts days in this zone."""

    day_zone: ZoneText


CALENDAR_DAY_ZONE_CHANGED = EventSpec(
    "library.calendar.day_zone_changed",
    aggregate_type="calendar",
    payload=CalendarDayZoneChangedPayload,
)

DEFAULT_EVENT_TYPES.register(CALENDAR_DAY_ZONE_CHANGED)


def calendar_day_zone_changed(library_id: uuid.UUID, day_zone: ZoneName) -> NewEvent:
    """One calendar per library: the aggregate is the library."""
    return CALENDAR_DAY_ZONE_CHANGED.new(
        aggregate_id=library_id, payload={"day_zone": day_zone}
    )
