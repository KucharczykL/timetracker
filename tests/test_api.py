import json
import logging
import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from session_rows import duration_only_row, session_row, timed_row, tracked_run

from games.filters import parse_game_filter
from games.models import (
    Device,
    Game,
    Platform,
    PlayerSession,
    Purchase,
    UserPreferences,
)
from games.reads.playtime import game_playtime
from timetracker import settings_resolver

pytestmark = pytest.mark.django_db


@pytest.fixture
def user(db):
    return get_user_model().objects.create_user(username="tester", password="pw")


@pytest.fixture
def auth_client(user):
    client = Client()
    client.force_login(user)
    return client


def _test_library():
    user = get_user_model().objects.filter(username="tester").first()
    if user is None:
        user, _ = get_user_model().objects.get_or_create(username="api-fixture-owner")
    return user.library


def _owned_device(**values):
    return Device.objects.create(library=_test_library(), **values)


def _owned_game(**values):
    return Game.objects.create(library=_test_library(), **values)


def _owned_purchase(**values):
    return Purchase.objects.create(library=_test_library(), **values)


def test_existing_endpoint_requires_auth():
    # Anonymous client hits an existing GET endpoint -> 401 after API-wide auth.
    response = Client().get("/api/platforms/groups")
    assert response.status_code == 401


def test_existing_endpoint_allows_logged_in(auth_client):
    response = auth_client.get("/api/platforms/groups")
    assert response.status_code == 200


def _played_on(device, started_at, **columns):
    """A projection row on the fixture game, on that device."""
    game, _ = Game.objects.get_or_create(library=_test_library(), name="Hades")
    return timed_row(
        tracked_run(_test_library(), game), started_at, None, device=device, **columns
    )


def test_device_search_blank_query_orders_by_most_recent_session(auth_client):
    desktop = _owned_device(name="Desktop")
    deck = _owned_device(name="Steam Deck")
    _played_on(desktop, datetime(2025, 1, 1, tzinfo=UTC))
    _played_on(deck, datetime(2026, 1, 1, tzinfo=UTC))

    rows = auth_client.get("/api/devices/search", {"limit": 10}).json()

    assert [row["value"] for row in rows][:2] == [str(deck.id), str(desktop.id)]


def test_device_search_orders_by_live_sessions_alone(auth_client):
    """A removed session moves no device."""
    desktop = _owned_device(name="Desktop")
    deck = _owned_device(name="Steam Deck")
    _played_on(desktop, datetime(2025, 1, 1, tzinfo=UTC))
    _played_on(deck, datetime(2024, 1, 1, tzinfo=UTC))
    _played_on(deck, datetime(2026, 1, 1, tzinfo=UTC), removed_at=datetime.now(tz=UTC))

    rows = auth_client.get("/api/devices/search", {"limit": 10}).json()

    assert [row["value"] for row in rows][:2] == [str(desktop.id), str(deck.id)]


def test_platform_search_blank_query_uses_newest_game_or_purchase(auth_client):
    atari = Platform.objects.create(name="Atari")
    switch = Platform.objects.create(name="Switch")
    old_game = _owned_game(name="Old game", platform=atari)
    recent_purchase = _owned_purchase(
        price_currency="CZK", platform=switch, date_purchased=date(2026, 1, 1)
    )
    Game.objects.filter(pk=old_game.pk).update(
        updated_at=datetime(2025, 1, 1, tzinfo=UTC)
    )
    Purchase.objects.filter(pk=recent_purchase.pk).update(
        updated_at=datetime(2026, 1, 1, tzinfo=UTC)
    )

    rows = auth_client.get("/api/platforms/search", {"limit": 10}).json()

    assert [row["value"] for row in rows][:2] == [str(switch.id), str(atari.id)]


def test_platform_search_blank_query_does_not_join_games_to_purchases(auth_client):
    platform = Platform.objects.create(name="PC")
    _owned_game(name="One", platform=platform)
    _owned_purchase(
        price_currency="CZK", platform=platform, date_purchased=date(2026, 1, 1)
    )

    with CaptureQueriesContext(connection) as queries:
        auth_client.get("/api/platforms/search", {"limit": 10})

    search_sql = next(
        query["sql"] for query in queries if 'FROM "games_platform"' in query["sql"]
    )
    assert 'LEFT OUTER JOIN "games_game"' not in search_sql
    assert 'LEFT OUTER JOIN "games_purchase"' not in search_sql


