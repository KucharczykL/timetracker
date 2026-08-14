"""Every view routed from games/urls.py must require authentication.

The Ninja API is covered separately by ``NinjaAPI(auth=django_auth)``
(games/api.py:52) and is not routed from games/urls.py.
"""

from datetime import UTC, date, datetime

import pytest
from django.conf import settings
from django.urls import reverse

from games import urls as games_urls
from games.models import (
    Device,
    Game,
    GameStatusChange,
    Platform,
    PlayEvent,
    Purchase,
    Session,
)


@pytest.fixture
def world(db):
    platform = Platform.objects.create(name="PC")
    game = Game.objects.create(name="Test Game", platform=platform)
    purchase = Purchase.objects.create(
        price_currency="CZK", date_purchased=date(2024, 6, 1), type=Purchase.GAME
    )
    purchase.games.set([game])
    return {
        "game_id": game.id,
        "purchase_id": purchase.id,
        "session_id": Session.objects.create(
            game=game, timestamp_start=datetime(2024, 6, 1, 12, tzinfo=UTC)
        ).id,
        "playevent_id": PlayEvent.objects.create(game=game).id,
        "statuschange_id": GameStatusChange.objects.create(
            game=game, new_status="p"
        ).id,
        "device_id": Device.objects.create(name="Desk").id,
        "platform_id": platform.id,
        "year": 2024,
        "model": "game",
        "key": "DEFAULT_PURCHASE_CURRENCY",
    }


def test_every_route_requires_login(client, world):
    world["pk"] = world["statuschange_id"]
    unprotected = []
    for pattern in games_urls.urlpatterns:
        if pattern.name is None:
            continue
        needed = pattern.pattern.regex.groupindex.keys()
        missing = [key for key in needed if key not in world]
        assert not missing, f"add a sample argument for {pattern.name}: {missing}"
        url = reverse(f"games:{pattern.name}", kwargs={k: world[k] for k in needed})
        response = client.get(url)
        redirects_to_login = (
            response.status_code == 302 and settings.LOGIN_URL in (response["Location"])
        )
        if not redirects_to_login:
            unprotected.append(f"{pattern.name} -> {response.status_code}")
    assert unprotected == []
