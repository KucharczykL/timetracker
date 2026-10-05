"""A redirect in dialog mode becomes a result."""

import json
import re
import uuid

import pytest
from devices import create_device
from django.contrib import messages
from django.contrib.auth.models import AnonymousUser
from django.contrib.messages.middleware import MessageMiddleware
from django.contrib.sessions.middleware import SessionMiddleware
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.test import Client, RequestFactory
from django.urls import URLPattern, URLResolver, get_resolver, reverse
from tracked_games import create_tracked_game

from common.components import Div, Fragment
from common.form_dialog import FORM_DIALOG_HEADER, CreatedRedirect
from common.layout import render_page
from common.returns import action_url
from games.form_dialog_middleware import FormDialogResultMiddleware, dialog_result
from games.forms import game_option
from games.models import Device, Game
from games.toast_middleware import EVENTS_HEADER, ToastMessagesMiddleware
from games.views.returns import READ_ONLY

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


def _page_messages(client: Client, url: str) -> list[object]:
    html = client.get(url).content.decode()
    found = re.search(
        r'<script id="django-messages" type="application/json">(.*?)</script>', html
    )
    assert found is not None
    return json.loads(found.group(1))


@pytest.mark.django_db(transaction=True)
def test_removal_from_a_list_is_done_with_its_undo(logged_in, owned_library):
    device = create_device(owned_library)
    origin = reverse("games:list_devices") + "?filter=%7B%7D&page=2"
    response = logged_in.post(
        action_url("games:remove_device", device.pk, origin=origin),
        headers=DIALOG_HEADERS,
    )

    assert response.status_code == 200
    assert response["Cache-Control"] == "no-store"
    assert FORM_DIALOG_HEADER in response["Vary"]
    answer = response.json()
    assert answer["kind"] == "done"
    assert answer["url"] == SERVER + origin
    [message] = answer["messages"]
    assert message["action"]["label"] == "Undo"
    assert EVENTS_HEADER not in response
    assert Device.objects.get(pk=device.pk).removed_at is not None
    # Handed to the dialog, so the reload shows none.
    assert _page_messages(logged_in, origin) == []


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


@pytest.mark.django_db(transaction=True)
def test_a_continue_hands_the_queue_to_the_next_answer(
    logged_in, owned_library, game_post
):
    device = create_device(owned_library, "Deck")
    logged_in.post(
        action_url(
            "games:remove_device", device.pk, origin=reverse("games:list_devices")
        )
    )
    continued = logged_in.post(
        reverse("games:add_game"),
        {**game_post("Outer Wilds"), "submit_and_add_to_library": ""},
        headers=DIALOG_HEADERS,
    ).json()
    assert continued["kind"] == "continue"

    answer = logged_in.get(continued["url"], headers=DIALOG_HEADERS).json()

    assert answer["kind"] == "page"
    assert [message["message"] for message in answer["messages"]] == [
        "Deck removed from your library."
    ]
    assert _page_messages(logged_in, reverse("games:list_devices")) == []


#: Pages a form dialog presents.
_FORM_ROUTES = (
    "games:add_device",
    "games:add_platform",
    "games:add_game",
    "games:add_session",
    "games:add_playthrough",
)


@pytest.mark.django_db
@pytest.mark.parametrize("route", _FORM_ROUTES)
def test_a_form_page_answers_in_dialog_mode_under_debug(
    logged_in, debug_page_rendering, route
):
    response = logged_in.get(reverse(route), headers=DIALOG_HEADERS)

    assert response.status_code == 200
    assert response.json()["kind"] == "page"


def test_dialog_content_repeating_an_id_is_refused(settings):
    settings.DEBUG = True
    request = _dialog_request()
    request.user = AnonymousUser()
    content = Fragment(Div(id="twice"), Div(id="twice"))

    with pytest.raises(ValueError, match="twice"):
        render_page(request, content, title="T")


