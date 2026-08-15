"""session_time_range under SESSION_TIME_ZONE_DISPLAY: own-zone rendering,
zone labels, NULL fallback, and graceful handling of an unusable stored zone."""

from dataclasses import replace
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from common.date_time_presentation import (
    DEFAULT_DATE_TIME_FORMAT_PROFILE,
    DateTimePresentation,
)
from games.formatting import session_time_range
from games.models import Game, Session

pytestmark = pytest.mark.django_db

_ACCOUNT_PRESENTATION = DateTimePresentation(
    DEFAULT_DATE_TIME_FORMAT_PROFILE, "en-us", ZoneInfo("Europe/Prague")
)
_OWN_PRESENTATION = replace(_ACCOUNT_PRESENTATION, session_time_zone_display="own")

# 2026-07-01 12:00 UTC = 14:00 CEST = 21:00 JST.
_START = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
_END = datetime(2026, 7, 1, 13, 0, tzinfo=UTC)


def _session(library, **overrides) -> Session:
    defaults = {
        "game": Game.objects.create(library=library, name="Hades"),
        "timestamp_start": _START,
        "timestamp_end": _END,
    }
    defaults.update(overrides)
    return Session.objects.create(**defaults)


def test_null_zones_render_exactly_as_before(owned_library):
    session = _session(owned_library)
    assert session_time_range(session, _OWN_PRESENTATION) == session_time_range(
        session, _ACCOUNT_PRESENTATION
    )
    assert "14:00" in session_time_range(session, _ACCOUNT_PRESENTATION)


def test_account_preference_ignores_stored_zones(owned_library):
    session = _session(
        owned_library,
        timestamp_start_timezone="Asia/Tokyo",
        timestamp_end_timezone="Asia/Tokyo",
    )
    rendered = session_time_range(session, _ACCOUNT_PRESENTATION)
    assert "21:00" not in rendered
    assert "JST" not in rendered


def test_own_preference_renders_zone_and_label(owned_library):
    session = _session(
        owned_library,
        timestamp_start_timezone="Asia/Tokyo",
        timestamp_end_timezone="Asia/Tokyo",
    )
    rendered = session_time_range(session, _OWN_PRESENTATION)
    assert "22:00 JST" in rendered


def test_same_zone_same_day_gets_one_label_on_the_end_no_repeated_date(owned_library):
    """Both endpoints land in the same zone on the same calendar day — the
    common case. Neither the date nor the zone label belongs on both ends:
    '22:37 JST — 23:14 JST' repeats a zone that never changed, and
    '22:37 JST — 22/09/2025 23:14 JST' would repeat a date that was never in
    question. One label, on the end, reads the way '9am – 5pm PST' does."""
    session = _session(
        owned_library,
        timestamp_start_timezone="Asia/Tokyo",
        timestamp_end_timezone="Asia/Tokyo",
    )
    rendered = session_time_range(session, _OWN_PRESENTATION)
    assert rendered == "2026-07-01 21:00 — 22:00 JST"


def test_a_labelled_end_carries_its_own_date_across_the_date_line(owned_library):
    """A labelled endpoint renders date + time, not time alone: 21:00 UTC is
    2026-07-02 06:00 in Tokyo, and "06:00 JST" after a 14:00 start reads as
    the same evening unless the date is there."""
    session = _session(
        owned_library,
        timestamp_end=datetime(2026, 7, 1, 21, 0, tzinfo=UTC),
        timestamp_end_timezone="Asia/Tokyo",
    )
    rendered = session_time_range(session, _OWN_PRESENTATION)
    assert rendered == "2026-07-01 14:00 — 2026-07-02 06:00 JST"


def test_own_preference_matching_zone_gets_no_label(owned_library):
    """A label only where the sorted list would otherwise lie — a session in
    the account's own zone reads exactly as before."""
    session = _session(
        owned_library,
        timestamp_start_timezone="Europe/Prague",
        timestamp_end_timezone="Europe/Prague",
    )
    rendered = session_time_range(session, _OWN_PRESENTATION)
    assert rendered == session_time_range(
        _session(owned_library), _ACCOUNT_PRESENTATION
    )


def test_flight_renders_each_endpoint_in_its_own_zone(owned_library):
    session = _session(
        owned_library,
        timestamp_start_timezone="Europe/Prague",
        timestamp_end_timezone="Asia/Tokyo",
    )
    rendered = session_time_range(session, _OWN_PRESENTATION)
    assert "14:00" in rendered  # start: CEST wall clock, no label (matches account)
    assert "22:00 JST" in rendered  # end: Tokyo wall clock, labelled


def test_unusable_stored_zone_falls_back_to_the_display_zone(owned_library):
    session = _session(owned_library, timestamp_start_timezone="Not/AZone")
    assert session_time_range(session, _OWN_PRESENTATION) == session_time_range(
        _session(owned_library), _ACCOUNT_PRESENTATION
    )


def test_open_session_labels_its_start(owned_library):
    session = _session(
        owned_library, timestamp_end=None, timestamp_start_timezone="Asia/Tokyo"
    )
    rendered = session_time_range(session, _OWN_PRESENTATION)
    assert rendered.endswith("21:00 JST")
