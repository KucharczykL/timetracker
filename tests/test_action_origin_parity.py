"""Every link to a mutating view carries the page it was rendered on.

A row's Edit button must come back to the filtered, sorted, paginated list the
user was actually looking at, which only works if the page stamped its own full
path onto the link. Form actions count: the delete-confirmation POST target is
the single most important URL in the mechanism.
"""

import html
import re
from datetime import UTC, date, datetime
from urllib.parse import parse_qs, urlparse

import pytest
from django.urls import Resolver404, resolve, reverse

from games.models import Device, Game, Platform, PlayEvent, Purchase, Session
from games.views.returns import CONFIRMATION, ORIGIN_AWARE

LINK_ATTRIBUTE = re.compile(r'\b(?:href|hx-get|hx-post|action)="([^"]*)"')
MUST_CARRY_ORIGIN = ORIGIN_AWARE | CONFIRMATION


@pytest.fixture
def world(owned_library):
    platform = Platform.objects.create(name="PC")
    game = Game.objects.create(
        library=owned_library, name="Test Game", platform=platform
    )
    purchase = Purchase.objects.create(
        library=owned_library,
        price_currency="CZK",
        date_purchased=date(2024, 6, 1),
        type=Purchase.GAME,
    )
    purchase.games.set([game])
    Session.objects.create(
        game=game,
        timestamp_start=datetime(2024, 6, 1, 12, tzinfo=UTC),
        device=Device.objects.create(library=owned_library, name="Desk"),
    )
    PlayEvent.objects.create(game=game)
    return game


def _missing_origin(body: str, page_path: str) -> list[str]:
    failures = []
    for raw in LINK_ATTRIBUTE.findall(body):
        url = html.unescape(raw)
        if not url.startswith("/"):
            continue
        parsed = urlparse(url)
        try:
            match = resolve(parsed.path)
        except Resolver404:
            continue
        name = f"{match.app_name}:{match.url_name}"
        if name not in MUST_CARRY_ORIGIN:
            continue
        carried = parse_qs(parsed.query).get("origin", [])
        if carried != [page_path]:
            failures.append(f"{name} carried {carried!r}, expected [{page_path!r}]")
    return failures


@pytest.mark.parametrize(
    "url_name",
    [
        "games:list_games",
        "games:list_sessions",
        "games:list_purchases",
        "games:list_playevents",
        "games:list_platforms",
        "games:list_devices",
        "games:list_statuschanges",
    ],
)
def test_list_pages_stamp_their_own_path(client, owned_user, world, url_name):
    client.force_login(owned_user)
    page_path = reverse(url_name) + "?page=1"
    response = client.get(page_path)
    assert response.status_code == 200
    assert _missing_origin(response.content.decode(), page_path) == []


@pytest.mark.parametrize("url_name", ["games:view_game", "games:view_purchase"])
def test_detail_pages_stamp_their_own_path(client, owned_user, world, url_name):
    client.force_login(owned_user)
    target = world if url_name == "games:view_game" else world.purchases.first()
    page_path = reverse(url_name, args=[target.id])
    response = client.get(page_path)
    assert response.status_code == 200
    assert _missing_origin(response.content.decode(), page_path) == []


def test_a_form_page_stamps_no_origin_on_its_navbar(client, owned_user, world):
    """There is nothing to return to from a form, and an origin naming one would
    be refused by the READ_ONLY allow-list anyway."""
    client.force_login(owned_user)
    body = client.get(reverse("games:edit_game", args=[world.id])).content.decode()
    assert "origin=" not in body
