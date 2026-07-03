import json
import logging
from datetime import datetime, timedelta, timezone as dt_timezone

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from games.filters import parse_game_filter
from games.models import Device, Game, Platform, Session

pytestmark = pytest.mark.django_db


@pytest.fixture
def user(db):
    return get_user_model().objects.create_user(username="tester", password="pw")


@pytest.fixture
def auth_client(user):
    client = Client()
    client.force_login(user)
    return client


def test_existing_endpoint_requires_auth():
    # Anonymous client hits an existing GET endpoint -> 401 after API-wide auth.
    response = Client().get("/api/platforms/groups")
    assert response.status_code == 401


def test_existing_endpoint_allows_logged_in(auth_client):
    response = auth_client.get("/api/platforms/groups")
    assert response.status_code == 200


def _make_session(**overrides):
    # Only build the default game/device when the caller didn't supply one, so a
    # call like _make_session(game=other) doesn't leave a throwaway Game/Platform
    # in the DB that could skew count-based assertions.
    if "game" not in overrides:
        platform = Platform.objects.create(name="PC")
        overrides["game"] = Game.objects.create(name="Hades", platform=platform)
    if "device" not in overrides:
        overrides["device"] = Device.objects.create(name="Deck", type="h")
    fields = dict(
        timestamp_start=datetime(2026, 6, 24, 18, 0, tzinfo=dt_timezone.utc),
        timestamp_end=None,
        duration_manual=timedelta(0),
        note="",
        emulated=False,
    )
    fields.update(overrides)
    return Session.objects.create(**fields)


