import re

import pytest
from devices import create_device
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from entries import record_entry
from graphs import default_graph
from session_rows import session_row

from games.models import Device, Game, Platform, UserPreferences
from timetracker import settings_resolver


@pytest.fixture
def user(db):
    return get_user_model().objects.create_user(username="tester", password="pw")


@pytest.fixture
def auth_client(user):
    client = Client()
    client.force_login(user)
    return client


@pytest.fixture
def game(db, user):
    platform = Platform.objects.create(name="PC", icon="steam", group="PC")
    return Game.objects.create(library=user.library, name="Hades", platform=platform)


def _set_purchase_currency(user) -> None:
    UserPreferences.objects.filter(user=user).update(default_purchase_currency="EUR")
    settings_resolver.clear_cache()


def _tag_with(html: str, **attributes: object) -> str:
    for tag in re.findall(r"<[^>]+>", html):
        if all(f'{name}="{value}"' in tag for name, value in attributes.items()):
            return tag
    raise AssertionError(f"No tag contains {attributes!r}")


@pytest.mark.parametrize("url_name", ["games:add_purchase", "games:add_to_library"])
def test_purchase_forms_use_user_currency(auth_client, user, game, url_name):
    _set_purchase_currency(user)
    graph = default_graph(game, user.library)
    url = (
        reverse(url_name, args=[record_entry(user.library, graph.release).pk])
        if url_name == "games:add_purchase"
        else f"{reverse(url_name)}?game={game.pk}"
    )

    html = auth_client.get(url).content.decode()

    currency_input = _tag_with(html, name="currency")
    assert 'value="EUR"' in currency_input
    assert 'placeholder="EUR"' in currency_input


@pytest.mark.parametrize("states_game", [False, True])
def test_session_add_forms_use_user_device(auth_client, user, game, states_game):
    preferred = create_device(
        library=user.library, name="Steam Deck", type=Device.HANDHELD
    )
    user.library.preferences.set_default_device(preferred)
    query = f"?game={game.pk}" if states_game else ""

    html = auth_client.get(reverse("games:add_session") + query).content.decode()

    _tag_with(html, name="device", value=preferred.pk)


def test_session_edit_holds_what_the_session_states(auth_client, user, game):
    preferred = create_device(
        library=user.library, name="Steam Deck", type=Device.HANDHELD
    )
    existing_device = create_device(
        library=user.library, name="Desktop", type=Device.PC
    )
    user.library.preferences.set_default_device(preferred)
    empty = session_row(game, started_at=timezone.now())
    existing = session_row(
        game,
        started_at=timezone.now(),
        device=existing_device,
    )

    empty_html = auth_client.get(
        reverse("games:edit_session", args=[empty.pk])
    ).content.decode()
    existing_html = auth_client.get(
        reverse("games:edit_session", args=[existing.pk])
    ).content.decode()

    _tag_with(empty_html, name="device", value="", **{"data-search-select-none": ""})
    assert f'value="{preferred.pk}"' not in empty_html
    _tag_with(existing_html, name="device", value=existing_device.pk)
