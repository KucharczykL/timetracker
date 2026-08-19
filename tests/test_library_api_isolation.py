import json
from datetime import UTC, date, datetime, timedelta

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from common.criteria import (
    AggregateCriterion,
    ChoiceCriterion,
    FieldComparisonCriterion,
    FilterQueryContext,
    Modifier,
    RelationMatch,
    StringCriterion,
)
from common.filter_execution import execute_filter
from games.filters import (
    GameFilter,
    PlatformFilter,
    PurchaseFilter,
    SessionFilter,
    filter_query_context_for_library,
)
from games.models import (
    Device,
    FilterPreset,
    Game,
    Platform,
    PlayEvent,
    Purchase,
    Session,
)
from games.views.stats_data import compute_stats

YEAR = 2024

pytestmark = pytest.mark.django_db


def _client_for(user) -> Client:
    client = Client()
    client.force_login(user)
    return client


def _patch(client: Client, path: str, payload: dict):
    return client.patch(path, json.dumps(payload), content_type="application/json")


@pytest.fixture
def two_libraries(db):
    user_a = get_user_model().objects.create_user(username="library-a", password="pw")
    user_b = get_user_model().objects.create_user(username="library-b", password="pw")
    library_a = user_a.library
    library_b = user_b.library

    shared_platform = Platform.objects.create(name="Shared Platform", group="Shared")
    platform_a = Platform.objects.create(
        library=library_a, name="Library A Platform", group="Library A"
    )
    platform_b = Platform.objects.create(
        library=library_b, name="Library B Platform", group="Library B"
    )
    game_a = Game.objects.create(
        library=library_a,
        name="Library A Game",
        platform=platform_a,
        year_released=YEAR,
        status=Game.Status.FINISHED,
    )
    game_b = Game.objects.create(
        library=library_b,
        name="Library B Game",
        platform=platform_b,
        year_released=YEAR,
        status=Game.Status.FINISHED,
    )
    shared_game_a = Game.objects.create(
        library=library_a,
        name="Library A Shared Game",
        platform=shared_platform,
        year_released=YEAR - 1,
    )
    shared_game_b = Game.objects.create(
        library=library_b,
        name="Library B Shared Game",
        platform=shared_platform,
        year_released=YEAR - 1,
    )
    device_a = Device.objects.create(library=library_a, name="Library A Device")
    device_b = Device.objects.create(library=library_b, name="Library B Device")

    session_a = Session.objects.create(
        game=game_a,
        device=device_a,
        timestamp_start=datetime(YEAR, 6, 1, 10, tzinfo=UTC),
        timestamp_end=datetime(YEAR, 6, 1, 12, tzinfo=UTC),
    )
    session_b = Session.objects.create(
        game=game_b,
        device=device_b,
        timestamp_start=datetime(YEAR, 6, 2, 10, tzinfo=UTC),
        timestamp_end=datetime(YEAR, 6, 2, 13, tzinfo=UTC),
    )
    PlayEvent.objects.create(
        game=game_a,
        started=date(YEAR, 1, 1),
        ended=date(YEAR, 2, 1),
        note="Library A event",
    )
    playevent_b = PlayEvent.objects.create(
        game=game_b,
        started=date(YEAR, 1, 2),
        ended=date(YEAR, 2, 2),
        note="Library B event",
    )

    purchase_a = Purchase.objects.create(
        library=library_a,
        price=30,
        price_currency="CZK",
        converted_price=30,
        converted_currency="CZK",
        date_purchased=date(YEAR, 3, 1),
        type=Purchase.GAME,
    )
    purchase_a.games.set([game_a])
    purchase_b = Purchase.objects.create(
        library=library_b,
        price=100,
        price_currency="CZK",
        converted_price=100,
        converted_currency="CZK",
        date_purchased=date(YEAR, 3, 2),
        type=Purchase.GAME,
    )
    purchase_b.games.set([game_b])

    return {
        "user_a": user_a,
        "user_b": user_b,
        "client_a": _client_for(user_a),
        "client_b": _client_for(user_b),
        "library_a": library_a,
        "library_b": library_b,
        "shared_platform": shared_platform,
        "platform_a": platform_a,
        "platform_b": platform_b,
        "game_a": game_a,
        "game_b": game_b,
        "shared_game_a": shared_game_a,
        "shared_game_b": shared_game_b,
        "device_a": device_a,
        "device_b": device_b,
        "session_a": session_a,
        "session_b": session_b,
        "playevent_b": playevent_b,
        "purchase_a": purchase_a,
        "purchase_b": purchase_b,
    }


