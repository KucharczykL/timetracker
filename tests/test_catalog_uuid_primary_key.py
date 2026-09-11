"""What a UUID primary key on the catalog has to keep answering.

Each of these was a guarantee the promotion off integer keys could have lost
without anything else noticing: a uniqueness rule, a route that reads an
identity, a page that builds a filter link, a stale integer arriving in one.
"""

import json

import pytest
from django.db import IntegrityError, transaction
from django.test import Client
from django.urls import NoReverseMatch, reverse
from django.utils import timezone

from games.models import Device, Game, Platform, PlayerGameStatus, Session

pytestmark = pytest.mark.django_db(transaction=True)


# Route-shape only; never reaches the database.
GAME_ROUTE_ID = "018f5e66-e800-7000-8000-000000000001"


@pytest.fixture
def library_client(db, django_user_model):
    user = django_user_model.objects.create_user(username="promoted", password="pw")
    client = Client()
    client.force_login(user)
    return client, user.library


def test_games_uniqueness_guarantees_are_still_enforced(owned_library):
    """`DROP COLUMN` cascades indexes away while Django's migration state keeps
    listing them, so both of Game's guarantees have to be asserted as *enforced*.

    Through `bulk_create`, because `Model.save()` runs `clean()`, which raises in
    Python before PostgreSQL ever sees the row. Every constrained column needs a
    non-NULL value too - a NULL never collides in a unique index.
    """
    platform = Platform.objects.create(name="Shared Platform")
    Game.objects.create(
        library=owned_library, name="Twin", platform=platform, year_released=2020
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        Game.objects.bulk_create(
            [
                Game(
                    library=owned_library,
                    name="Twin",
                    platform=platform,
                    year_released=2020,
                )
            ]
        )

    Game.objects.create(
        library=owned_library, name="Platformless", platform=None, year_released=2021
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        Game.objects.bulk_create(
            [
                Game(
                    library=owned_library,
                    name="Platformless",
                    platform=None,
                    year_released=2021,
                )
            ]
        )


def test_search_endpoints_report_each_entitys_own_identity_type(library_client):
    """Every catalog/config search option exposes its UUID identity as JSON text."""
    client, library = library_client
    platform = Platform.objects.create(name="Search Platform")
    game = Game.objects.create(library=library, name="Searchable", platform=platform)
    device = Device.objects.create(library=library, name="Searchable Device")

    games = client.get("/api/games/search", {"q": "Search"}).json()
    assert [row["value"] for row in games] == [str(game.pk)]

    platforms = client.get("/api/platforms/search", {"q": "Search"}).json()
    assert [row["value"] for row in platforms] == [str(platform.pk)]

    devices = client.get("/api/devices/search", {"q": "Search"}).json()
    assert [row["value"] for row in devices] == [str(device.pk)]


@pytest.mark.django_db(transaction=True)
def test_game_bearing_endpoints_accept_the_new_identity(library_client):
    """The three non-search endpoints that typed a game id as an integer. Each
    fails independently, and none is covered by a search-endpoint test."""
    client, library = library_client
    game = Game.objects.create(library=library, name="Endpoint Game")

    assert (
        client.patch(
            f"/api/games/{game.pk}/status",
            json.dumps({"status": PlayerGameStatus.PLAYED}),
            content_type="application/json",
        ).status_code
        == 204
    )

    created = client.post(
        "/api/playthrough/",
        json.dumps({"game_id": str(game.pk), "note": "played"}),
        content_type="application/json",
    )
    assert created.status_code == 204

    session = Session.objects.create(game=game, timestamp_start=timezone.now())
    detail = client.get(f"/api/session/{session.pk}").json()
    assert detail["game"]["id"] == str(game.pk)


def test_pages_that_build_filter_links_still_render(library_client):
    """`filter_to_json` is `json.dumps(to_json())`, which cannot represent a
    UUID. Game detail and stats both build catalog filter links server-side, with
    the identity as a criterion value *and* as a label key."""
    client, library = library_client
    platform = Platform.objects.create(name="Link Platform")
    game = Game.objects.create(library=library, name="Linked", platform=platform)
    Session.objects.create(game=game, timestamp_start=timezone.now())

    assert client.get(game.get_absolute_url()).status_code == 200
    assert client.get("/tracker/stats/").status_code == 200


def test_a_stale_integer_filter_degrades_instead_of_crashing(library_client):
    """The shape a preset or bookmarked URL saved before this slice carries."""
    client, library = library_client
    Game.objects.create(library=library, name="Still Listed")

    response = client.get(
        "/tracker/game/list",
        {"filter": json.dumps({"platform": {"value": [7], "modifier": "INCLUDES"}})},
        follow=True,
    )

    assert response.status_code == 200
    assert b"Still Listed" in response.content


def test_catalog_routes_accept_a_uuid_and_reject_an_integer():
    assert reverse("games:view_game", args=[GAME_ROUTE_ID, "catalog-game"]).endswith(
        f"{GAME_ROUTE_ID}/catalog-game/"
    )
    with pytest.raises(NoReverseMatch):
        reverse("games:view_game", args=[1, "catalog-game"])
