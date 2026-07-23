from datetime import UTC, datetime

from django.contrib.auth import get_user_model
from django.http import HttpResponse
from django.test import RequestFactory

from common.middleware import TimezoneActivationMiddleware
from games.forms import SessionForm
from games.models import Game, UserPreferences
from timetracker import settings_resolver


def _session_form_data(game: Game, timestamp_start: str) -> dict[str, str]:
    return {
        "game": str(game.pk),
        "timestamp_start": timestamp_start,
        "timestamp_end": "",
        "duration_manual": "",
        "device": "",
        "note": "",
    }


def test_datetime_local_session_input_is_interpreted_in_the_account_timezone(db):
    user = get_user_model().objects.create_user(username="tester", password="pw")
    game = Game.objects.create(name="Hades")
    UserPreferences.objects.create(user=user, display_time_zone="Pacific/Kiritimati")
    settings_resolver.clear_cache()
    captured: dict[str, object] = {}

    def response(request):
        form = SessionForm(data=_session_form_data(game, "2026-01-01T10:30"))
        assert form.is_valid(), form.errors
        captured["timestamp_start"] = form.cleaned_data["timestamp_start"]
        return HttpResponse()

    request = RequestFactory().post("/tracker/session/add")
    request.user = user
    TimezoneActivationMiddleware(response)(request)

    assert captured["timestamp_start"] == datetime(2025, 12, 31, 20, 30, tzinfo=UTC)


def test_datetime_local_dst_gap_is_rejected_in_the_account_timezone(db):
    user = get_user_model().objects.create_user(username="tester", password="pw")
    game = Game.objects.create(name="Hades")
    UserPreferences.objects.create(user=user, display_time_zone="America/New_York")
    settings_resolver.clear_cache()
    captured: dict[str, object] = {}

    def response(request):
        form = SessionForm(data=_session_form_data(game, "2026-03-08T02:30"))
        captured["errors"] = form.errors.as_text()
        return HttpResponse()

    request = RequestFactory().post("/tracker/session/add")
    request.user = user
    TimezoneActivationMiddleware(response)(request)

    assert "couldn’t be interpreted in time zone America/New_York" in str(
        captured["errors"]
    )