def test_device_search_typed_query_remains_alphabetical(auth_client):
    alpha = _owned_device(name="Alpha")
    alpine = _owned_device(name="Alpine")
    _played_on(alpha, datetime(2025, 1, 1, tzinfo=UTC))
    _played_on(alpine, datetime(2026, 1, 1, tzinfo=UTC))

    rows = auth_client.get("/api/devices/search", {"q": "Al", "limit": 10}).json()

    assert [row["value"] for row in rows] == [str(alpha.id), str(alpine.id)]


def test_platform_search_typed_query_remains_alphabetical(auth_client):
    alpha = Platform.objects.create(name="Alpha")
    alpine = Platform.objects.create(name="Alpine")
    recent_game = _owned_game(name="Recent", platform=alpine)
    Game.objects.filter(pk=recent_game.pk).update(
        updated_at=datetime(2026, 1, 1, tzinfo=UTC)
    )

    rows = auth_client.get("/api/platforms/search", {"q": "Al", "limit": 10}).json()

    assert [row["value"] for row in rows] == [str(alpha.id), str(alpine.id)]


def _row(**overrides):
    """A projection row on the fixture game and device."""
    if "game" not in overrides:
        platform, _ = Platform.objects.get_or_create(name="PC")
        overrides["game"] = _owned_game(name="Hades", platform=platform)
    if "device" not in overrides:
        overrides["device"] = _owned_device(name="Deck", type="h")
    game = overrides.pop("game")
    overrides.setdefault("started_at", datetime(2026, 6, 24, 18, 0, tzinfo=UTC))
    return session_row(game, **overrides)


def test_session_detail_shape(auth_client):
    session = _row(
        ended_at=datetime(2026, 6, 24, 19, 0, tzinfo=UTC),
        duration_manual=timedelta(minutes=30),
    )
    response = auth_client.get(f"/api/session/{session.id}")
    assert response.status_code == 200
    data = response.json()
    game = session.playthrough.player_game.game
    assert data["id"] == str(session.id)
    assert data["playthrough_id"] == str(session.playthrough_id)
    assert data["game"] == {
        "id": str(game.id),
        "name": "Hades",
        "platform": {"name": "PC", "icon": game.platform.icon},
    }
    assert data["device"] == {
        "id": str(session.device.id),
        "name": "Deck",
        "type": "h",
    }
    assert data["timing_mode"] == "corrected"
    assert data["started_at"] == "2026-06-24T18:00:00Z"
    assert data["ended_at"] == "2026-06-24T19:00:00Z"
    assert data["stated_day"] is None
    assert data["stated_duration_seconds"] == 5400
    assert data["duration_seconds"] == 5400
    assert data["day"] == "2026-06-24"
    assert data["emulated"] is False
    assert "created_at" in data
    assert "modified_at" not in data


def test_session_detail_running_timed_row(auth_client):
    session = _row()
    data = auth_client.get(f"/api/session/{session.id}").json()
    assert data["timing_mode"] == "timed"
    assert data["ended_at"] is None
    assert data["stated_duration_seconds"] is None
    assert data["duration_seconds"] == 0


def test_session_detail_duration_only_row(auth_client):
    game = _owned_game(name="Hades")
    session = duration_only_row(
        tracked_run(_test_library(), game), date(2026, 6, 24), timedelta(minutes=45)
    )
    data = auth_client.get(f"/api/session/{session.id}").json()
    assert data["timing_mode"] == "duration_only"
    assert data["started_at"] is None
    assert data["started_at_zone"] is None
    assert data["stated_day"] == "2026-06-24"
    assert data["day"] == "2026-06-24"
    assert data["stated_duration_seconds"] == 2700
    assert data["duration_seconds"] == 2700


def test_session_detail_labels_an_endpoint_zone(auth_client):
    session = _row(started_at_zone="Asia/Tokyo")
    data = auth_client.get(f"/api/session/{session.id}").json()
    assert data["started_at_zone"] == "Asia/Tokyo"
    assert data["started_at_zone_label"] == "JST"
    assert data["ended_at_zone_label"] is None


