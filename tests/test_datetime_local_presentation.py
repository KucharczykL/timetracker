from datetime import UTC, datetime

from django import forms
from django.contrib.auth import get_user_model
from django.http import HttpResponse
from django.test import RequestFactory

from common.middleware import TimezoneActivationMiddleware
from games.forms import GameStatusChangeForm, SessionForm, custom_datetime_widget
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


def test_session_and_game_status_change_datetime_fields_stay_native_pending_485():
    """Pin: issue #485 gives Purchase/PlayEvent DateField inputs a
    presentation-aware segmented `<date-picker>`, but explicitly excludes
    Session.timestamp_start/timestamp_end and GameStatusChange.timestamp —
    these are DateTimeField (not DateField) rendered via native
    `type="datetime-local"`, and need a dedicated time-segment design (plus
    integration with `session-timestamp-buttons.ts`) tracked as a follow-up:
    https://github.com/KucharczykL/timetracker/issues/511. This test documents
    the decision and fails loudly if a future change silently swaps these
    widgets without updating (or closing) that issue."""
    session_form = SessionForm()
    for field_name in ("timestamp_start", "timestamp_end"):
        widget = session_form.fields[field_name].widget
        assert isinstance(widget, forms.DateTimeInput)
        assert widget.input_type == "datetime-local"
        assert widget.format == custom_datetime_widget.format

    status_change_form = GameStatusChangeForm()
    widget = status_change_form.fields["timestamp"].widget
    assert isinstance(widget, forms.DateTimeInput)
    assert widget.input_type == "datetime-local"
    assert widget.format == custom_datetime_widget.format