def test_search_options_are_library_scoped_and_shared_platforms_remain_visible(
    two_libraries,
):
    world = two_libraries
    client = world["client_a"]

    game_ids = {
        row["value"] for row in client.get("/api/games/search", {"q": "Game"}).json()
    }
    assert game_ids == {str(world["game_a"].id), str(world["shared_game_a"].id)}

    device_ids = {
        row["value"]
        for row in client.get("/api/devices/search", {"q": "Device"}).json()
    }
    assert device_ids == {world["device_a"].id}

    Game.objects.filter(pk=world["shared_game_a"].pk).update(
        updated_at=datetime(2020, 1, 1, tzinfo=UTC)
    )
    Game.objects.filter(pk=world["game_a"].pk).update(
        updated_at=datetime(2021, 1, 1, tzinfo=UTC)
    )
    Game.objects.filter(pk=world["shared_game_b"].pk).update(
        updated_at=datetime(2022, 1, 1, tzinfo=UTC)
    )
    platform_ids = [row["value"] for row in client.get("/api/platforms/search").json()]
    assert platform_ids == [
        str(world["platform_a"].id),
        str(world["shared_platform"].id),
    ]

    groups = {row["value"] for row in client.get("/api/platforms/groups").json()}
    assert groups == {"Shared", "Library A"}


def test_foreign_game_status_id_is_undisclosed_and_unchanged(two_libraries):
    world = two_libraries

    response = _patch(
        world["client_a"],
        f"/api/games/{world['game_b'].id}/status",
        {"status": Game.Status.ABANDONED},
    )

    assert response.status_code == 404
    world["game_b"].refresh_from_db()
    assert world["game_b"].status == Game.Status.FINISHED


def test_playevent_crud_is_library_scoped(two_libraries):
    world = two_libraries
    client = world["client_a"]
    foreign = world["playevent_b"]

    listed_ids = {row["id"] for row in client.get("/api/playevent/").json()}
    assert foreign.id not in listed_ids
    assert client.get(f"/api/playevent/{foreign.id}").status_code == 404
    assert (
        _patch(client, f"/api/playevent/{foreign.id}", {"note": "changed"}).status_code
        == 404
    )
    assert client.delete(f"/api/playevent/{foreign.id}").status_code == 404
    create = client.post(
        "/api/playevent/",
        json.dumps({"game_id": str(world["game_b"].id), "note": "foreign"}),
        content_type="application/json",
    )
    assert create.status_code == 404
    foreign.refresh_from_db()
    assert foreign.note == "Library B event"


def test_session_reads_and_mutations_are_library_scoped(two_libraries):
    world = two_libraries
    client = world["client_a"]
    foreign = world["session_b"]
    own = world["session_a"]

    payload = client.get("/api/session/").json()
    assert payload["count"] == 1
    assert [row["id"] for row in payload["items"]] == [own.id]
    assert client.get(f"/api/session/{foreign.id}").status_code == 404
    assert (
        _patch(
            client,
            f"/api/session/{foreign.id}",
            {"timestamp_end": f"{YEAR}-06-02T14:00:00Z"},
        ).status_code
        == 404
    )
    assert (
        _patch(
            client,
            f"/api/session/{own.id}/device",
            {"device_id": world["device_b"].id},
        ).status_code
        == 404
    )
    own.refresh_from_db()
    foreign.refresh_from_db()
    assert own.device_id == world["device_a"].uuid
    assert foreign.timestamp_end == datetime(YEAR, 6, 2, 13, tzinfo=UTC)


@pytest.mark.parametrize(
    ("model", "filter_payload", "expected"),
    [
        ("game", {"name": {"value": "Library A", "modifier": "INCLUDES"}}, 2),
        (
            "session",
            {"game_filter": {"name": {"value": "Library A", "modifier": "INCLUDES"}}},
            1,
        ),
        ("purchase", {"converted_price": {"value": 0, "modifier": "GREATER_THAN"}}, 1),
        ("playevent", {"note": {"value": "event", "modifier": "INCLUDES"}}, 1),
        ("device", {"name": {"value": "Device", "modifier": "INCLUDES"}}, 1),
        ("platform", {"name": {"value": "Platform", "modifier": "INCLUDES"}}, 1),
    ],
)
def test_filter_counts_start_from_a_library_scoped_base_queryset(
    two_libraries, model, filter_payload, expected
):
    response = two_libraries["client_a"].get(
        "/api/filter/count",
        {"model": model, "filter": json.dumps(filter_payload)},
    )

    assert response.status_code == 200
    assert response.json() == {"count": expected}


