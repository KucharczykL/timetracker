"""Display formatting for game-domain models, neutral of the view layer so any
view can import it without a view→view dependency."""

from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from common.date_time_presentation import DateTimePresentation, DateTimeStyle
from games.models import Session


def _presentation_in_zone(
    presentation: DateTimePresentation, zone_name: str | None
) -> DateTimePresentation | None:
    """``presentation`` re-aimed at a session's own zone, or ``None`` when the
    stored name is missing or unusable (e.g. removed from tzdata) — the caller
    falls back to the account zone rather than crashing a list page."""
    if not zone_name:
        return None
    try:
        zone = ZoneInfo(zone_name)
    except ZoneInfoNotFoundError, ValueError:
        return None
    return replace(presentation, timezone=zone)


def zone_label(value: datetime, zone: ZoneInfo) -> str:
    """Short zone label for display, e.g. "JST" or "+09".

    Public because the session API ships this exact string to the client
    (``games/api.py``) instead of letting the browser recompute it — Intl's
    ``timeZoneName: "short"`` says "GMT+9" where this says "JST", and a row
    must read the same whether the server rendered it or the client rebuilt it.
    """
    return value.astimezone(zone).tzname() or zone.key


def _endpoint_text(
    value: datetime,
    style: DateTimeStyle,
    endpoint_presentation: DateTimePresentation,
    account_presentation: DateTimePresentation,
) -> str:
    labelled = endpoint_presentation.timezone.key != account_presentation.timezone.key
    # A labelled endpoint always carries its date: projecting into another zone
    # can move the wall clock across midnight, and "06:00 JST" after a 20:00
    # start reads as the same evening unless the date is spelled out.
    text = endpoint_presentation.format(value, "datetime" if labelled else style)
    if labelled:
        # Without the label a sorted list lies: a 21:00 session can be
        # genuinely earlier than the 14:00 one after it.
        text = f"{text} {zone_label(value, endpoint_presentation.timezone)}"
    return text


def session_time_range(session: Session, presentation: DateTimePresentation) -> str:
    """The session's start (— end) timestamp string. Shared by every table that
    renders a session, so the formatting cannot drift between them. Under the
    "own" display preference each endpoint renders in its stored zone, labelled
    whenever that differs from the account's display zone."""
    start_presentation = presentation
    end_presentation = presentation
    if presentation.session_time_zone_display == "own":
        start_presentation = (
            _presentation_in_zone(presentation, session.timestamp_start_timezone)
            or presentation
        )
        end_presentation = (
            _presentation_in_zone(presentation, session.timestamp_end_timezone)
            or presentation
        )
    start = _endpoint_text(
        session.timestamp_start, "datetime", start_presentation, presentation
    )
    if session.timestamp_end is None:
        return start
    end = _endpoint_text(session.timestamp_end, "time", end_presentation, presentation)
    return f"{start} — {end}"
