"""Display formatting for game-domain models, neutral of the view layer so any
view can import it without a view→view dependency."""

from common.date_time_presentation import DateTimePresentation
from games.models import Session


def session_time_range(session: Session, presentation: DateTimePresentation) -> str:
    """The session's start (— end) timestamp string. Shared by every table that
    renders a session, so the formatting cannot drift between them."""
    start = presentation.format(session.timestamp_start, "datetime")
    if session.timestamp_end:
        return f"{start} — {presentation.format(session.timestamp_end, 'time')}"
    return start
