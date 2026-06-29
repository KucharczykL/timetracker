"""Issue #206: save_preset must reject malformed/invalid filter JSON and unknown
modes with a server-side warning log + user-facing error + non-201, instead of
silently storing a match-everything filter behind a success toast."""

import json
import logging

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from games.models import FilterPreset


@pytest.fixture
def user(db):
    return get_user_model().objects.create_user(username="tester", password="pw")


@pytest.fixture
def auth_client(user):
    client = Client()
    client.force_login(user)
    return client


def _save(client, **data):
    return client.post(reverse("games:save_preset"), data)


def _messages(response):
    return [str(message) for message in response.wsgi_request._messages]


def test_valid_filter_creates_preset_and_logs_nothing(
    auth_client, capture_games_logger
):
    valid = json.dumps({"name": {"modifier": "INCLUDES", "value": "halo"}})
    with capture_games_logger() as caplog:
        response = _save(auth_client, name="My preset", mode="games", filter=valid)

    assert response.status_code == 201
    preset = FilterPreset.objects.get()
    assert preset.object_filter == {"name": {"modifier": "INCLUDES", "value": "halo"}}
    assert not [record for record in caplog.records if record.name == "games"]


def test_empty_filter_creates_preset_with_empty_object_filter(auth_client):
    response = _save(auth_client, name="Empty", mode="games", filter="")
    assert response.status_code == 201
    assert FilterPreset.objects.get().object_filter == {}


def test_malformed_json_rejected_logged_and_no_row(auth_client, capture_games_logger):
    with capture_games_logger() as caplog:
        response = _save(auth_client, name="Bad", mode="games", filter="{not json")

    assert response.status_code == 400
    assert not FilterPreset.objects.exists()
    records = [record for record in caplog.records if record.name == "games"]
    assert any(
        record.levelno == logging.WARNING
        and "rejected preset save" in record.getMessage()
        and "mode=games" in record.getMessage()
        for record in records
    )
    assert any("Invalid filter" in message for message in _messages(response))


def test_semantically_invalid_filter_rejected(auth_client, capture_games_logger):
    # Parseable JSON, build-time-invalid filter (BETWEEN without value2).
    bad = json.dumps({"year_released": {"modifier": "BETWEEN", "value": 2000}})
    with capture_games_logger() as caplog:
        response = _save(auth_client, name="Bad", mode="games", filter=bad)

    assert response.status_code == 400
    assert not FilterPreset.objects.exists()
    assert any(
        "rejected preset save" in record.getMessage()
        for record in caplog.records
        if record.name == "games"
    )
    assert any("Invalid filter" in message for message in _messages(response))


def test_null_filter_creates_empty_preset(auth_client):
    # JSON `null` legitimately means "no filter" -> empty object_filter + 201.
    response = _save(auth_client, name="Null", mode="games", filter="null")
    assert response.status_code == 201
    assert FilterPreset.objects.get().object_filter == {}


def test_non_object_filter_rejected(auth_client, capture_games_logger):
    # Valid JSON that is not a filter object (scalar/array) is a malformed
    # payload, not "no filter": reject it rather than silently saving {} + 201.
    for payload in ("[1, 2]", "5"):
        with capture_games_logger() as caplog:
            response = _save(auth_client, name="X", mode="games", filter=payload)
        assert response.status_code == 400, payload
        assert not FilterPreset.objects.exists()
        assert any(
            "not an object" in record.getMessage()
            for record in caplog.records
            if record.name == "games"
        ), payload


def test_unknown_mode_rejected(auth_client, capture_games_logger):
    valid = json.dumps({"name": {"modifier": "INCLUDES", "value": "halo"}})
    with capture_games_logger() as caplog:
        response = _save(auth_client, name="X", mode="bogus", filter=valid)

    assert response.status_code == 400
    assert not FilterPreset.objects.exists()
    assert any(
        "unknown mode" in record.getMessage()
        for record in caplog.records
        if record.name == "games"
    )


def test_valid_non_games_mode_round_trips(auth_client):
    # A non-`games` mode must resolve to its parser and store the filter — guards
    # against a missing/mistyped MODE_PARSERS key rejecting a legitimate mode.
    sessions_filter = json.dumps({"note": {"modifier": "INCLUDES", "value": "boss"}})
    response = _save(
        auth_client, name="Sessions", mode="sessions", filter=sessions_filter
    )
    assert response.status_code == 201
    preset = FilterPreset.objects.get()
    assert preset.mode == "sessions"
    assert preset.object_filter == {"note": {"modifier": "INCLUDES", "value": "boss"}}


def test_mode_parsers_cover_every_mode_choice():
    # MODE_PARSERS is the source of truth for which modes save_preset accepts;
    # it must stay in sync with the model's choices or a valid mode 400s.
    from games.views.filter_presets import MODE_PARSERS

    assert set(MODE_PARSERS) == {value for value, _label in FilterPreset.MODE_CHOICES}


def test_missing_name_rejected(auth_client):
    response = _save(auth_client, name="", mode="games", filter="")
    assert response.status_code == 400
    assert not FilterPreset.objects.exists()
