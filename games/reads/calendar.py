"""The zone a library counts days in."""

from zoneinfo import ZoneInfo

from games.models import LibraryCalendar, UserLibrary
from timetracker.settings_resolver import resolve_str_for_user


def calendar_day_zone(library: UserLibrary) -> ZoneInfo:
    """The calendar's zone, or the owner's display zone before one is stated."""
    row = LibraryCalendar.objects.filter(library=library).only("day_zone").first()
    if row is not None:
        return ZoneInfo(row.day_zone)
    return ZoneInfo(resolve_str_for_user(library.user, "DISPLAY_TIME_ZONE"))