def test_session_detail_shape(auth_client):
    session = _make_session(
        timestamp_end=datetime(2026, 6, 24, 19, 0, tzinfo=dt_timezone.utc),
        duration_manual=timedelta(minutes=30),
    )
    response = auth_client.get(f"/api/session/{session.id}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == session.id
    assert data["game"] == {
        "id": session.game.id,
        "name": "Hades",
        "platform": {"name": "PC", "icon": session.game.platform.icon},
    }
    assert data["device"] == {"id": session.device.id, "name": "Deck", "type": "h"}
    assert data["timestamp_start"] == "2026-06-24T18:00:00Z"
    assert data["timestamp_end"] == "2026-06-24T19:00:00Z"
    assert data["duration_manual_seconds"] == 1800
    assert data["is_manual"] is True
    assert data["emulated"] is False
    assert "modified_at" in data and "created_at" in data


def test_session_detail_open_session_null_end(auth_client):
    session = _make_session()  # timestamp_end=None, manual=0
    data = auth_client.get(f"/api/session/{session.id}").json()
    assert data["timestamp_end"] is None
    assert data["duration_manual_seconds"] == 0
    assert data["is_manual"] is False


@pytest.mark.parametrize(
    "manual,expected",
    [
        (timedelta(0), False),
        (timedelta(minutes=5), True),
        (timedelta(minutes=-5), True),  # negative still counts as manual
    ],
)
def test_session_is_manual_matrix(auth_client, manual, expected):
    # NB: Session.save() coerces a None duration_manual to timedelta(0),
    # so the null case is unreachable via normal save and not tested here.
    # is_manual is shipped explicitly (not derived client-side) to stay correct
    # for negative/sub-second durations and to match server display exactly.
    session = _make_session(duration_manual=manual)
    data = auth_client.get(f"/api/session/{session.id}").json()
    assert data["is_manual"] is expected


def test_session_detail_404(auth_client):
    response = auth_client.get("/api/session/999999")
    assert response.status_code == 404


def test_session_detail_requires_auth():
    session = _make_session()
    assert Client().get(f"/api/session/{session.id}").status_code == 401


def test_session_list_envelope(auth_client):
    for _ in range(3):
        _make_session()
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
        _make_session()
    page1 = auth_client.get("/api/session/").json()
    assert page1["count"] == 12
    assert page1["num_pages"] == 2
    assert len(page1["items"]) == 10
    page2 = auth_client.get("/api/session/?page=2").json()
    assert page2["page"] == 2
    assert len(page2["items"]) == 2


def test_session_list_sort_parity(auth_client):
    older = _make_session(timestamp_start=datetime(2020, 1, 1, tzinfo=dt_timezone.utc))
    newer = _make_session(timestamp_start=datetime(2026, 1, 1, tzinfo=dt_timezone.utc))
    ascending = auth_client.get("/api/session/?sort=date").json()["items"]
    ids = [row["id"] for row in ascending]
    assert ids.index(older.id) < ids.index(newer.id)


def test_session_list_filter_parity(auth_client):
    keep = _make_session()
    other_platform = Platform.objects.create(name="Switch")
    other_game = Game.objects.create(name="Celeste", platform=other_platform)
    _make_session(game=other_game)
    # Structured filter: sessions for the "keep" game only (game MultiCriterion INCLUDES).
    # SessionFilter.game is MultiCriterion — JSON: {"game": {"value": [id], "modifier": "INCLUDES"}}
    session_filter = {
        "game": {
            "value": [keep.game.id],
            "modifier": "INCLUDES",
        }
    }
    response = auth_client.get("/api/session/", {"filter": json.dumps(session_filter)})
    items = response.json()["items"]
    assert [row["id"] for row in items] == [keep.id]


def test_session_list_requires_auth():
    assert Client().get("/api/session/").status_code == 401


def test_session_list_page_overshoot_clamps(auth_client):
    # get_page clamps an out-of-range page to the last page instead of erroring,
    # so a JS client overshooting the end gets the last page, not a 404/500.
    for _ in range(3):
        _make_session()
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
        _make_session()
    response = auth_client.get("/api/session/?filter=not-json")
    assert response.status_code == 400


def test_session_list_invalid_filter_semantics_rejected(auth_client):
    # Parseable JSON but a build-time-invalid filter (BETWEEN without value2) must
    # also be a 400, not a 500.
    bad = json.dumps({"duration_total_hours": {"modifier": "BETWEEN", "value": 1}})
    response = auth_client.get(f"/api/session/?filter={bad}")
    assert response.status_code == 400


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
    _make_session()
    response = auth_client.get("/api/session/?sort=bogusfield")
    assert response.status_code == 400
    assert "Invalid sort" in response.json()["detail"]


def test_session_list_unknown_sort_logged(auth_client, capture_games_logger):
    # Issue #207: the rejection must also leave a server-side warning, mirroring
    # the filter path, so ?sort=<garbage> probing is visible to operators.
    _make_session()
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
    _make_session()
    response = auth_client.get("/api/session/?sort=-date")
    assert response.status_code == 200


def _patch_session(client, session_id, body):
    return client.patch(
        f"/api/session/{session_id}",
        data=json.dumps(body),
        content_type="application/json",
    )


def test_session_patch_finish_sets_end(auth_client):
    # Open session finished by sending the client's "now" as timestamp_end.
    session = _make_session()  # start 2026-06-24 18:00, end None
    response = _patch_session(
        auth_client, session.id, {"timestamp_end": "2026-06-24T19:00:00Z"}
    )
    assert response.status_code == 200
    assert response.json()["timestamp_end"] == "2026-06-24T19:00:00Z"
    session.refresh_from_db()
    assert session.timestamp_end == datetime(2026, 6, 24, 19, 0, tzinfo=dt_timezone.utc)


def test_session_patch_reset_start_keeps_end_null(auth_client):
    # Reset overwrites timestamp_start; an omitted timestamp_end is untouched.
    session = _make_session()
    response = _patch_session(
        auth_client, session.id, {"timestamp_start": "2026-06-24T20:00:00Z"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["timestamp_start"] == "2026-06-24T20:00:00Z"
    assert body["timestamp_end"] is None
    session.refresh_from_db()
    assert session.timestamp_start == datetime(
        2026, 6, 24, 20, 0, tzinfo=dt_timezone.utc
    )


def test_session_patch_end_before_start_rejected(auth_client):
    session = _make_session()  # start 18:00
    response = _patch_session(
        auth_client, session.id, {"timestamp_end": "2026-06-24T17:00:00Z"}
    )
    assert response.status_code == 422
    session.refresh_from_db()
    assert session.timestamp_end is None  # unchanged


def test_session_patch_recalcs_playtime_via_signal(auth_client):
    # Finishing an open session grows duration_total; the post_save Session
    # signal must recompute Game.playtime (we never set playtime by hand).
    session = _make_session()
    assert session.game.playtime == timedelta(0)
    _patch_session(auth_client, session.id, {"timestamp_end": "2026-06-24T19:00:00Z"})
    session.game.refresh_from_db()
    assert session.game.playtime == timedelta(hours=1)


def test_session_patch_does_not_write_generatedfield(auth_client):
    # duration_total is a DB-computed GeneratedField; after a finish PATCH it must
    # reflect the new end without the handler ever writing it.
    session = _make_session()
    _patch_session(auth_client, session.id, {"timestamp_end": "2026-06-24T19:00:00Z"})
    session.refresh_from_db()
    assert session.duration_total == timedelta(hours=1)


def test_session_patch_404(auth_client):
    assert _patch_session(auth_client, 999999, {"note": "x"}).status_code == 404


def test_session_patch_requires_auth():
    session = _make_session()
    response = _patch_session(
        Client(), session.id, {"timestamp_end": "2026-06-24T19:00:00Z"}
    )
    assert response.status_code == 401


# ── PATCH /api/session/{id}/device — nullable device (#290) ──────────────────


def _patch_device(client, session_id, body):
    return client.patch(
        f"/api/session/{session_id}/device",
        data=json.dumps(body),
        content_type="application/json",
    )


def test_device_patch_assigns_device(auth_client):
    session = _make_session()
    other_device = Device.objects.create(name="Desktop", type="PC")
    response = _patch_device(auth_client, session.id, {"device_id": other_device.id})
    assert response.status_code == 204
    session.refresh_from_db()
    assert session.device == other_device


def test_device_patch_unknown_device_404(auth_client):
    # A stale id (device deleted elsewhere) must 404 cleanly, not IntegrityError.
    session = _make_session()
    original_device = session.device
    response = _patch_device(auth_client, session.id, {"device_id": 999999})
    assert response.status_code == 404
    session.refresh_from_db()
    assert session.device == original_device


def test_device_patch_null_clears_device(auth_client):
    session = _make_session()
    assert session.device is not None
    response = _patch_device(auth_client, session.id, {"device_id": None})
    assert response.status_code == 204
    session.refresh_from_db()
    assert session.device is None


def test_session_detail_serializes_null_device(auth_client):
    session = _make_session(device=None)
    data = auth_client.get(f"/api/session/{session.id}").json()
    assert data["device"] is None


# ── /api/filter/count — live result count for the nested filter builder (#195) ──


COUNT_URL = "/api/filter/count"


def _make_games(*names):
    platform = Platform.objects.create(name="PC")
    return [Game.objects.create(name=name, platform=platform) for name in names]


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


def test_filter_count_non_game_model(auth_client):
    # The endpoint's whole point is genericity — prove a non-game model key
    # resolves its own filter class + queryset, not just "game".
    Device.objects.create(name="Deck", type="h")
    Device.objects.create(name="Desktop", type="d")
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
