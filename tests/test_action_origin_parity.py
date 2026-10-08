"""Every link to a mutating view carries the page it was rendered on.

A row's Edit button must come back to the filtered, sorted, paginated list the
user was actually looking at, which only works if the page stamped its own full
path onto the link. Form actions count: the delete-confirmation POST target is
the single most important URL in the mechanism.
"""

import html
import re
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse

import pytest
from devices import create_device
from django.urls import Resolver404, resolve, reverse
from entries import record_entry
from graphs import default_graph
from historical_playtime_rows import record_row
from purchases import record_purchase
from session_rows import session_row

from games.models import Game, Platform, Playthrough
from games.views.returns import ORIGIN_AWARE

LINK_ATTRIBUTE = re.compile(r'\b(?:href|action)="([^"]*)"')
MUST_CARRY_ORIGIN = ORIGIN_AWARE


@pytest.fixture
def world(owned_library):
    platform = Platform.objects.create(name="PC")
    graph = default_graph(
        Game(library=owned_library, name="Test Game", platform=platform),
        owned_library,
    )
    game = graph.game
    record_purchase(record_entry(owned_library, graph.release))
    session_row(
        game,
        started_at=datetime(2024, 6, 1, 12, tzinfo=UTC),
        device=create_device(library=owned_library, name="Desk"),
    )
    #: Tracking states a run of its own, so the playthrough
    #: sweep has a row whose actions carry an origin.
    record_row([Playthrough.objects.get(player_game__game=game)])
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
        "games:list_playthroughs",
        "games:list_historical_playtime",
        "games:list_platforms",
        "games:list_devices",
        "games:list_library",
    ],
)
def test_list_pages_stamp_their_own_path(client, owned_user, world, url_name):
    client.force_login(owned_user)
    page_path = reverse(url_name) + "?page=1"
    response = client.get(page_path)
    assert response.status_code == 200
    assert _missing_origin(response.content.decode(), page_path) == []


def test_the_detail_page_stamps_its_own_path(client, owned_user, world):
    client.force_login(owned_user)
    page_path = world.get_absolute_url()
    response = client.get(page_path)
    assert response.status_code == 200
    assert _missing_origin(response.content.decode(), page_path) == []


def test_a_form_page_stamps_no_origin_on_its_navbar(client, owned_user, world):
    """There is nothing to return to from a form, and an origin naming one would
    be refused by the READ_ONLY allow-list anyway."""
    client.force_login(owned_user)
    body = client.get(reverse("games:edit_game", args=[world.id])).content.decode()
    assert "origin=" not in body
