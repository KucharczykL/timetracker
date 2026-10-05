"""A redirect in dialog mode becomes a result."""

import uuid

import pytest
from django.contrib import messages
from django.contrib.messages.middleware import MessageMiddleware
from django.contrib.sessions.middleware import SessionMiddleware
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.test import Client, RequestFactory
from django.urls import URLPattern, URLResolver, get_resolver, reverse

from common.form_dialog import FORM_DIALOG_HEADER
from common.returns import action_url
from games.form_dialog_middleware import FormDialogResultMiddleware, dialog_result
from games.models import Device
from games.toast_middleware import EVENTS_HEADER, ToastMessagesMiddleware
from games.views.returns import READ_ONLY
from tests.devices import create_device
from tests.tracked_games import create_tracked_game

DIALOG_HEADERS = {FORM_DIALOG_HEADER: "1", "Accept": "application/json"}
SERVER = "http://testserver"


@pytest.fixture
def logged_in(owned_user) -> Client:
    client = Client()
    client.force_login(owned_user)
    return client


def _dialog_request(path: str = "/") -> HttpRequest:
    request = RequestFactory().post(path, headers=DIALOG_HEADERS)
    SessionMiddleware(lambda request: HttpResponse()).process_request(request)
    MessageMiddleware(lambda request: HttpResponse()).process_request(request)
    return request


def _answered(request: HttpRequest, response: HttpResponse) -> HttpResponse:
    return FormDialogResultMiddleware(lambda request: response)(request)


@pytest.mark.django_db(transaction=True)
def test_removal_from_a_list_is_done_with_its_undo(logged_in, owned_library):
    device = create_device(owned_library)
    origin = reverse("games:list_devices")
    response = logged_in.post(
        action_url("games:remove_device", device.pk, origin=origin),
        headers=DIALOG_HEADERS,
    )

    assert response.status_code == 200
    assert response["Cache-Control"] == "no-store"
    answer = response.json()
    assert answer["kind"] == "done"
    assert answer["url"] == SERVER + origin
    [message] = answer["messages"]
    assert message["action"]["label"] == "Undo"
    assert EVENTS_HEADER not in response
    assert Device.objects.get(pk=device.pk).removed_at is not None


@pytest.mark.django_db(transaction=True)
def test_removal_from_the_game_page_is_done_on_the_list(logged_in, owned_library):
    game = create_tracked_game(owned_library, "Outer Wilds")
    origin = game.get_absolute_url()
    response = logged_in.post(
        action_url("games:remove_game", game.pk, origin=origin),
        headers=DIALOG_HEADERS,
    )

    answer = response.json()
    assert answer["kind"] == "done"
    assert answer["url"] == SERVER + reverse("games:list_games")


@pytest.mark.django_db(transaction=True)
def test_add_game_then_library_continues(logged_in, game_post):
    response = logged_in.post(
        reverse("games:add_game"),
        {**game_post("Outer Wilds"), "submit_and_add_to_library": ""},
        headers=DIALOG_HEADERS,
    )

    answer = response.json()
    assert answer == {"kind": "continue", "url": answer["url"]}
    resolved = get_resolver().resolve(answer["url"].removeprefix(SERVER).split("?")[0])
    assert resolved.view_name == "games:add_library_entry"


@pytest.mark.django_db
def test_sign_in_continues(client):
    response = client.get(reverse("games:add_device"), headers=DIALOG_HEADERS)

    answer = response.json()
    assert answer["kind"] == "continue"
    assert answer["url"].startswith(SERVER + reverse("login"))


def test_an_off_origin_target_passes_through():
    request = _dialog_request()
    redirect = HttpResponseRedirect("https://elsewhere.test/games")

    assert _answered(request, redirect) is redirect


def test_a_page_request_is_untouched():
    request = RequestFactory().post("/")
    redirect = HttpResponseRedirect("/devices")

    assert _answered(request, redirect) is redirect


def test_continue_leaves_the_queue():
    request = _dialog_request()
    messages.success(request, "Saved")

    assert dialog_result(request, "/login/") == {
        "kind": "continue",
        "url": SERVER + "/login/",
    }
    assert len(messages.get_messages(request)) == 1


def test_the_toast_middleware_skips_a_dialog_request():
    request = _dialog_request()
    messages.success(request, "Saved")
    response = ToastMessagesMiddleware(lambda request: HttpResponse())(request)

    assert EVENTS_HEADER not in response
    assert len(messages.get_messages(request)) == 1


#: Sample values per path converter.
_SAMPLES = {
    "int": 1,
    "string": "x",
    "slug": "x",
    "path": "x",
    "uuid": uuid.uuid7(),
    "uuidv7": uuid.uuid7(),
}


def _named_routes(
    patterns: list[URLPattern | URLResolver], namespace: str = ""
) -> list[tuple[str, URLPattern]]:
    found: list[tuple[str, URLPattern]] = []
    for pattern in patterns:
        if isinstance(pattern, URLResolver):
            inner = (
                f"{namespace}{pattern.namespace}:" if pattern.namespace else namespace
            )
            found.extend(_named_routes(pattern.url_patterns, inner))
        elif pattern.name is not None:
            found.append((f"{namespace}{pattern.name}", pattern))
    return found


@pytest.mark.parametrize(
    ("name", "pattern"),
    _named_routes(get_resolver().url_patterns),
    ids=lambda value: value if isinstance(value, str) else "",
)
def test_every_route_classifies(name, pattern):
    converters = getattr(pattern.pattern, "converters", {})
    kwargs = {
        key: _SAMPLES[type(converter).__name__.removesuffix("Converter").lower()]
        for key, converter in converters.items()
    }
    path = reverse(name, kwargs=kwargs)
    answer = dialog_result(_dialog_request(), path)

    assert answer is not None
    assert answer["kind"] == ("done" if name in READ_ONLY else "continue")


@pytest.mark.django_db(transaction=True)
def test_a_rewritten_token_survives_sign_in(owned_user):
    client = Client(enforce_csrf_checks=True)
    client.get(reverse("login"))
    signed_out = client.cookies["csrftoken"].value
    client.post(
        reverse("login"),
        {
            "username": owned_user.username,
            "password": "p",
            "csrfmiddlewaretoken": signed_out,
        },
        headers=DIALOG_HEADERS,
    )
    rotated = client.cookies["csrftoken"].value
    assert rotated != signed_out

    response = client.post(
        reverse("games:add_device"),
        {
            "name": "Deck",
            "type": Device.UNKNOWN,
            "submission": str(uuid.uuid7()),
            "csrfmiddlewaretoken": rotated,
        },
        headers=DIALOG_HEADERS,
    )

    assert response.status_code == 200
    assert response.json()["kind"] == "done"
