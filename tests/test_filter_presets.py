"""Tests for the FilterPreset endpoints (games/views/filter_presets.py):

- #206: save_preset rejects malformed/invalid filter JSON + unknown modes with a
  server-side warning log + user-facing error + non-201 (no silent match-everything).
- #209: list_presets renders via the component layer, escaping user-controlled
  preset.name (stored-XSS fix).
- list_presets validates `mode` (no NoReverseMatch 500).
- Per-user ownership: presets are scoped to their creator (no IDOR across users).
- delete_preset is DELETE-only (no CSRF-via-GET self-deletion).
"""

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


@pytest.fixture
def second_user(db):
    return get_user_model().objects.create_user(username="other", password="pw")


@pytest.fixture
def second_auth_client(second_user):
    client = Client()
    client.force_login(second_user)
    return client


def _save(client, **data):
    return client.post(reverse("games:save_preset"), data)


def _messages(response):
    return [str(message) for message in response.wsgi_request._messages]


def test_valid_filter_creates_preset_and_logs_nothing(
    user, auth_client, capture_games_logger
):
    valid = json.dumps({"name": {"modifier": "INCLUDES", "value": "halo"}})
    with capture_games_logger() as caplog:
        response = _save(auth_client, name="My preset", mode="games", filter=valid)

    assert response.status_code == 201
    preset = FilterPreset.objects.get()
    assert preset.object_filter == {"name": {"modifier": "INCLUDES", "value": "halo"}}
    assert preset.user == user  # owner is set
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


# --- list_presets: escaping, mode validation ---------------------------------


def _list(client, mode="games"):
    return client.get(reverse("games:list_presets"), {"mode": mode})


def test_list_presets_escapes_preset_name(auth_client):
    # #209: a malicious name must be HTML-escaped, not rendered as live markup.
    _save(
        auth_client,
        name="<img src=x onerror=alert(1)>",
        mode="games",
        filter="",
    )
    body = _list(auth_client).content
    assert b"<img src=x onerror" not in body  # not raw (would execute)
    assert b"&lt;img" in body  # escaped (proves escape, not strip)


def test_list_presets_escapes_filter_in_href(auth_client):
    # The object_filter is serialized into the row's href; a `"` in it must not
    # break out of the attribute. It is quote()-encoded (-> %22), so no raw `"`
    # from the filter appears unencoded in the link.
    quoted = json.dumps({"name": {"modifier": "INCLUDES", "value": 'a"b'}})
    _save(auth_client, name="Quote", mode="games", filter=quoted)
    body = _list(auth_client).content.decode()
    href = body[body.index("?filter=") : body.index('"', body.index("?filter="))]
    assert '"' not in href
    assert "%22" in href


def test_list_presets_rejects_unknown_mode(auth_client):
    # Unknown mode used to 500 via reverse(f"games:list_{mode}"); now a clean 400.
    assert _list(auth_client, mode="bogus").status_code == 400


def test_list_presets_empty_state(auth_client):
    assert b"No saved presets" in _list(auth_client).content


# --- per-user ownership (IDOR) + delete method guard -------------------------


def _make_preset(client, name="P"):
    valid = json.dumps({"name": {"modifier": "INCLUDES", "value": "x"}})
    _save(client, name=name, mode="games", filter=valid)
    return FilterPreset.objects.get(name=name)


def test_list_presets_only_returns_own(auth_client, second_auth_client):
    _make_preset(auth_client, name="MineAlone")
    assert b"MineAlone" not in _list(second_auth_client).content


def test_delete_preset_requires_ownership(auth_client, second_auth_client):
    preset = _make_preset(auth_client)
    response = second_auth_client.delete(
        reverse("games:delete_preset", args=[preset.id])
    )
    assert response.status_code == 404
    assert FilterPreset.objects.filter(id=preset.id).exists()  # not deleted


def test_load_preset_requires_ownership(auth_client, second_auth_client):
    preset = _make_preset(auth_client)
    response = second_auth_client.get(reverse("games:load_preset", args=[preset.id]))
    assert response.status_code == 404


def test_owner_can_delete_via_delete_method(auth_client):
    preset = _make_preset(auth_client)
    response = auth_client.delete(reverse("games:delete_preset", args=[preset.id]))
    assert response.status_code == 200
    assert not FilterPreset.objects.filter(id=preset.id).exists()


@pytest.mark.parametrize("method", ["get", "post"])
def test_delete_preset_rejects_non_delete_methods(auth_client, method):
    # DELETE-only: a GET (e.g. <img src=.../>) must not delete (CSRF-via-GET).
    preset = _make_preset(auth_client)
    response = getattr(auth_client, method)(
        reverse("games:delete_preset", args=[preset.id])
    )
    assert response.status_code == 405
    assert FilterPreset.objects.filter(id=preset.id).exists()