def test_session_detail_answers_no_row_another_library_holds(auth_client):
    stranger = get_user_model().objects.create_user(username="stranger", password="p")
    game = Game.objects.create(library=stranger.library, name="Theirs")
    session = session_row(game, started_at=datetime(2026, 6, 24, 18, 0, tzinfo=UTC))
    assert auth_client.get(f"/api/session/{session.id}").status_code == 404


def test_session_detail_404(auth_client):
    response = auth_client.get(f"/api/session/{uuid.uuid7()}")
    assert response.status_code == 404


def test_session_detail_requires_auth():
    session = _row()
    assert Client().get(f"/api/session/{session.id}").status_code == 401


def test_session_list_envelope(auth_client):
    for _ in range(3):
        _row()
    data = auth_client.get("/api/session/").json()
    assert set(data.keys()) == {"items", "count", "page", "page_size", "num_pages"}
    assert data["count"] == 3
    assert data["page"] == 1
    assert data["page_size"] == 10
    assert data["num_pages"] == 1
    assert len(data["items"]) == 3
    assert "id" in data["items"][0] and "game" in data["items"][0]


def test_session_list_pagination(auth_client):
    for _ in range(12):
        _row()
    page1 = auth_client.get("/api/session/").json()
    assert page1["count"] == 12
    assert page1["num_pages"] == 2
    assert len(page1["items"]) == 10
    page2 = auth_client.get("/api/session/?page=2").json()
    assert page2["page"] == 2
    assert len(page2["items"]) == 2


def test_session_list_sort_parity(auth_client):
    """`date` orders on `sort_instant`, across the modes."""
    older = _row(started_at=datetime(2020, 1, 1, tzinfo=UTC))
    written = duration_only_row(
        tracked_run(_test_library(), _owned_game(name="Celeste")),
        date(2023, 1, 1),
        timedelta(hours=1),
    )
    newer = _row(started_at=datetime(2026, 1, 1, tzinfo=UTC))
    ascending = auth_client.get("/api/session/?sort=date").json()["items"]
    ids = [row["id"] for row in ascending]
    assert ids == [str(older.id), str(written.id), str(newer.id)]
    descending = auth_client.get("/api/session/").json()["items"]
    assert [row["id"] for row in descending] == list(reversed(ids))


def test_session_list_filter_parity(auth_client):
    keep = _row()
    other_platform = Platform.objects.create(name="Switch")
    other_game = _owned_game(name="Celeste", platform=other_platform)
    _row(game=other_game)
    # Structured filter: sessions for the "keep" game only (INCLUDES).
    # PlayerSessionFilter.game is a UUIDMultiCriterion, and this hand-built
    # JSON has to carry the identity the way the wire does - as a string.
    session_filter = {
        "game": {
            "value": [str(keep.playthrough.player_game.game_id)],
            "modifier": "INCLUDES",
        }
    }
    response = auth_client.get("/api/session/", {"filter": json.dumps(session_filter)})
    items = response.json()["items"]
    assert [row["id"] for row in items] == [str(keep.id)]


def test_session_list_requires_auth():
    assert Client().get("/api/session/").status_code == 401


def test_session_list_page_overshoot_clamps(auth_client):
    # get_page clamps an out-of-range page to the last page instead of erroring,
    # so a JS client overshooting the end gets the last page, not a 404/500.
    for _ in range(3):
        _row()
    response = auth_client.get("/api/session/?page=999")
    assert response.status_code == 200
    data = response.json()
    assert data["page"] == data["num_pages"] == 1
    assert len(data["items"]) == 3


def test_session_list_malformed_filter_rejected(auth_client):
    # An invalid ?filter= (malformed JSON or a semantically-invalid filter) makes
    # parse_session_filter raise FilterError; the API turns that into a 400 rather
    # than 500-ing or silently returning the unfiltered list.
    for _ in range(2):
        _row()
    response = auth_client.get("/api/session/?filter=not-json")
    assert response.status_code == 400


