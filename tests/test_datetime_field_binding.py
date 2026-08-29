"""Timezone binding for the Session datetime fields.

These fields used to be native ``<input type="datetime-local">`` and are now
the segmented ``<date-time-field>`` widget (issue #511). The widget submits an
offset-qualified wall clock, but a submission Django rejects — a DST gap — posts
back the bare wall clock, and *that* is the shape whose interpretation these
tests pin: it is read in the account's timezone, not the server's.
"""

import re
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.http import HttpResponse
from django.test import RequestFactory
from django.utils import timezone

from common.date_time_presentation import (
    DEFAULT_DATE_TIME_FORMAT_PROFILE,
    DateTimePresentation,
    zone_or_none,
)
from common.middleware import TimezoneActivationMiddleware
from games.forms import DateTimeFieldWidget, SessionForm
from games.models import Game, Session, UserPreferences
from timetracker import settings_resolver


def _presentation(time_zone: str) -> DateTimePresentation:
    return DateTimePresentation(
        DEFAULT_DATE_TIME_FORMAT_PROFILE, "en-us", ZoneInfo(time_zone)
    )


def _library():
    return get_user_model().objects.create_user(username="datetime-form-owner").library


def _session_form_data(game: Game, timestamp_start: str) -> dict[str, str]:
    return {
        "game": str(game.pk),
        "timestamp_start": timestamp_start,
        "timestamp_end": "",
        "duration_manual": "",
        "device": "",
        "note": "",
    }


def test_naive_session_input_is_interpreted_in_the_account_timezone(db):
    user = get_user_model().objects.create_user(username="tester", password="pw")
    game = Game.objects.create(library=user.library, name="Hades")
    UserPreferences.objects.filter(user=user).update(
        display_time_zone="Pacific/Kiritimati"
    )
    settings_resolver.clear_cache()
    captured: dict[str, object] = {}

    def response(request):
        form = SessionForm(
            library=user.library,
            data=_session_form_data(game, "2026-01-01T10:30"),
            presentation=_presentation("Pacific/Kiritimati"),
        )
        assert form.is_valid(), form.errors
        captured["timestamp_start"] = form.cleaned_data["timestamp_start"]
        return HttpResponse()

    request = RequestFactory().post("/tracker/session/add")
    request.user = user
    TimezoneActivationMiddleware(response)(request)

    assert captured["timestamp_start"] == datetime(2025, 12, 31, 20, 30, tzinfo=UTC)


def test_naive_dst_gap_is_rejected_in_the_account_timezone(db):
    user = get_user_model().objects.create_user(username="tester", password="pw")
    game = Game.objects.create(library=user.library, name="Hades")
    UserPreferences.objects.filter(user=user).update(
        display_time_zone="America/New_York"
    )
    settings_resolver.clear_cache()
    captured: dict[str, object] = {}

    def response(request):
        form = SessionForm(
            library=user.library,
            data=_session_form_data(game, "2026-03-08T02:30"),
            presentation=_presentation("America/New_York"),
        )
        captured["errors"] = form.errors.as_text()
        return HttpResponse()

    request = RequestFactory().post("/tracker/session/add")
    request.user = user
    TimezoneActivationMiddleware(response)(request)

    assert "couldn’t be interpreted in time zone America/New_York" in str(
        captured["errors"]
    )


def test_offset_qualified_input_binds_to_the_instant_it_names(db):
    """The shape the widget actually submits. An offset makes the value aware,
    so ``from_current_timezone`` leaves it alone and the account's own display
    zone cannot re-interpret it — the instant is the one the segments showed."""
    user = get_user_model().objects.create_user(username="tester", password="pw")
    game = Game.objects.create(library=user.library, name="Hades")
    UserPreferences.objects.filter(user=user).update(
        display_time_zone="Pacific/Kiritimati"
    )
    settings_resolver.clear_cache()
    captured: dict[str, object] = {}

    def response(request):
        form = SessionForm(
            library=user.library,
            data=_session_form_data(game, "2026-01-01T10:30:00.000000+14:00"),
            presentation=_presentation("Pacific/Kiritimati"),
        )
        assert form.is_valid(), form.errors
        captured["timestamp_start"] = form.cleaned_data["timestamp_start"]
        return HttpResponse()

    request = RequestFactory().post("/tracker/session/add")
    request.user = user
    TimezoneActivationMiddleware(response)(request)

    assert captured["timestamp_start"] == datetime(2025, 12, 31, 20, 30, tzinfo=UTC)


