"""The command that changes the zone a library counts days in."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import ClassVar

from games.commands.playersession import _check_zones
from games.events.calendar import calendar_day_zone_changed
from games.events.dispatch import Command, CommandContext, CommandName
from games.events.playersession import ZoneName
from games.events.vocabulary import NewEvent, Unchanged
from games.models import LibraryCalendar


@dataclass(frozen=True, slots=True)
class SetCalendarDayZone(Command):
    """State the zone this library counts days in."""

    command_name: ClassVar[CommandName] = CommandName.CALENDAR_SET_DAY_ZONE
    day_zone: ZoneName

    def __post_init__(self) -> None:
        #: One spelling, so restatements fingerprint alike.
        object.__setattr__(self, "day_zone", self.day_zone.strip())

    def build(self, context: CommandContext) -> Sequence[NewEvent] | Unchanged:
        _check_zones(self.day_zone)
        row = LibraryCalendar.objects.filter(library=context.library).first()
        if row is not None and row.day_zone == self.day_zone:
            return Unchanged(f"This library already counts days in {self.day_zone}.")
        return [calendar_day_zone_changed(context.library.pk, self.day_zone)]