def test_session_list_invalid_filter_semantics_rejected(auth_client):
    # Parseable JSON but a build-time-invalid filter (BETWEEN without value2) must
    # also be a 400, not a 500.
    bad = json.dumps({"duration_hours": {"modifier": "BETWEEN", "value": 1}})
    response = auth_client.get(f"/api/session/?filter={bad}")
    assert response.status_code == 400


def test_session_list_rejects_a_key_no_field_answers(auth_client):
    """A stored `is_manual` names no field now; dropping it would widen the
    filter in silence."""
    for stale in ("is_manual", "timestamp_start", "duration_total_hours"):
        stale_filter = json.dumps({stale: {"value": True}})
        response = auth_client.get(f"/api/session/?filter={stale_filter}")
        assert response.status_code == 400
        assert stale in response.json()["detail"]


def test_session_list_malformed_filter_logged(auth_client, capture_games_logger):
    # Issue #203: a rejected filter must leave a server-side warning so operators
    # can spot DoS-probing, in addition to the 400 the client sees.
    with capture_games_logger() as caplog:
        response = auth_client.get("/api/session/?filter=not-json")

    assert response.status_code == 400
    records = [record for record in caplog.records if record.name == "games"]
    # Assert each labelled field so a swapped/dropped positional arg is caught.
    assert any(
        record.levelno == logging.WARNING
        and "rejected invalid filter" in record.getMessage()
        and "entity=session" in record.getMessage()
        and "user=tester" in record.getMessage()
        and "path=/api/session/" in record.getMessage()
        for record in records
    )


def test_session_list_unknown_sort_rejected(auth_client):
    # Issue #207: an unknown ?sort= key must 400 (parity with the filter rejection
    # in the same handler) instead of silently returning default-sorted data.
    _row()
    response = auth_client.get("/api/session/?sort=bogusfield")
    assert response.status_code == 400
    assert "Invalid sort" in response.json()["detail"]


def test_session_list_unknown_sort_logged(auth_client, capture_games_logger):
    # Issue #207: the rejection must also leave a server-side warning, mirroring
    # the filter path, so ?sort=<garbage> probing is visible to operators.
    _row()
    with capture_games_logger() as caplog:
        response = auth_client.get("/api/session/?sort=bogusfield")

    assert response.status_code == 400
    records = [record for record in caplog.records if record.name == "games"]
    assert any(
        record.levelno == logging.WARNING
        and "rejected unknown sort field(s)" in record.getMessage()
        and "entity=session" in record.getMessage()
        and "user=tester" in record.getMessage()
        and "path=/api/session/" in record.getMessage()
        and "bogusfield" in record.getMessage()
        for record in records
    )


def test_session_list_valid_sort_still_ok(auth_client):
    # Regression: a valid ?sort= key is unaffected by the unknown-sort rejection.
    _row()
    response = auth_client.get("/api/session/?sort=-date")
    assert response.status_code == 200


def _patch_session(client, session_id, body):
    return client.patch(
        f"/api/session/{session_id}",
        data=json.dumps(body),
        content_type="application/json",
    )


#: Every PATCH dispatches, which opens its own transaction.
@pytest.mark.django_db(transaction=True)
def test_session_patch_timing_restates_the_whole_statement(auth_client, user):
    _prague_calendar(user)
    session = _row()
    response = _patch_session(
        auth_client,
        session.id,
        {
            "timing": {
                "started_at": "2026-06-24T18:00:00Z",
                "ended_at": "2026-06-24T19:00:00Z",
            }
        },
    )
    assert response.status_code == 200, response.content
    assert response.json()["ended_at"] == "2026-06-24T19:00:00Z"
    session.refresh_from_db()
    assert session.timing_mode == "timed"
    assert session.ended_at == datetime(2026, 6, 24, 19, 0, tzinfo=UTC)