def test_session_uses_the_segmented_datetime_widget(db):
    """Issue #511: these were the last native date/time controls in the app."""
    presentation = _presentation("UTC")
    library = _library()
    session_form = SessionForm(library=library, presentation=presentation)
    for field_name in ("timestamp_start", "timestamp_end"):
        assert isinstance(
            session_form.fields[field_name].widget, DateTimeFieldWidget
        ), field_name


def test_an_ambiguous_stored_timestamp_survives_an_untouched_edit(db):
    """The hour a DST fall-back repeats happens twice, so a bare wall clock no
    longer says which instant was stored — and Django refuses to bind an
    ambiguous naive value at all, so re-saving such a session without touching
    it failed outright. AwareDateTimeField keeps the offset in the rendered
    value, so both occurrences round-trip to themselves."""
    game = Game.objects.create(library=_library(), name="Hades")
    earlier = datetime(2026, 11, 1, 5, 30, tzinfo=UTC)  # 01:30 EDT (-04:00)
    later = datetime(2026, 11, 1, 6, 30, tzinfo=UTC)  # 01:30 EST (-05:00)

    with timezone.override(ZoneInfo("America/New_York")):
        for stored in (earlier, later):
            session = Session.objects.create(game=game, timestamp_start=stored)
            rendered = SessionForm(
                library=game.library,
                instance=session,
                presentation=_presentation("America/New_York"),
            )["timestamp_start"]
            hidden = re.search(r'name="timestamp_start" value="([^"]*)"', str(rendered))
            assert hidden is not None
            # Both render the same wall clock; only the offset tells them apart.
            assert hidden.group(1).startswith("2026-11-01T01:30:00")

            resubmitted = SessionForm(
                library=game.library,
                data=_session_form_data(game, hidden.group(1)),
                instance=session,
                presentation=_presentation("America/New_York"),
            )
            assert resubmitted.is_valid(), resubmitted.errors
            assert resubmitted.cleaned_data["timestamp_start"] == stored


def test_zone_or_none_parses_valid_zones_and_rejects_junk():
    assert zone_or_none("Asia/Tokyo") == ZoneInfo("Asia/Tokyo")
    assert zone_or_none(None) is None
    assert zone_or_none("") is None
    assert zone_or_none("Not/AZone") is None


def test_edit_form_renders_the_wall_clock_in_the_sessions_own_zone(db):
    """A Tokyo-tagged 06:37 UTC start must render as Tokyo's 15:37+09:00, not
    the account's 08:37+02:00 — the digits shown are the digits that were
    typed against that zone."""
    game = Game.objects.create(library=_library(), name="Hades")
    session = Session.objects.create(
        game=game,
        timestamp_start=datetime(2026, 7, 28, 6, 37, tzinfo=UTC),
        timestamp_start_timezone="Asia/Tokyo",
    )
    rendered = str(
        SessionForm(
            library=game.library,
            instance=session,
            presentation=_presentation("Europe/Prague"),
        )["timestamp_start"]
    )
    hidden = re.search(r'name="timestamp_start" value="([^"]*)"', rendered)
    assert hidden is not None
    assert hidden.group(1) == "2026-07-28T15:37:00+09:00"


def test_an_unusable_stored_zone_falls_back_to_the_display_zone(db):
    game = Game.objects.create(library=_library(), name="Hades")
    session = Session.objects.create(
        game=game,
        timestamp_start=datetime(2026, 7, 28, 6, 37, tzinfo=UTC),
        timestamp_start_timezone="Not/AZone",
    )
    rendered = str(
        SessionForm(
            library=game.library,
            instance=session,
            presentation=_presentation("Europe/Prague"),
        )["timestamp_start"]
    )
    hidden = re.search(r'name="timestamp_start" value="([^"]*)"', rendered)
    assert hidden is not None
    assert hidden.group(1) == "2026-07-28T08:37:00+02:00"


