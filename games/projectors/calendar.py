"""The current zone a library counts days in, and the days it moves."""

from typing import ClassVar

from games.events.calendar import CALENDAR_DAY_ZONE_CHANGED
from games.events.envelope import RecordedEvent
from games.events.projection import HandlerMap, Projector, ProjectorFamily
from games.models import LibraryCalendar, PlayerSession, PlayerSessionTimingMode


class LibraryCalendars(Projector):
    """One row per library, and every session day beside it.

    Writes rows its event does not name: a session's `day_zone` is
    the calendar, so one change rewrites every row holding an instant,
    removed rows included, and `effective_day` regenerates.
    """

    family_name = ProjectorFamily.CURRENT_STATE

    def _day_zone_changed(self, event: RecordedEvent) -> None:
        day_zone = event.payload["day_zone"]
        self.project(
            LibraryCalendar,
            event,
            day_zone=day_zone,
        )
        sessions = self.target.model(PlayerSession)
        sessions._default_manager.filter(
            library_id=event.library_id,
            timing_mode__in=(
                PlayerSessionTimingMode.TIMED,
                PlayerSessionTimingMode.CORRECTED,
            ),
        ).update(day_zone=day_zone)

    handles: ClassVar[HandlerMap] = {CALENDAR_DAY_ZONE_CHANGED: _day_zone_changed}