def test_presets_are_library_owned_and_same_name_is_unique_per_library(two_libraries):
    body = json.dumps({"name": "Backlog", "mode": "games", "filter": None})

    response_a = two_libraries["client_a"].post(
        "/api/presets/", body, content_type="application/json"
    )
    response_b = two_libraries["client_b"].post(
        "/api/presets/", body, content_type="application/json"
    )

    assert response_a.status_code == response_b.status_code == 201
    assert FilterPreset.objects.filter(name="Backlog").count() == 2
    assert {
        preset.library_id for preset in FilterPreset.objects.filter(name="Backlog")
    } == {two_libraries["library_a"].id, two_libraries["library_b"].id}
    assert [
        row["label"] for row in two_libraries["client_a"].get("/api/presets/").json()
    ] == ["Backlog"]


def test_compute_stats_uses_only_the_requested_library(two_libraries):
    world = two_libraries
    stats = compute_stats(world["library_a"], YEAR)

    assert stats["total_sessions"] == 1
    assert stats["total_hours"] == timedelta(hours=2)
    assert stats["unique_days"] == 1
    assert stats["total_games"] == 1
    assert stats["total_year_games"] == 1
    assert stats["total_spent"] == 30
    assert stats["all_purchased_this_year_count"] == 1
    assert stats["all_purchased_refunded_this_year_count"] == 0
    assert stats["all_finished_this_year_count"] == 1
    assert stats["this_year_finished_this_year_count"] == 1
    assert stats["dropped_count"] == 0
    assert [game.id for game in stats["top_10_games_by_playtime"]] == [
        world["game_a"].id
    ]
    assert {row["platform_id"] for row in stats["total_playtime_per_platform"]} == {
        world["platform_a"].id
    }
    assert list(stats["all_purchased_this_year"]) == [world["purchase_a"]]


def test_nested_filter_cannot_match_shared_platform_from_foreign_game(two_libraries):
    world = two_libraries
    filter_object = PlatformFilter(
        game_filter=GameFilter(
            name=StringCriterion(value="Library B", modifier=Modifier.INCLUDES)
        )
    )

    matching = execute_filter(
        filter_object,
        Platform.objects.visible_to(world["library_a"]),
        filter_query_context_for_library(world["library_a"]),
    )

    assert list(matching) == []


def test_aggregate_filter_subqueries_are_library_scoped(two_libraries):
    world = two_libraries
    criterion = AggregateCriterion(value=1)
    criterion.scope = SessionFilter(
        note=StringCriterion(value="Library", modifier=Modifier.INCLUDES)
    )
    filter_object = GameFilter(session_count=criterion)

    queryset = execute_filter(
        filter_object,
        Game.objects.for_library(world["library_a"]),
        filter_query_context_for_library(world["library_a"]),
    )

    assert str(queryset.query).count("library_id") >= 3


def test_multivalued_comparison_subquery_is_library_scoped(two_libraries):
    world = two_libraries
    filter_object = GameFilter(
        field_comparisons=[
            FieldComparisonCriterion(
                left="sessions__timestamp_end",
                right="sessions__timestamp_start",
                modifier=Modifier.GREATER_THAN,
                quantifier=RelationMatch.ANY,
            )
        ]
    )

    queryset = execute_filter(
        filter_object,
        Game.objects.for_library(world["library_a"]),
        filter_query_context_for_library(world["library_a"]),
    )

    assert str(queryset.query).count("library_id") >= 3


def test_purchase_games_filter_is_scoped_and_lazy(
    two_libraries,
    django_assert_num_queries,
):
    world = two_libraries
    filter_object = PurchaseFilter(
        games=ChoiceCriterion(
            value=[world["game_a"].id],
            modifier=Modifier.INCLUDES_ONLY,
        )
    )

    with django_assert_num_queries(0):
        queryset = execute_filter(
            filter_object,
            Purchase.objects.for_library(world["library_a"]),
            filter_query_context_for_library(world["library_a"]),
        )

    assert str(queryset.query).count("library_id") >= 3


def test_filter_execution_rejects_missing_authorization_context(two_libraries):
    world = two_libraries

    with pytest.raises(TypeError):
        execute_filter(
            GameFilter(name=StringCriterion(value="Library A Game")),
            Game.objects.for_library(world["library_a"]),
        )


def test_filter_execution_rejects_validation_only_context(two_libraries):
    world = two_libraries

    with pytest.raises(RuntimeError, match="validation-only"):
        execute_filter(
            GameFilter(name=StringCriterion(value="Library A Game")),
            Game.objects.for_library(world["library_a"]),
            FilterQueryContext.for_validation(),
        )
