"""Display formatting for game-domain models, neutral of the view layer so any
view can import it without a view→view dependency."""

from common.time import local_strftime, timeformat
from games.models import Session


def session_time_range(session: Session) -> str:
    """The session's start (— end) timestamp string. Shared by every table that
    renders a session, so the formatting cannot drift between them."""
    start = local_strftime(session.timestamp_start)
    if session.timestamp_end:
        return f"{start} — {local_strftime(session.timestamp_end, timeformat)}"
    return start
