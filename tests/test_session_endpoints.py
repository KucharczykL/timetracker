import logging
from datetime import timedelta
from typing import NamedTuple

import pytest
from devices import create_device, end_device_access, remove_device
from django.contrib.messages import get_messages
from django.urls import reverse
from django.utils import timezone
from session_rows import session_row, tracked_run

from games.models import Game, Platform, PlayerSession

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def _prague_calendar(owned_user, set_user_setting):
    """The rows `session_rows` seeds count their days in Prague."""
    set_user_setting(owned_user, "DISPLAY_TIME_ZONE", "Europe/Prague")


@pytest.fixture
def auth_client(client, owned_user):
    client.force_login(owned_user)
    return client


@pytest.fixture
def running_session(owned_library):
    platform = Platform.objects.create(name="PC")
    game = Game.objects.create(library=owned_library, name="Hades", platform=platform)
    device = create_device(library=owned_library, name="Deck")
    return session_row(game, device=device, started_at=timezone.now())


def _game_of(session):
    return session.playthrough.player_game.game


def test_resume_is_post_only(auth_client, running_session):
    url = reverse("games:resume_session", args=[_game_of(running_session).pk])
    assert auth_client.get(url).status_code == 405


def test_resume_post_starts_a_session_on_the_run_and_redirects(
    auth_client, running_session
):
    url = reverse("games:resume_session", args=[_game_of(running_session).pk])
    before = PlayerSession.objects.count()
    response = auth_client.post(url)
    assert response.status_code == 302
    assert response["Location"] == reverse("games:list_sessions")
    assert PlayerSession.objects.count() == before + 1
    clone = PlayerSession.objects.latest("created_at")
    assert clone.playthrough_id == running_session.playthrough_id
    assert clone.device_id == running_session.device_id
    assert clone.ended_at is None


class Resumed(NamedTuple):
    session: PlayerSession
    notices: list[str]


def _resume(auth_client, game) -> Resumed:
    before = set(PlayerSession.objects.values_list("pk", flat=True))
    response = auth_client.post(reverse("games:resume_session", args=[game.pk]))
    assert response.status_code == 302
    (session,) = PlayerSession.objects.exclude(pk__in=before)
    assert session.ended_at is None
    notices = [str(message) for message in get_messages(response.wsgi_request)]
    return Resumed(session, notices)


@pytest.fixture
def default_device(owned_library):
    device = create_device(library=owned_library, name="Desktop")
    owned_library.preferences.set_default_device(device)
    return device


@pytest.fixture
def games_errors(capture_games_logger):
    with capture_games_logger() as captured:
        captured.set_level(logging.ERROR, logger="games")
        yield captured


def test_resume_states_no_removed_device(auth_client, running_session, games_errors):
    remove_device(running_session.device)

    resumed = _resume(auth_client, _game_of(running_session))

    assert resumed.session.device_id is None
    assert resumed.notices == ["Resumed with no device; Deck is no longer held."]
    assert games_errors.records == []


def test_resume_falls_back_to_the_default_device(
    auth_client, running_session, default_device
):
    PlayerSession.objects.filter(pk=running_session.pk).update(emulated=True)
    remove_device(running_session.device)

    resumed = _resume(auth_client, _game_of(running_session))

    assert resumed.session.device_id == default_device.pk
    assert resumed.session.emulated is False
    assert resumed.notices == ["Resumed on Desktop; Deck is no longer held."]


def test_resume_does_not_carry_an_ended_device(
    auth_client, running_session, games_errors
):
    end_device_access(running_session.device)

    resumed = _resume(auth_client, _game_of(running_session))

    assert resumed.session.device_id is None
    assert resumed.notices == ["Resumed with no device; Deck is no longer held."]
    assert games_errors.records == []


def test_resume_keeps_a_held_device_without_a_notice(auth_client, running_session):
    resumed = _resume(auth_client, _game_of(running_session))

    assert resumed.session.device_id == running_session.device_id
    assert resumed.notices == []


def test_resume_keeps_no_device_and_the_flag(
    auth_client, running_session, default_device
):
    PlayerSession.objects.filter(pk=running_session.pk).update(
        device=None, emulated=True
    )

    resumed = _resume(auth_client, _game_of(running_session))

    assert resumed.session.device_id is None
    assert resumed.session.emulated is True
    assert resumed.notices == []


def test_resume_without_a_session_takes_the_default(
    auth_client, owned_library, default_device
):
    game = Game.objects.create(library=owned_library, name="Celeste")
    tracked_run(owned_library, game)

    resumed = _resume(auth_client, game)

    assert resumed.session.device_id == default_device.pk
    assert resumed.session.emulated is False
    assert resumed.notices == []


def test_resume_reads_the_latest_session(auth_client, owned_library, running_session):
    older = create_device(library=owned_library, name="Laptop")
    older_start = running_session.started_at - timedelta(days=1)
    session_row(
        _game_of(running_session),
        device=older,
        started_at=older_start,
        ended_at=older_start + timedelta(hours=1),
    )

    resumed = _resume(auth_client, _game_of(running_session))

    assert resumed.session.device_id == running_session.device_id


def test_resume_logs_a_foreign_device(
    auth_client, running_session, django_user_model, default_device, games_errors
):
    stranger = django_user_model.objects.create_user(username="stranger")
    foreign = create_device(library=stranger.library, name="Foreign")
    PlayerSession.objects.filter(pk=running_session.pk).update(device=foreign)

    resumed = _resume(auth_client, _game_of(running_session))

    assert resumed.session.device_id == default_device.pk
    assert resumed.notices == []
    (record,) = games_errors.records
    assert str(running_session.pk) in record.getMessage()
    assert str(_game_of(running_session).pk) in record.getMessage()
