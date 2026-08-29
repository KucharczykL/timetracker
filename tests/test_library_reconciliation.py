"""End-to-end parity proof for the final two-library ownership domain."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from io import StringIO
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client
from django.urls import reverse

from common.filter_execution import execute_filter
from games import tasks
from games.conversion import request_conversion
from games.filters import (
    filter_query_context_for_library,
    filter_queryset_for_library,
    filter_url,
)
from games.models import (
    Device,
    ExchangeRate,
    FilterPreset,
    Game,
    GameStatusChange,
    Platform,
    PlayEvent,
    Purchase,
    PurchaseConversionState,
    Session,
)
from games.views import stats_links
from games.views.stats_data import compute_stats

YEAR = 2025
pytestmark = pytest.mark.django_db


def _client_for(user) -> Client:
    client = Client()
    client.force_login(user)
    return client


def _session(game, device, day: int, hours: int) -> Session:
    started = datetime(YEAR, 6, day, 10, tzinfo=UTC)
    return Session.objects.create(
        game=game,
        device=device,
        timestamp_start=started,
        timestamp_end=started + timedelta(hours=hours),
    )


@pytest.fixture
def parity_world(monkeypatch):
    monkeypatch.setattr("games.conversion.async_task", lambda *args, **kwargs: None)
    user_a = get_user_model().objects.create_user(username="reconcile-a", password="pw")
    user_b = get_user_model().objects.create_user(username="reconcile-b", password="pw")
    library_a = user_a.library
    library_b = user_b.library

    shared_platform = Platform.objects.create(
        name="Reconcile Shared Platform", group="Shared"
    )
    platform_a = Platform.objects.create(
        library=library_a, name="Reconcile A Private Platform", group="Private"
    )
    platform_b = Platform.objects.create(
        library=library_b, name="Reconcile B Private Platform", group="Private"
    )
    game_a = Game.objects.create(
        library=library_a,
        name="Reconcile A Main Game",
        platform=platform_a,
        year_released=YEAR,
        status=Game.Status.FINISHED,
    )
    shared_game_a = Game.objects.create(
        library=library_a,
        name="Reconcile A Shared Game",
        platform=shared_platform,
        year_released=YEAR,
        status=Game.Status.PLAYED,
    )
    game_b = Game.objects.create(
        library=library_b,
        name="Reconcile B Main Game",
        platform=platform_b,
        year_released=YEAR,
        status=Game.Status.FINISHED,
    )
    shared_game_b = Game.objects.create(
        library=library_b,
        name="Reconcile B Shared Game",
        platform=shared_platform,
        year_released=YEAR,
        status=Game.Status.PLAYED,
    )
    device_a = Device.objects.create(library=library_a, name="Reconcile A Device")
    device_b = Device.objects.create(library=library_b, name="Reconcile B Device")
    sessions_a = [
        _session(game_a, device_a, 1, 2),
        _session(shared_game_a, device_a, 2, 1),
    ]
    sessions_b = [
        _session(game_b, device_b, 3, 4),
        _session(shared_game_b, device_b, 4, 1),
    ]

    playevent_a = PlayEvent.objects.create(
        game=game_a,
        started=date(YEAR, 1, 1),
        ended=date(YEAR, 2, 1),
        note="Reconcile A Event",
    )
    playevent_b = PlayEvent.objects.create(
        game=game_b,
        started=date(YEAR, 1, 2),
        ended=date(YEAR, 2, 2),
        note="Reconcile B Event",
    )
    status_a = GameStatusChange.objects.create(
        game=game_a,
        old_status=Game.Status.PLAYED,
        new_status=Game.Status.FINISHED,
        timestamp=datetime(YEAR, 2, 1, tzinfo=UTC),
    )
    status_b = GameStatusChange.objects.create(
        game=game_b,
        old_status=Game.Status.PLAYED,
        new_status=Game.Status.FINISHED,
        timestamp=datetime(YEAR, 2, 2, tzinfo=UTC),
    )
    purchase_a = Purchase.objects.create(
        library=library_a,
        name="Reconcile A Purchase",
        platform=platform_a,
        date_purchased=date(YEAR, 3, 1),
        price=100,
        price_currency="CZK",
        converted_price=100,
        converted_currency="CZK",
    )
    purchase_a.games.set([game_a, shared_game_a])
    purchase_b = Purchase.objects.create(
        library=library_b,
        name="Reconcile B Purchase",
        platform=platform_b,
        date_purchased=date(YEAR, 3, 2),
        price=200,
        price_currency="CZK",
        converted_price=200,
        converted_currency="CZK",
    )
    purchase_b.games.set([game_b, shared_game_b])
    Purchase.objects.filter(pk__in=[purchase_a.pk, purchase_b.pk]).update(
        needs_price_update=False
    )
    for state in PurchaseConversionState.objects.filter(
        library__in=[library_a, library_b]
    ):
        state.requested_currency = "CZK"
        state.published_version = state.requested_version
        state.published_currency = "CZK"
        state.status = PurchaseConversionState.Status.COMPLETE
        state.retry_at = None
        state.last_error = ""
        state.save()

    client_a = _client_for(user_a)
    client_b = _client_for(user_b)

    return SimpleNamespace(**locals())


def _count_link(filter_object, model, library) -> int:
    queryset = filter_queryset_for_library(model._meta.model_name, library)
    return (
        execute_filter(
            filter_object,
            queryset,
            filter_query_context_for_library(library),
        )
        .distinct()
        .count()
    )


def test_row_link_and_audit_reconciliation_is_independent(parity_world):
    world = parity_world
    for library, username in (
        (world.library_a, world.user_a.username),
        (world.library_b, world.user_b.username),
    ):
        assert Game.objects.for_library(library).count() == 2
        assert Device.objects.for_library(library).count() == 1
        assert Purchase.objects.for_library(library).count() == 1
        assert Session.objects.for_library(library).count() == 2
        assert PlayEvent.objects.for_library(library).count() == 1
        assert GameStatusChange.objects.for_library(library).count() == 1
        assert Platform.objects.for_library(library).count() == 1
        assert Platform.objects.visible_to(library).count() == 2
        assert (
            Purchase.games.through.objects.filter(purchase__library=library).count()
            == 2
        )
        output = StringIO()
        call_command("audit_library_ownership", "--user", username, stdout=output)
        assert "Cross-library links: 0" in output.getvalue()
        assert "Ownership audit passed" in output.getvalue()


def test_pages_render_only_the_authenticated_library(parity_world):
    world = parity_world
    cases = (
        (
            world.client_a,
            "Reconcile A",
            "Reconcile B",
            world.platform_a.name,
            world.platform_b.name,
        ),
        (
            world.client_b,
            "Reconcile B",
            "Reconcile A",
            world.platform_b.name,
            world.platform_a.name,
        ),
    )
    for client, own, foreign, own_platform, foreign_platform in cases:
        for url_name in (
            "games:list_games",
            "games:list_sessions",
            "games:list_purchases",
            "games:list_devices",
            "games:list_playevents",
            "games:stats_by_year",
        ):
            args = [YEAR] if url_name == "games:stats_by_year" else None
            response = client.get(reverse(url_name, args=args))
            assert response.status_code == 200
            body = response.content.decode()
            assert own in body
            assert foreign not in body
        platform_body = client.get(reverse("games:list_platforms")).content.decode()
        assert own_platform in platform_body
        assert foreign_platform not in platform_body
        assert (
            reverse("games:edit_platform", args=[world.shared_platform.pk])
            not in platform_body
        )


def test_apis_filters_and_presets_reconcile_per_library(parity_world):
    world = parity_world
    for side in ("a", "b"):
        client = getattr(world, f"client_{side}")
        # JSON carries every promoted identity as a string.
        own_games = {
            str(world.__dict__[f"game_{side}"].pk),
            str(world.__dict__[f"shared_game_{side}"].pk),
        }
        game_ids = {
            row["value"]
            for row in client.get("/api/games/search", {"q": "Reconcile"}).json()
        }
        assert game_ids == own_games
        assert {row["value"] for row in client.get("/api/devices/search").json()} == {
            str(getattr(world, f"device_{side}").pk)
        }
        assert {row["value"] for row in client.get("/api/platforms/search").json()} == {
            str(world.shared_platform.pk),
            str(getattr(world, f"platform_{side}").pk),
        }
        sessions = client.get("/api/session/").json()
        assert sessions["count"] == 2
        assert {row["id"] for row in sessions["items"]} == {
            str(session.pk) for session in getattr(world, f"sessions_{side}")
        }
        assert {row["id"] for row in client.get("/api/playevent/").json()} == {
            str(getattr(world, f"playevent_{side}").pk)
        }
        count = client.get(
            "/api/filter/count",
            {
                "model": "game",
                "filter": json.dumps(
                    {"name": {"value": "Reconcile", "modifier": "INCLUDES"}}
                ),
            },
        )
        assert count.json() == {"count": 2}

    payload = json.dumps({"name": "Parity", "mode": "games", "filter": None})
    assert (
        world.client_a.post(
            "/api/presets/", payload, content_type="application/json"
        ).status_code
        == 201
    )
    assert (
        world.client_b.post(
            "/api/presets/", payload, content_type="application/json"
        ).status_code
        == 201
    )
    assert FilterPreset.objects.filter(name="Parity").count() == 2
    assert [row["label"] for row in world.client_a.get("/api/presets/").json()] == [
        "Parity"
    ]
    assert [row["label"] for row in world.client_b.get("/api/presets/").json()] == [
        "Parity"
    ]


def test_statistics_and_exact_links_reconcile_per_library(parity_world):
    world = parity_world
    expected = (("a", timedelta(hours=3), 100), ("b", timedelta(hours=5), 200))
    for side, playtime, spending in expected:
        library = getattr(world, f"library_{side}")
        client = getattr(world, f"client_{side}")
        game = getattr(world, f"game_{side}")
        stats = compute_stats(library, YEAR)
        assert stats["total_sessions"] == 2
        assert stats["total_hours"] == playtime
        assert stats["total_games"] == 2
        assert stats["total_spent"] == spending
        assert stats["total_spent_currency"] == "CZK"
        exact_links = (
            (stats_links.all_sessions(YEAR), Session, stats["total_sessions"]),
            (stats_links.games_played(YEAR), Game, stats["total_games"]),
            (
                stats_links.purchases_total(YEAR),
                Purchase,
                stats["all_purchased_this_year_count"],
            ),
            (stats_links.sessions_for_game(game.pk, YEAR, game.name), Session, 1),
            (
                stats_links.sessions_for_platform(
                    world.shared_platform.pk, YEAR, world.shared_platform.name
                ),
                Session,
                1,
            ),
            (stats_links.games_in_month(YEAR, 6), Game, 2),
        )
        for link_filter, model, count in exact_links:
            assert _count_link(link_filter, model, library) == count
            assert client.get(filter_url(link_filter), follow=True).status_code == 200


def test_conversion_publication_is_independent_per_library(parity_world):
    world = parity_world
    ExchangeRate.objects.create(
        currency_from="CZK", currency_to="EUR", year=YEAR, rate=0.04
    )
    ExchangeRate.objects.create(
        currency_from="CZK", currency_to="USD", year=YEAR, rate=0.05
    )
    version_a = request_conversion(world.library_a, "EUR")
    version_b = request_conversion(world.library_b, "USD")

    tasks.convert_library_prices(str(world.library_a.pk), version_a)
    world.purchase_a.refresh_from_db()
    world.purchase_b.refresh_from_db()
    state_b = PurchaseConversionState.objects.get(library=world.library_b)
    assert (world.purchase_a.converted_price, world.purchase_a.converted_currency) == (
        4,
        "EUR",
    )
    assert (world.purchase_b.converted_price, world.purchase_b.converted_currency) == (
        200,
        "CZK",
    )
    assert (state_b.status, state_b.requested_currency) == ("pending", "USD")

    tasks.convert_library_prices(str(world.library_b.pk), version_b)
    world.purchase_b.refresh_from_db()
    assert (world.purchase_b.converted_price, world.purchase_b.converted_currency) == (
        10,
        "USD",
    )
    assert compute_stats(world.library_a, YEAR)["total_spent_currency"] == "EUR"
    assert compute_stats(world.library_b, YEAR)["total_spent_currency"] == "USD"
    assert (
        world.client_a.get("/api/conversion/status").json()["published_currency"]
        == "EUR"
    )
    assert (
        world.client_b.get("/api/conversion/status").json()["published_currency"]
        == "USD"
    )
