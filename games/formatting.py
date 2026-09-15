"""Display formatting for game-domain models, neutral of the view layer so any
view can import it without a view→view dependency."""

from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo

from common.date_time_presentation import (
    DateTimePresentation,
    DateTimeStyle,
    zone_or_none,
)
from games.models import PlayerSession, PlayerSessionTimingMode


def _presentation_in_zone(
    presentation: DateTimePresentation, zone_name: str | None
) -> DateTimePresentation | None:
    """``presentation`` re-aimed at a session's own zone, or ``None`` when the
    stored name is missing or unusable — the caller falls back to the account
    zone rather than crashing a list page."""
    zone = zone_or_none(zone_name)
    return None if zone is None else replace(presentation, timezone=zone)


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
    show_label: bool,
) -> str:
    text = endpoint_presentation.format(value, style)
    if show_label:
        text = f"{text} {zone_label(value, endpoint_presentation.timezone)}"
    return text


def session_time_range(
    session: PlayerSession, presentation: DateTimePresentation
) -> str:
    """The session's start (— end) string, or a Duration-only row's day.

    Shared by every table that renders a session, so the formatting cannot
    drift between them. Under the "own" display preference each endpoint
    renders in its stored zone, labelled whenever that differs from the
    account's display zone.
    """
    if session.timing_mode == PlayerSessionTimingMode.DURATION_ONLY:
        #: A written day: no instant, no zone, nothing to convert.
        assert session.stated_day is not None
        return presentation.format(session.stated_day, "date")
    assert session.started_at is not None
    start_presentation = presentation
    end_presentation = presentation
    if presentation.session_time_zone_display == "own":
        start_presentation = (
            _presentation_in_zone(presentation, session.started_at_zone) or presentation
        )
        end_presentation = (
            _presentation_in_zone(presentation, session.ended_at_zone) or presentation
        )

    start_differs = start_presentation.timezone.key != presentation.timezone.key
    end_differs = end_presentation.timezone.key != presentation.timezone.key
    same_zone = start_presentation.timezone.key == end_presentation.timezone.key
    # Without a label at all a sorted list lies: a 21:00 session can be
    # genuinely earlier than the 14:00 one after it. But when both endpoints
    # share one zone, saying so twice ("22:37 JST — 23:14 JST") repeats
    # information that hasn't changed — one label, on the end, reads the same
    # way "9am – 5pm PST" does.
    start_label = start_differs and not (same_zone and end_differs)

    start = _endpoint_text(
        session.started_at, "datetime", start_presentation, start_label
    )
    if session.ended_at is None:
        return start
    # The end only needs its own date when it actually differs from the
    # start's — not merely because it carries a zone label. Two endpoints in
    # the same far-away zone on the same calendar day (the common case) must
    # not print that date twice for no reason; a genuine date-line crossing
    # ("06:00 JST" the morning after a 20:00 start) still needs it spelled out.
    start_date = session.started_at.astimezone(start_presentation.timezone).date()
    end_date = session.ended_at.astimezone(end_presentation.timezone).date()
    end_style: DateTimeStyle = "datetime" if end_date != start_date else "time"
    end = _endpoint_text(session.ended_at, end_style, end_presentation, end_differs)
    return f"{start} — {end}"