@pytest.mark.django_db(transaction=True)
def test_session_patch_timing_is_told_apart_by_shape(auth_client, user):
    _prague_calendar(user)
    session = _row()
    response = _patch_session(
        auth_client,
        session.id,
        {"timing": {"day": "2026-06-25", "duration_seconds": 2700}},
    )
    assert response.status_code == 200, response.content
    body = response.json()
    assert body["timing_mode"] == "duration_only"
    assert body["stated_day"] == "2026-06-25"
    assert body["duration_seconds"] == 2700

    response = _patch_session(
        auth_client,
        session.id,
        {
            "timing": {
                "started_at": "2026-06-24T18:00:00Z",
                "ended_at": "2026-06-24T19:00:00Z",
                "duration_seconds": 5400,
            }
        },
    )
    assert response.status_code == 200, response.content
    assert response.json()["timing_mode"] == "corrected"
    assert response.json()["duration_seconds"] == 5400


@pytest.mark.django_db(transaction=True)
def test_session_patch_end_before_start_rejected(auth_client, user):
    _prague_calendar(user)
    session = _row()  # start 18:00
    response = _patch_session(
        auth_client,
        session.id,
        {
            "timing": {
                "started_at": "2026-06-24T18:00:00Z",
                "ended_at": "2026-06-24T17:00:00Z",
            }
        },
    )
    assert response.status_code == 409
    session.refresh_from_db()
    assert session.ended_at is None  # unchanged


@pytest.mark.django_db(transaction=True)
def test_session_patch_grows_the_games_playtime(auth_client, user):
    _prague_calendar(user)
    session = _row()
    game = session.playthrough.player_game.game
    library = _test_library()
    assert game_playtime(library, game).total == timedelta(0)
    _patch_session(
        auth_client,
        session.id,
        {
            "timing": {
                "started_at": "2026-06-24T18:00:00Z",
                "ended_at": "2026-06-24T19:00:00Z",
            }
        },
    )
    assert game_playtime(library, game).total == timedelta(hours=1)


@pytest.mark.django_db(transaction=True)
def test_session_patch_describes_one_fact_per_key(auth_client, user):
    _prague_calendar(user)
    session = _row()
    other = _owned_device(name="Desktop", type="p")
    response = _patch_session(
        auth_client,
        session.id,
        {"note": "boss fight", "device_id": str(other.id), "emulated": True},
    )
    assert response.status_code == 200, response.content
    session.refresh_from_db()
    assert (session.note, session.device_id, session.emulated) == (
        "boss fight",
        other.id,
        True,
    )
    assert (
        _patch_session(auth_client, session.id, {"device_id": None}).status_code == 200
    )
    session.refresh_from_db()
    assert session.device_id is None


@pytest.mark.django_db(transaction=True)
def test_session_patch_moves_the_run(auth_client, user):
    _prague_calendar(user)
    session = _row()
    other_run = tracked_run(_test_library(), _owned_game(name="Celeste"))
    response = _patch_session(
        auth_client, session.id, {"playthrough_id": str(other_run.pk)}
    )
    assert response.status_code == 200, response.content
    assert response.json()["playthrough_id"] == str(other_run.pk)


@pytest.mark.django_db(transaction=True)
def test_session_patch_refuses_a_key_it_does_not_know(auth_client, user):
    session = _row()
    for stale in ({"timestamp_end": "2026-06-24T19:00:00Z"}, {"timing": {"end": "x"}}):
        assert _patch_session(auth_client, session.id, stale).status_code == 422


@pytest.mark.django_db(transaction=True)
def test_session_patch_refuses_a_device_another_library_holds(auth_client, user):
    _prague_calendar(user)
    session = _row()
    stranger = get_user_model().objects.create_user(username="stranger", password="p")
    theirs = Device.objects.create(library=stranger.library, name="Theirs")
    response = _patch_session(auth_client, session.id, {"device_id": str(theirs.id)})
    assert response.status_code == 404
    session.refresh_from_db()
    assert session.device_id != theirs.id


def _prague_calendar(user):
    """The rows `session_rows` seeds count their days in Prague."""
    UserPreferences.objects.filter(user=user).update(display_time_zone="Europe/Prague")
    settings_resolver.clear_cache()


def test_session_patch_404(auth_client):
    assert _patch_session(auth_client, uuid.uuid7(), {"note": "x"}).status_code == 404


def test_session_patch_requires_auth():
    session = _row()
    response = _patch_session(Client(), session.id, {"note": "x"})
    assert response.status_code == 401


