import pytest
from django.urls import reverse
from django.utils import timezone
from session_rows import session_row

from games.models import Device, Game, Platform, PlayerSession

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
    device = Device.objects.create(library=owned_library, name="Deck")
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
