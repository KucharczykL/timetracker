import logging

import pytest
from devices import create_device, end_device_access, remove_device
from django.urls import reverse
from django.utils import timezone
from session_rows import session_row

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


def _resumed(auth_client, session):
    before = set(PlayerSession.objects.values_list("pk", flat=True))
    response = auth_client.post(
        reverse("games:resume_session", args=[_game_of(session).pk])
    )
    assert response.status_code == 302
    (resumed,) = PlayerSession.objects.exclude(pk__in=before)
    assert resumed.ended_at is None
    return resumed


def test_resume_states_no_removed_device(auth_client, running_session):
    remove_device(running_session.device)

    assert _resumed(auth_client, running_session).device_id is None


def test_resume_falls_back_to_the_default_device(
    auth_client, owned_library, running_session
):
    PlayerSession.objects.filter(pk=running_session.pk).update(emulated=True)
    remove_device(running_session.device)
    default = create_device(library=owned_library, name="Desktop")
    owned_library.preferences.set_default_device(default)

    resumed = _resumed(auth_client, running_session)

    assert resumed.device_id == default.pk
    assert resumed.emulated is False


def test_resume_does_not_carry_an_ended_device(auth_client, running_session):
    end_device_access(running_session.device)

    assert _resumed(auth_client, running_session).device_id is None


def test_resume_logs_a_foreign_device(
    auth_client, running_session, django_user_model, capture_games_logger
):
    stranger = django_user_model.objects.create_user(username="stranger")
    foreign = create_device(library=stranger.library, name="Foreign")
    PlayerSession.objects.filter(pk=running_session.pk).update(device=foreign)

    with capture_games_logger() as captured:
        captured.set_level(logging.ERROR, logger="games")
        resumed = _resumed(auth_client, running_session)

    assert resumed.device_id is None
    assert any("holds no device" in record.getMessage() for record in captured.records)