# ── POST /api/session/ — record a session (#1074) ────────────────────────────


def _post_session(client, body, **extra):
    return client.post(
        "/api/session/",
        data=json.dumps(body),
        content_type="application/json",
        **extra,
    )


def _tracked_run(name="Hades"):
    """This library's ordinary run at a game of its own."""
    platform, _ = Platform.objects.get_or_create(name="PC")
    return tracked_run(_test_library(), _owned_game(name=name, platform=platform))


#: Every POST dispatches, which opens its own transaction.
@pytest.mark.django_db(transaction=True)
def test_post_session_records_a_timed_session(auth_client, user):
    _prague_calendar(user)
    run = _tracked_run()

    response = _post_session(
        auth_client,
        {
            "playthrough_id": str(run.pk),
            "timing": {"started_at": "2026-06-24T18:00:00Z"},
        },
    )

    assert response.status_code == 201, response.content
    body = response.json()
    row = PlayerSession.objects.get(pk=body["id"])
    assert row.playthrough_id == run.pk
    assert body["timing_mode"] == "timed"
    assert body["day"] == row.effective_day.isoformat()


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    "timing,mode,duration_seconds",
    [
        ({"day": "2026-06-25", "duration_seconds": 2700}, "duration_only", 2700),
        (
            {
                "started_at": "2026-06-24T18:00:00Z",
                "ended_at": "2026-06-24T19:00:00Z",
                "duration_seconds": 5400,
            },
            "corrected",
            5400,
        ),
    ],
)
def test_post_session_records_each_timing_shape(
    auth_client, user, timing, mode, duration_seconds
):
    _prague_calendar(user)
    run = _tracked_run()

    response = _post_session(
        auth_client, {"playthrough_id": str(run.pk), "timing": timing}
    )

    assert response.status_code == 201, response.content
    body = response.json()
    assert body["timing_mode"] == mode
    assert body["duration_seconds"] == duration_seconds


@pytest.mark.django_db(transaction=True)
def test_post_session_records_the_described_facts(auth_client, user):
    _prague_calendar(user)
    run = _tracked_run()
    device = _owned_device(name="Deck", type="h")

    response = _post_session(
        auth_client,
        {
            "playthrough_id": str(run.pk),
            "timing": {"started_at": "2026-06-24T18:00:00Z"},
            "device_id": str(device.pk),
            "note": "one sitting",
            "emulated": True,
        },
    )

    assert response.status_code == 201, response.content
    body = response.json()
    assert body["note"] == "one sitting"
    assert body["emulated"] is True
    assert body["device"]["id"] == str(device.pk)
    row = PlayerSession.objects.get(pk=body["id"])
    assert row.device_id == device.pk
    assert row.note == "one sitting"
    assert row.emulated is True


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    "stale",
    [
        {"timing": {"started_at": "2026-06-24T18:00:00Z"}, "timestamp_end": "x"},
        {"timing": {"started_at": "2026-06-24T18:00:00Z", "end": "x"}},
    ],
)
def test_post_session_refuses_a_key_it_does_not_know(auth_client, user, stale):
    _prague_calendar(user)
    run = _tracked_run()

    response = _post_session(auth_client, {"playthrough_id": str(run.pk), **stale})

    assert response.status_code == 422
    assert not PlayerSession.objects.filter(playthrough=run).exists()


def test_post_session_requires_auth():
    run = _tracked_run()
    response = _post_session(
        Client(),
        {
            "playthrough_id": str(run.pk),
            "timing": {"started_at": "2026-06-24T18:00:00Z"},
        },
    )
    assert response.status_code == 401


# ── PATCH /api/session/{id}/device — nullable device (#290) ──────────────────


def _patch_device(client, session_id, body):
    return client.patch(
        f"/api/session/{session_id}/device",
        data=json.dumps(body),
        content_type="application/json",
    )


@pytest.mark.django_db(transaction=True)
def test_device_patch_assigns_device(auth_client):
    session = _row()
    other_device = _owned_device(name="Desktop", type="PC")
    response = _patch_device(
        auth_client, session.id, {"device_id": str(other_device.id)}
    )
    assert response.status_code == 204
    session.refresh_from_db()
    assert session.device == other_device


