"""Timezone binding for the Session/GameStatusChange datetime fields.

These fields used to be native ``<input type="datetime-local">`` and are now
the segmented ``<date-time-field>`` widget (issue #511). The widget submits an
offset-qualified wall clock, but a submission Django rejects — a DST gap — posts
back the bare wall clock, and *that* is the shape whose interpretation these
tests pin: it is read in the account's timezone, not the server's.
"""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.http import HttpResponse
from django.test import RequestFactory

from common.date_time_presentation import (
    DEFAULT_DATE_TIME_FORMAT_PROFILE,
    DateTimePresentation,
)
from common.middleware import TimezoneActivationMiddleware
from games.forms import DateTimeFieldWidget, GameStatusChangeForm, SessionForm
from games.models import Game, UserPreferences
from timetracker import settings_resolver


def _presentation(time_zone: str) -> DateTimePresentation:
    return DateTimePresentation(
        DEFAULT_DATE_TIME_FORMAT_PROFILE, "en-us", ZoneInfo(time_zone)
    )


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
    game = Game.objects.create(name="Hades")
    UserPreferences.objects.create(user=user, display_time_zone="Pacific/Kiritimati")
    settings_resolver.clear_cache()
    captured: dict[str, object] = {}

    def response(request):
        form = SessionForm(
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
    game = Game.objects.create(name="Hades")
    UserPreferences.objects.create(user=user, display_time_zone="America/New_York")
    settings_resolver.clear_cache()
    captured: dict[str, object] = {}

    def response(request):
        form = SessionForm(
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
    game = Game.objects.create(name="Hades")
    UserPreferences.objects.create(user=user, display_time_zone="Pacific/Kiritimati")
    settings_resolver.clear_cache()
    captured: dict[str, object] = {}

    def response(request):
        form = SessionForm(
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


def test_session_and_game_status_change_use_the_segmented_datetime_widget(db):
    """Issue #511: these were the last native date/time controls in the app."""
    presentation = _presentation("UTC")
    session_form = SessionForm(presentation=presentation)
    for field_name in ("timestamp_start", "timestamp_end"):
        assert isinstance(
            session_form.fields[field_name].widget, DateTimeFieldWidget
        ), field_name

    status_change_form = GameStatusChangeForm(presentation=presentation)
    assert isinstance(
        status_change_form.fields["timestamp"].widget, DateTimeFieldWidget
    )
