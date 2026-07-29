"""The confirm-then-act flow, independent of what the action does."""

from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory
from django.urls import reverse

from common.returns import action_url
from games.models import Platform
from games.views.deletion import confirm_and_apply, confirm_and_delete

CONFIRM_URL = "/tracker/platform/1/delete"


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
    confirm_url = action_url("games:delete_session", 1, origin=origin)

    body = _apply(_request("get", confirm_url), []).content.decode()
    assert "origin=%2Ftracker%2Fsession%2Flist%3Fpage%3D2" in body

    response = _apply(_request("post", confirm_url), [])
    assert response["Location"] == origin


def test_reject_refuses_an_origin_naming_the_acted_on_page(db):
    origin = reverse("games:view_game", args=[1])
    confirm_url = action_url("games:delete_game", 1, origin=origin)

    response = _apply(_request("post", confirm_url), [], reject=origin)

    assert response["Location"] == reverse("games:list_sessions")


def test_confirm_and_delete_still_deletes(db):
    platform = Platform.objects.create(name="Doomed")

    response = confirm_and_delete(
        _request("post"),
        platform,
        title="Delete platform",
        message="Delete it?",
        fallback="games:list_platforms",
    )

    assert not Platform.objects.filter(pk=platform.pk).exists()
    assert response["Location"] == reverse("games:list_platforms")


def test_confirm_and_delete_still_labels_its_button_delete(db):
    platform = Platform.objects.create(name="Kept")

    body = confirm_and_delete(
        _request("get"),
        platform,
        title="Delete platform",
        message="Delete it?",
        fallback="games:list_platforms",
    ).content.decode()

    assert "Delete" in body
    assert Platform.objects.filter(pk=platform.pk).exists()