@pytest.mark.django_db(transaction=True)
def test_device_patch_unknown_device_404(auth_client):
    # A stale id (device deleted elsewhere) must 404 cleanly, not IntegrityError.
    session = _row()
    original_device = session.device
    response = _patch_device(auth_client, session.id, {"device_id": str(uuid.uuid7())})
    assert response.status_code == 404
    session.refresh_from_db()
    assert session.device == original_device


@pytest.mark.django_db(transaction=True)
def test_device_patch_null_clears_device(auth_client):
    session = _row()
    assert session.device is not None
    response = _patch_device(auth_client, session.id, {"device_id": None})
    assert response.status_code == 204
    session.refresh_from_db()
    assert session.device is None


def test_session_detail_serializes_null_device(auth_client):
    session = _row(device=None)
    data = auth_client.get(f"/api/session/{session.id}").json()
    assert data["device"] is None


# ── /api/filter/count — live result count for the nested filter builder (#195) ──


COUNT_URL = "/api/filter/count"


def _make_games(*names):
    platform = Platform.objects.create(name="PC")
    return [_owned_game(name=name, platform=platform) for name in names]


def test_filter_count_empty_filter_counts_all(auth_client):
    _make_games("Hades", "Celeste", "Braid")
    response = auth_client.get(COUNT_URL, {"model": "game"})
    assert response.status_code == 200
    assert response.json() == {"count": 3}


def test_filter_count_empty_object_counts_all(auth_client):
    # "{}" deserializes to an all-None filter whose to_q() is an empty Q() — the
    # same "match all" as an absent filter, not an error.
    _make_games("Hades", "Celeste")
    response = auth_client.get(COUNT_URL, {"model": "game", "filter": "{}"})
    assert response.status_code == 200
    assert response.json() == {"count": 2}


def test_filter_count_applies_filter(auth_client):
    # Discriminating: filter a 5-game set down to a 2-game subset so a regression
    # that silently matched-all (or returned the wrong branch) can't pass — the
    # expected count is strictly between 0 and the total.
    _make_games("Hades", "Hades II", "Celeste", "Braid", "Tunic")
    filter_json = json.dumps({"name": {"value": "Hades", "modifier": "INCLUDES"}})
    response = auth_client.get(COUNT_URL, {"model": "game", "filter": filter_json})
    assert response.status_code == 200
    # Parity with the real queryset the list view would build.
    parsed = parse_game_filter(filter_json)
    assert parsed is not None
    expected = Game.objects.filter(parsed.to_q()).count()
    assert expected == 2
    assert expected < Game.objects.count()
    assert response.json() == {"count": expected}


@pytest.mark.untracked_games
def test_filter_count_counts_only_tracked_games(auth_client):
    # The builder's live count is a promise about the list it navigates to,
    # and that list joins the projection.
    _make_games("Hades", "Celeste")
    response = auth_client.get(COUNT_URL, {"model": "game"})
    assert response.status_code == 200
    assert response.json() == {"count": 0}


def test_filter_count_non_game_model(auth_client):
    # The endpoint's whole point is genericity — prove a non-game model key
    # resolves its own filter class + queryset, not just "game".
    _owned_device(name="Deck", type="h")
    _owned_device(name="Desktop", type="d")
    response = auth_client.get(COUNT_URL, {"model": "device"})
    assert response.status_code == 200
    assert response.json() == {"count": Device.objects.count()}
    # And a filter actually applies against that model.
    filter_json = json.dumps({"name": {"value": "Deck", "modifier": "EQUALS"}})
    filtered = auth_client.get(COUNT_URL, {"model": "device", "filter": filter_json})
    assert filtered.json() == {"count": 1}


def test_filter_count_special_characters_round_trip(auth_client):
    # A value with quotes/ampersand/accented Latin must survive URL-encoding and match.
    tricky = 'Niño "quoted" & Zelda\'s'
    _make_games(tricky, "Other")
    filter_json = json.dumps({"name": {"value": tricky, "modifier": "EQUALS"}})
    response = auth_client.get(COUNT_URL, {"model": "game", "filter": filter_json})
    assert response.status_code == 200
    assert response.json() == {"count": 1}