def test_dialog_content_is_unchecked_outside_debug():
    request = _dialog_request()
    request.user = AnonymousUser()
    content = Fragment(Div(id="twice"), Div(id="twice"))

    assert render_page(request, content, title="T").status_code == 200


@pytest.mark.django_db
def test_sign_in_continues(client):
    response = client.get(reverse("games:add_device"), headers=DIALOG_HEADERS)

    assert response["Cache-Control"] == "no-store"
    assert FORM_DIALOG_HEADER in response["Vary"]
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


@pytest.mark.django_db(transaction=True)
def test_a_page_answer_uses_up_the_queue(logged_in, owned_library):
    device = create_device(owned_library, "Deck")
    remove = action_url(
        "games:remove_device", device.pk, origin=reverse("games:list_devices")
    )
    logged_in.post(remove)
    answer = logged_in.get(reverse("games:add_device"), headers=DIALOG_HEADERS).json()

    assert [message["message"] for message in answer["messages"]] == [
        "Deck removed from your library."
    ]
    assert _page_messages(logged_in, reverse("games:list_devices")) == []


def test_a_redirect_without_location_passes_through():
    request = _dialog_request()
    response = HttpResponse(status=302)

    assert _answered(request, response) is response


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
def test_every_redirect_status_becomes_a_result(status):
    request = _dialog_request()
    response = HttpResponse(status=status, headers={"Location": "/login/"})

    assert _answered(request, response).status_code == 200


def test_an_unresolvable_path_continues():
    assert dialog_result(_dialog_request(), "/nowhere/at/all") == {
        "kind": "continue",
        "url": SERVER + "/nowhere/at/all",
    }


def test_the_result_keeps_the_redirect_cookies():
    request = _dialog_request()
    redirect = HttpResponseRedirect("/login/")
    redirect.set_cookie("marker", "kept")

    assert _answered(request, redirect).cookies["marker"].value == "kept"


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


OPTION = {"value": "1", "label": "Outer Wilds (PC)", "data": {}}


def test_a_tagged_redirect_to_a_read_only_page_is_created():
    request = _dialog_request()
    messages.success(request, "Saved")
    redirect = CreatedRedirect(reverse("games:list_games"), option=OPTION)

    assert json.loads(_answered(request, redirect).content) == {
        "kind": "created",
        "url": SERVER + reverse("games:list_games"),
        "messages": [{"message": "Saved", "type": "success"}],
        "option": OPTION,
    }


def test_a_tagged_redirect_to_a_form_page_continues(caplog, capture_games_logger):
    request = _dialog_request()
    redirect = CreatedRedirect(reverse("games:add_game"), option=OPTION)

    with capture_games_logger():
        answer = json.loads(_answered(request, redirect).content)

    assert answer["kind"] == "continue"
    assert "hands it to no picker" in caplog.text


def test_a_tagged_redirect_outside_dialog_mode_stays():
    request = RequestFactory().post("/")
    redirect = CreatedRedirect("/devices", option=OPTION)

    assert _answered(request, redirect) is redirect


@pytest.mark.django_db(transaction=True)
def test_add_game_answers_the_created_game(logged_in, game_post, owned_library):
    response = logged_in.post(
        reverse("games:add_game"), game_post("Outer Wilds"), headers=DIALOG_HEADERS
    )

    answer = response.json()
    game = Game.objects.get(library=owned_library, name="Outer Wilds")
    assert answer["kind"] == "created"
    assert answer["option"] == game_option(game)
    assert answer["url"] == SERVER + reverse("games:list_games")


@pytest.mark.untracked_games
@pytest.mark.django_db(transaction=True)
def test_add_game_refused_tracking_hands_over_nothing(
    logged_in, game_post, monkeypatch
):
    monkeypatch.setattr(
        "games.views.game.track_game_for_request", lambda *args, **kwargs: False
    )

    response = logged_in.post(
        reverse("games:add_game"), game_post("Outer Wilds"), headers=DIALOG_HEADERS
    )

    assert response.json()["kind"] == "done"