def test_session_datetime_widgets_name_their_paired_zone_row(db):
    library = _library()
    form = SessionForm(library=library, presentation=_presentation("Europe/Prague"))
    assert 'zone-field-name="timestamp_start_timezone"' in str(form["timestamp_start"])
    assert 'zone-field-name="timestamp_end_timezone"' in str(form["timestamp_end"])


def test_naive_input_is_interpreted_in_the_selected_zone(db):
    """A DST-gap submission posts the bare wall clock; the digits were typed
    against the *picked* zone, so that is the zone they bind in."""
    user = get_user_model().objects.create_user(username="tester", password="pw")
    game = Game.objects.create(library=user.library, name="Hades")
    UserPreferences.objects.filter(user=user).update(display_time_zone="Europe/Prague")
    settings_resolver.clear_cache()
    captured: dict[str, object] = {}

    def response(request):
        form = SessionForm(
            library=user.library,
            data={
                **_session_form_data(game, "2026-07-28T15:37"),
                "timestamp_start_timezone": "Asia/Tokyo",
            },
            presentation=_presentation("Europe/Prague"),
        )
        assert form.is_valid(), form.errors
        captured["timestamp_start"] = form.cleaned_data["timestamp_start"]
        return HttpResponse()

    request = RequestFactory().post("/tracker/session/add")
    request.user = user
    TimezoneActivationMiddleware(response)(request)

    assert captured["timestamp_start"] == datetime(2026, 7, 28, 6, 37, tzinfo=UTC)


def test_naive_gap_in_the_selected_zone_is_rejected_naming_it(db):
    """2026-03-08 02:30 does not exist in America/New_York. The account zone
    (Tokyo, no DST) would accept it happily — the rejection must come from the
    selected zone, and name it."""
    user = get_user_model().objects.create_user(username="tester", password="pw")
    game = Game.objects.create(library=user.library, name="Hades")
    UserPreferences.objects.filter(user=user).update(display_time_zone="Asia/Tokyo")
    settings_resolver.clear_cache()
    captured: dict[str, object] = {}

    def response(request):
        form = SessionForm(
            library=user.library,
            data={
                **_session_form_data(game, "2026-03-08T02:30"),
                "timestamp_start_timezone": "America/New_York",
            },
            presentation=_presentation("Asia/Tokyo"),
        )
        captured["errors"] = form.errors.as_text()
        return HttpResponse()

    request = RequestFactory().post("/tracker/session/add")
    request.user = user
    TimezoneActivationMiddleware(response)(request)

    assert "couldn’t be interpreted in time zone America/New_York" in str(
        captured["errors"]
    )


def test_naive_value_valid_in_the_selected_zone_survives_an_account_zone_gap(db):
    """The mirror case: 02:30 on 2026-03-08 is the account zone's spring-forward
    gap, but a perfectly ordinary Tokyo wall clock — it must bind, not error."""
    user = get_user_model().objects.create_user(username="tester", password="pw")
    game = Game.objects.create(library=user.library, name="Hades")
    UserPreferences.objects.filter(user=user).update(
        display_time_zone="America/New_York"
    )
    settings_resolver.clear_cache()
    captured: dict[str, object] = {}

    def response(request):
        form = SessionForm(
            library=user.library,
            data={
                **_session_form_data(game, "2026-03-08T02:30"),
                "timestamp_start_timezone": "Asia/Tokyo",
            },
            presentation=_presentation("America/New_York"),
        )
        assert form.is_valid(), form.errors
        captured["timestamp_start"] = form.cleaned_data["timestamp_start"]
        return HttpResponse()

    request = RequestFactory().post("/tracker/session/add")
    request.user = user
    TimezoneActivationMiddleware(response)(request)

    assert captured["timestamp_start"] == datetime(2026, 3, 7, 17, 30, tzinfo=UTC)