def test_filter_count_unknown_model_rejected(auth_client):
    response = auth_client.get(COUNT_URL, {"model": "bogus"})
    assert response.status_code == 400


def test_filter_count_malformed_filter_rejected(auth_client):
    response = auth_client.get(COUNT_URL, {"model": "game", "filter": "not-json"})
    assert response.status_code == 400


def test_filter_count_invalid_filter_semantics_rejected(auth_client):
    # Parseable JSON, but a build-time-invalid filter (BETWEEN without value2) → 400.
    bad = json.dumps({"year_released": {"modifier": "BETWEEN", "value": 1}})
    response = auth_client.get(COUNT_URL, {"model": "game", "filter": bad})
    assert response.status_code == 400


def test_filter_count_requires_auth():
    response = Client().get(COUNT_URL, {"model": "game"})
    assert response.status_code == 401


def test_session_out_includes_zone_fields(auth_client):
    session = _row(started_at_zone="Asia/Tokyo")
    response = auth_client.get(f"/api/session/{session.pk}")
    payload = response.json()
    assert payload["started_at_zone"] == "Asia/Tokyo"
    assert payload["ended_at_zone"] is None


def test_session_out_ships_the_server_computed_zone_label(auth_client):
    """The label travels as data so a client-rebuilt row cannot word it
    differently from a server-rendered one (tzname "JST" vs Intl "GMT+9")."""
    session = _row(started_at_zone="Asia/Tokyo")
    payload = auth_client.get(f"/api/session/{session.pk}").json()
    assert payload["started_at_zone_label"] == "JST"
    assert payload["ended_at_zone_label"] is None


def test_a_zone_matching_the_account_zone_gets_no_label(auth_client):
    # DISPLAY_TIME_ZONE's registry default is "UTC" for a fresh user with no
    # preference set (settings_registry.py) — not the process's active
    # timezone, which is why this pins the literal rather than reading
    # django_timezone.get_current_timezone_name().
    session = _row(started_at_zone="UTC")
    payload = auth_client.get(f"/api/session/{session.pk}").json()
    assert payload["started_at_zone"] is not None
    assert payload["started_at_zone_label"] is None


def test_an_unusable_stored_zone_gets_no_label(auth_client):
    """A zone dropped from tzdata must not 500 a list page."""
    session = _row()
    PlayerSession.objects.filter(pk=session.pk).update(started_at_zone="Not/AZone")
    payload = auth_client.get(f"/api/session/{session.pk}").json()
    assert payload["started_at_zone"] == "Not/AZone"
    assert payload["started_at_zone_label"] is None


@pytest.mark.django_db(transaction=True)
def test_patch_finish_stores_the_end_zone(auth_client, user):
    _prague_calendar(user)
    session = _row()
    response = _patch_session(
        auth_client,
        session.pk,
        {
            "timing": {
                "started_at": "2026-06-24T18:00:00Z",
                "ended_at": "2026-07-01T13:00:00Z",
                "ended_at_zone": "Asia/Tokyo",
            }
        },
    )
    assert response.status_code == 200, response.content
    session.refresh_from_db()
    assert session.ended_at_zone == "Asia/Tokyo"
    assert session.started_at_zone is None  # untouched


@pytest.mark.django_db(transaction=True)
def test_patch_rejects_a_non_iana_zone(auth_client, user):
    _prague_calendar(user)
    session = _row()
    response = _patch_session(
        auth_client,
        session.pk,
        {
            "timing": {
                "started_at": "2026-06-24T18:00:00Z",
                "started_at_zone": "Not/AZone",
            }
        },
    )
    assert response.status_code == 409
    session.refresh_from_db()
    assert session.started_at_zone is None


@pytest.mark.django_db(transaction=True)
def test_patch_null_clears_a_stored_zone(auth_client, user):
    _prague_calendar(user)
    session = _row(started_at_zone="Asia/Tokyo")
    response = _patch_session(
        auth_client,
        session.pk,
        {"timing": {"started_at": "2026-06-24T18:00:00Z", "started_at_zone": None}},
    )
    assert response.status_code == 200, response.content
    session.refresh_from_db()
    assert session.started_at_zone is None
