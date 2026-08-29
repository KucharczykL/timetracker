"""The confirm-then-act flow, independent of what the action does."""

import pytest
from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory
from django.urls import reverse

from common.returns import action_url
from games.models import Game
from games.views.removal import confirm_and_apply

# Any catalog route takes a UUIDv7; the value never reaches the database.
GAME_ID = "018f5e66-e800-7000-8000-000000000001"
SESSION_ID = "018f5e66-e800-7000-8000-000000000002"
CONFIRM_URL = "/tracker/platform/1/remove"


def _request(method: str, url: str = CONFIRM_URL):
    factory = RequestFactory()
    request = getattr(factory, method)(url)
    request.user = AnonymousUser()
    return request


def _apply(request, performed: list[str], **overrides):
    return confirm_and_apply(
        request,
        action=lambda: performed.append("ran"),
        title="Reset start time",
        message="Reset the start time to now?",
        confirm_label="Reset to now",
        fallback="games:list_sessions",
        **overrides,
    )


def test_get_renders_confirmation_without_running_the_action(db):
    performed: list[str] = []

    response = _apply(_request("get"), performed)

    assert response.status_code == 200
    assert "Reset to now" in response.content.decode()
    assert performed == []


def test_post_runs_the_action_once_and_redirects(db):
    performed: list[str] = []

    response = _apply(_request("post"), performed)

    assert performed == ["ran"]
    assert response.status_code == 302
    assert response["Location"] == reverse("games:list_sessions")


def test_origin_rides_through_the_confirmation(db):
    origin = f"{reverse('games:list_sessions')}?page=2"
    confirm_url = action_url("games:remove_session", SESSION_ID, origin=origin)

    body = _apply(_request("get", confirm_url), []).content.decode()
    assert "origin=%2Ftracker%2Fsession%2Flist%3Fpage%3D2" in body

    response = _apply(_request("post", confirm_url), [])
    assert response["Location"] == origin


def test_reject_refuses_an_origin_naming_the_acted_on_page(db):
    origin = reverse("games:view_game", args=[GAME_ID, "doomed-game"])
    confirm_url = action_url("games:remove_game", GAME_ID, origin=origin)

    response = _apply(_request("post", confirm_url), [], reject=origin)

    assert response["Location"] == reverse("games:list_sessions")


@pytest.mark.django_db(transaction=True)
def test_confirm_and_remove_stamps_rather_than_destroys(
    client, owned_user, owned_library
):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    client.force_login(owned_user)

    client.post(reverse("games:remove_game", args=[game.pk]))

    game.refresh_from_db()
    assert game.removed_at is not None


@pytest.mark.django_db(transaction=True)
def test_the_page_labels_its_button_remove(client, owned_user, owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    client.force_login(owned_user)

    page = client.get(reverse("games:remove_game", args=[game.pk])).content.decode()

    assert "Remove" in page
    assert "kept out of sight" not in page
    assert "permanently" not in page.lower()
