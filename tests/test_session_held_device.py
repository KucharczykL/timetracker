"""Edit Session keeps a removed device it holds."""

import logging
import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from devices import create_device, remove_device
from django.urls import reverse

from common.date_time_presentation import (
    DEFAULT_DATE_TIME_FORMAT_PROFILE,
    DateTimePresentation,
)
from games.commands.playersession import CreateSession, TimedTiming
from games.events.dispatch import dispatch
from games.forms import DEVICE_GONE, SessionForm
from games.models import Game, LibraryEvent, PlayerSession, Playthrough
from games.reads.calendar import calendar_day_zone

pytestmark = pytest.mark.django_db(transaction=True)

PRESENTATION = DateTimePresentation(
    DEFAULT_DATE_TIME_FORMAT_PROFILE, "en-us", ZoneInfo("UTC")
)
START = datetime(2026, 1, 1, 12, tzinfo=UTC)


@pytest.fixture
def logged_in(client, owned_user):
    client.force_login(owned_user)
    return client


@pytest.fixture
def other_library(django_user_model):
    return django_user_model.objects.create_user(
        username="other-owner", password="p"
    ).library


@pytest.fixture
def game(owned_library) -> Game:
    return Game.objects.create(library=owned_library, name="Outer Wilds")


@pytest.fixture
def run(game) -> Playthrough:
    return Playthrough.objects.get(player_game__game=game)


def a_session(library, run, device) -> PlayerSession:
    dispatch(
        CreateSession(
            playthrough_id=run.pk,
            timing=TimedTiming(
                started_at=START,
                ended_at=START + timedelta(hours=1),
                day_zone=calendar_day_zone(library).key,
            ),
            device_id=device.pk,
            implies_played=False,
        ),
        actor=library.user,
        library=library,
        idempotency_key=str(uuid.uuid7()),
    )
    return PlayerSession.objects.get()


def session_post(game, run, **changes) -> dict[str, str]:
    return {
        "game": str(game.pk),
        "playthrough": str(run.pk),
        "release": "",
        "started_at": "2026-01-01 12:00",
        "started_at_zone": "",
        "ended_at": "2026-01-01 13:00",
        "ended_at_zone": "",
        "duration": "",
        "note": "",
        **changes,
    }


def written_since(count: int) -> list[str]:
    return list(
        LibraryEvent.objects.order_by("pk")[count:].values_list("event_type", flat=True)
    )


def test_an_edit_keeps_a_held_removed_device(logged_in, owned_library, game, run):
    device = create_device(owned_library, name="Old PC")
    session = a_session(owned_library, run, device)
    remove_device(device)
    url = reverse("games:edit_session", args=[session.pk])

    page = logged_in.get(url).content.decode()
    assert "Old PC (removed)" in page
    assert f'<input name="device" value="{device.pk}" type="hidden">' in page
    events = LibraryEvent.objects.count()
    response = logged_in.post(
        url, session_post(game, run, device=str(device.pk), note="kept")
    )

    assert response.status_code == 302
    session.refresh_from_db()
    assert (session.note, session.device_id) == ("kept", device.pk)
    assert written_since(events) == ["library.playersession.note_changed"]


def test_an_edit_clears_a_held_removed_device(logged_in, owned_library, game, run):
    device = create_device(owned_library, name="Old PC")
    session = a_session(owned_library, run, device)
    remove_device(device)
    events = LibraryEvent.objects.count()

    response = logged_in.post(
        reverse("games:edit_session", args=[session.pk]),
        session_post(game, run, device=""),
    )

    assert response.status_code == 302
    session.refresh_from_db()
    assert session.device_id is None
    assert written_since(events) == ["library.playersession.device_changed"]


def test_a_new_session_refuses_a_removed_device(owned_library, game, run):
    device = remove_device(create_device(owned_library, name="Old PC"))
    form = SessionForm(
        data=session_post(game, run, device=str(device.pk)),
        library=owned_library,
        presentation=PRESENTATION,
    )

    assert not form.is_valid()
    assert form.errors["device"] == [DEVICE_GONE]


def test_another_sessions_removed_device_is_refused(owned_library, game, run):
    held = create_device(owned_library, name="Old PC")
    session = a_session(owned_library, run, held)
    other = remove_device(create_device(owned_library, name="Older PC"))
    form = SessionForm(
        data=session_post(game, run, device=str(other.pk)),
        library=owned_library,
        presentation=PRESENTATION,
        instance=session,
    )

    assert not form.is_valid()
    assert form.errors["device"] == [DEVICE_GONE]


def test_a_held_device_of_another_library_is_logged(
    owned_library, other_library, game, run, capture_games_logger
):
    foreign = create_device(other_library, name="Their PC")
    session = a_session(owned_library, run, create_device(owned_library))
    session.device_id = foreign.pk

    with capture_games_logger() as caplog:
        SessionForm(library=owned_library, presentation=PRESENTATION, instance=session)

    [record] = caplog.records
    assert record.levelno == logging.ERROR
    assert str(foreign.pk) in record.getMessage()
