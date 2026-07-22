"""Tests for the FilterPreset API endpoints (/api/presets, games/api.py).

Ported from the classic-view suite when the preset dropdown became a combobox
personality (#297) and the endpoints moved to Django Ninja:

- #206: save rejects semantically invalid filters with a warning log + 400; the
  old "filter is not an object" hand-rolled guard is subsumed by the PresetIn
  schema (`filter: dict | None`), which 422s scalar/array payloads before the
  handler runs — those framework rejections intentionally log nothing.
- #212: upsert on (user, mode, name); 201 create vs 200 update.
- Per-user ownership: presets are scoped to their creator (no IDOR across users).
- Mode validation on list and save (unknown mode -> 400, not 500).

Dead with the classic views (documented casualties):
- #209 HTML-escaping tests: the endpoint returns JSON; preset names are rendered
  client-side through the combobox label slot (`textContent` only), guarded by a
  vitest asserting a hostile label cannot inject markup. A JSON round-trip test
  below keeps the raw-name property visible.
- load_preset redirect tests: the endpoint is gone; picks navigate client-side.
- The malformed-JSON warning-log assertion: malformed request bodies never reach
  the handler (Ninja rejects them), so there is nothing to log.
"""

import json
import logging

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
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


def _presets_url() -> str:
    return reverse("api-1.0.0:list_presets")


def _delete_url(preset_id: int) -> str:
    return reverse("api-1.0.0:delete_preset", args=[preset_id])


def _save(client, *, name, mode="games", filter=None, sort=None, per_page=None):
    body = {"name": name, "mode": mode, "filter": filter}
    if sort is not None:
        body["sort"] = sort
    if per_page is not None:
        body["per_page"] = per_page
    return client.post(
        _presets_url(),
        json.dumps(body),
        content_type="application/json",
    )


def _list(client, mode="games", **params):
    return client.get(_presets_url(), {"mode": mode, **params})


def _make_preset(client, name="P"):
    _save(client, name=name, filter={"name": {"modifier": "INCLUDES", "value": "x"}})
    return FilterPreset.objects.get(name=name)


def test_presets_url_is_the_documented_path():
    # The client builds DELETE URLs as `base + id`, so the reversed base must be
    # the trailing-slash collection path.
    assert _presets_url() == "/api/presets/"


# --- auth: every endpoint requires a session ---------------------------------


def test_anonymous_is_rejected_on_all_endpoints(db):
    # New property vs the classic views (which 302-redirected to login):
    # django_auth returns 401 for anonymous API calls.
    anonymous = Client()
    assert anonymous.get(_presets_url()).status_code == 401
    assert (
        anonymous.post(
            _presets_url(),
            json.dumps({"name": "X", "mode": "games", "filter": None}),
            content_type="application/json",
        ).status_code
        == 401
    )
    assert anonymous.delete(_delete_url(1)).status_code == 401


# --- save: validation, logging, upsert ----------------------------------------


def test_valid_filter_creates_preset_and_logs_nothing(
    user, auth_client, capture_games_logger
):
    valid = {"name": {"modifier": "INCLUDES", "value": "halo"}}
    with capture_games_logger() as caplog:
        response = _save(auth_client, name="My preset", filter=valid)

    assert response.status_code == 201
    preset = FilterPreset.objects.get()
    assert preset.object_filter == valid
    assert preset.user == user  # owner is set
    assert not [record for record in caplog.records if record.name == "games"]


def test_null_filter_creates_empty_preset(auth_client):
    # `filter: null` (and an omitted filter) legitimately mean "no filter".
    response = _save(auth_client, name="Null", filter=None)
    assert response.status_code == 201
    assert FilterPreset.objects.get().object_filter == {}


def test_semantically_invalid_filter_rejected(auth_client, capture_games_logger):
    # Well-formed JSON object, build-time-invalid filter (BETWEEN without value2).
    bad = {"year_released": {"modifier": "BETWEEN", "value": 2000}}
    with capture_games_logger() as caplog:
        response = _save(auth_client, name="Bad", filter=bad)

    assert response.status_code == 400
    assert not FilterPreset.objects.exists()
    assert any(
        record.levelno == logging.WARNING
        and "rejected preset save" in record.getMessage()
        and "mode=games" in record.getMessage()
        for record in caplog.records
        if record.name == "games"
    )
    assert "Invalid filter" in response.json()["detail"]


@pytest.mark.parametrize("payload", [[1, 2], 5, "text"])
def test_non_object_filter_rejected_by_schema(auth_client, payload):
    # PresetIn declares `filter: dict | None`, so Ninja rejects scalars/arrays
    # with a 422 before the handler runs — the schema replaces the old
    # hand-rolled "filter is not an object" guard (#206). No warning log: the
    # request never reaches application code.
    response = _save(auth_client, name="X", filter=payload)
    assert response.status_code == 422
    assert not FilterPreset.objects.exists()


def test_malformed_json_body_rejected_by_framework(auth_client):
    # A syntactically broken body dies in Ninja's parser, not in the handler.
    response = auth_client.post(
        _presets_url(), "{not json", content_type="application/json"
    )
    assert response.status_code == 400
    assert not FilterPreset.objects.exists()


def test_unknown_mode_rejected(auth_client, capture_games_logger):
    valid = {"name": {"modifier": "INCLUDES", "value": "halo"}}
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
    sessions_filter = {"note": {"modifier": "INCLUDES", "value": "boss"}}
    response = _save(
        auth_client, name="Sessions", mode="sessions", filter=sessions_filter
    )
    assert response.status_code == 201
    preset = FilterPreset.objects.get()
    assert preset.mode == "sessions"
    assert preset.object_filter == sessions_filter


def test_mode_parsers_cover_every_mode_choice():
    # MODE_PARSERS is the source of truth for which modes the API accepts;
    # it must stay in sync with the model's choices or a valid mode 400s.
    from games.filters import MODE_PARSERS

    assert set(MODE_PARSERS) == {value for value, _label in FilterPreset.MODE_CHOICES}


def test_mode_sorts_is_a_subset_of_mode_choices():
    # MODE_SORTS gates which modes persist a preset sort. Every key must be a
    # real mode, or save_preset would gate on a mode that can never match (#77).
    from games.sorting import MODE_SORTS

    assert set(MODE_SORTS) <= {value for value, _label in FilterPreset.MODE_CHOICES}


# ── Sort round-trip (#77) ────────────────────────────────────────────────────


def test_save_persists_sort_in_find_filter(auth_client):
    _save(auth_client, name="Sorted", mode="games", filter=None, sort="-playtime,name")
    preset = FilterPreset.objects.get(name="Sorted")
    assert preset.find_filter == {"sort": "-playtime,name"}


def test_save_without_sort_stores_empty_find_filter(auth_client):
    _save(auth_client, name="Unsorted", mode="games", filter=None)
    preset = FilterPreset.objects.get(name="Unsorted")
    assert preset.find_filter == {}


def test_save_persists_sort_for_playevents_mode(auth_client):
    # #335 gave playevents/devices/platforms sort maps, so their presets now
    # round-trip a sort just like games/sessions/purchases (the MODE_SORTS gate
    # in save_preset admits them). Previously playevents was sort-less and dropped
    # the sort.
    _save(auth_client, name="PE", mode="playevents", filter=None, sort="-created")
    preset = FilterPreset.objects.get(name="PE")
    assert preset.find_filter == {"sort": "-created"}


def test_list_emits_persisted_sort(auth_client):
    _save(auth_client, name="Sorted", mode="games", filter=None, sort="-playtime")
    preset = FilterPreset.objects.get(name="Sorted")
    payload = _list(auth_client).json()
    assert payload == [
        {
            "value": preset.id,
            "label": "Sorted",
            "data": {"filter": "{}", "sort": "-playtime", "per_page": ""},
        }
    ]


def test_resaving_updates_sort_in_place(auth_client):
    _save(auth_client, name="V", mode="games", filter=None, sort="-playtime")
    _save(auth_client, name="V", mode="games", filter=None, sort="name")
    preset = FilterPreset.objects.get(name="V")
    assert preset.find_filter == {"sort": "name"}


def test_resaving_without_sort_clears_stored_sort(auth_client):
    # find_filter is part of the upsert defaults, so re-saving with no sort must
    # overwrite a previously-stored sort rather than leaving it stale.
    _save(auth_client, name="V", mode="games", filter=None, sort="-playtime")
    _save(auth_client, name="V", mode="games", filter=None)
    preset = FilterPreset.objects.get(name="V")
    assert preset.find_filter == {}


# ── Page-size round-trip ─────────────────────────────────────────────────────


def test_save_persists_non_default_per_page(auth_client):
    _save(auth_client, name="Big", mode="games", filter=None, per_page="100")
    preset = FilterPreset.objects.get(name="Big")
    assert preset.find_filter == {"per_page": 100}


def test_save_explicit_default_per_page_is_pinned(auth_client):
    from games.filters import FindFilter

    _save(
        auth_client,
        name="Default",
        mode="games",
        filter=None,
        per_page=str(FindFilter.per_page),
    )
    preset = FilterPreset.objects.get(name="Default")
    assert preset.find_filter == {"per_page": FindFilter.per_page}


def test_save_zero_per_page_is_persisted(auth_client):
    _save(auth_client, name="All", mode="games", filter=None, per_page="0")
    preset = FilterPreset.objects.get(name="All")
    assert preset.find_filter == {"per_page": 0}


def test_save_non_integer_per_page_stores_nothing(auth_client):
    _save(auth_client, name="Junk", mode="games", filter=None, per_page="lots")
    preset = FilterPreset.objects.get(name="Junk")
    assert preset.find_filter == {}


def test_save_negative_per_page_stores_nothing(auth_client):
    _save(auth_client, name="Neg", mode="games", filter=None, per_page="-5")
    preset = FilterPreset.objects.get(name="Neg")
    assert preset.find_filter == {}


def test_save_persists_sort_and_per_page_together(auth_client):
    _save(
        auth_client,
        name="Both",
        mode="games",
        filter=None,
        sort="-playtime",
        per_page="50",
    )
    preset = FilterPreset.objects.get(name="Both")
    assert preset.find_filter == {"sort": "-playtime", "per_page": 50}


def test_save_persists_per_page_for_non_games_mode(auth_client):
    _save(auth_client, name="PE", mode="playevents", filter=None, per_page="50")
    preset = FilterPreset.objects.get(name="PE")
    assert preset.find_filter == {"per_page": 50}


def test_list_emits_persisted_per_page(auth_client):
    _save(auth_client, name="Big", mode="games", filter=None, per_page="100")
    preset = FilterPreset.objects.get(name="Big")
    payload = _list(auth_client).json()
    assert payload == [
        {
            "value": preset.id,
            "label": "Big",
            "data": {"filter": "{}", "sort": "", "per_page": "100"},
        }
    ]


@pytest.mark.parametrize("stored", [-5, True, 25.0, "25", "lots"])
def test_list_degrades_corrupt_stored_per_page_to_inherited(auth_client, user, stored):
    preset = FilterPreset.objects.create(
        user=user,
        name="Corrupt",
        mode="games",
        object_filter={},
        find_filter={"per_page": stored},
    )

    assert _list(auth_client).json() == [
        {
            "value": preset.id,
            "label": "Corrupt",
            "data": {"filter": "{}", "sort": "", "per_page": ""},
        }
    ]


def test_resaving_without_per_page_clears_stored_per_page(auth_client):
    _save(auth_client, name="V", mode="games", filter=None, per_page="100")
    _save(auth_client, name="V", mode="games", filter=None)
    preset = FilterPreset.objects.get(name="V")
    assert preset.find_filter == {}


def test_missing_name_rejected(auth_client):
    response = _save(auth_client, name="   ", filter=None)
    assert response.status_code == 400
    assert not FilterPreset.objects.exists()


# --- list: shape, scoping, filtering ------------------------------------------


def test_list_shape_round_trips_object_filter(auth_client):
    # The picker consumes SearchSelectOption dicts; data.filter must carry the
    # stored object_filter as a JSON string the client can parse and apply.
    stored = {"name": {"modifier": "INCLUDES", "value": "halo"}}
    _save(auth_client, name="Shape", filter=stored)
    preset = FilterPreset.objects.get()

    payload = _list(auth_client).json()
    assert payload == [
        {
            "value": preset.id,
            "label": "Shape",
            "data": {"filter": json.dumps(stored), "sort": "", "per_page": ""},
        }
    ]


def test_list_empty_preset_serializes_empty_object(auth_client):
    _save(auth_client, name="Empty", filter=None)
    payload = _list(auth_client).json()
    assert payload[0]["data"]["filter"] == "{}"


def test_list_hostile_name_round_trips_raw(auth_client):
    # JSON is not an HTML context: the name goes over the wire untouched. The
    # render side is safe by construction (combobox labels use textContent only,
    # guarded by vitest) — this test just pins that nothing mangles the value.
    hostile = "<img src=x onerror=alert(1)>"
    _save(auth_client, name=hostile, filter=None)
    assert _list(auth_client).json()[0]["label"] == hostile


def test_list_rejects_unknown_mode(auth_client):
    assert _list(auth_client, mode="bogus").status_code == 400


def test_list_empty_is_empty_array(auth_client):
    assert _list(auth_client).json() == []


def test_list_only_returns_own(auth_client, second_auth_client):
    _make_preset(auth_client, name="MineAlone")
    _make_preset(second_auth_client, name="TheirOwn")
    labels = [option["label"] for option in _list(second_auth_client).json()]
    assert labels == ["TheirOwn"]


def test_list_is_mode_scoped(auth_client):
    _save(auth_client, name="GamesOnly", mode="games", filter=None)
    _save(auth_client, name="SessionsOnly", mode="sessions", filter=None)
    labels = [option["label"] for option in _list(auth_client, mode="sessions").json()]
    assert labels == ["SessionsOnly"]


def test_list_q_filters_by_name(auth_client):
    _save(auth_client, name="Backlog", filter=None)
    _save(auth_client, name="Finished", filter=None)
    labels = [option["label"] for option in _list(auth_client, q="back").json()]
    assert labels == ["Backlog"]


def test_list_limit_and_unbounded(auth_client):
    for index in range(3):
        _save(auth_client, name=f"P{index}", filter=None)
    assert len(_list(auth_client, limit=2).json()) == 2
    # limit=0 means unbounded: the collision check must see every name, or a
    # >limit collection lets a save silently destroy a preset (#212).
    assert len(_list(auth_client, limit=0).json()) == 3


# --- delete: ownership, method guard ------------------------------------------


def test_delete_requires_ownership(auth_client, second_auth_client):
    preset = _make_preset(auth_client)
    response = second_auth_client.delete(_delete_url(preset.id))
    assert response.status_code == 404
    assert FilterPreset.objects.filter(id=preset.id).exists()  # not deleted


def test_owner_can_delete(auth_client):
    preset = _make_preset(auth_client)
    response = auth_client.delete(_delete_url(preset.id))
    assert response.status_code == 204
    assert not FilterPreset.objects.filter(id=preset.id).exists()


@pytest.mark.parametrize("method", ["get", "post"])
def test_delete_url_rejects_non_delete_methods(auth_client, method):
    # DELETE-only: a GET (e.g. <img src=.../>) must not delete (CSRF-via-GET).
    preset = _make_preset(auth_client)
    response = getattr(auth_client, method)(_delete_url(preset.id))
    assert response.status_code == 405
    assert FilterPreset.objects.filter(id=preset.id).exists()


# --- #212: unique (user, mode, name) + overwrite (upsert) --------------------


def test_resaving_same_name_overwrites_in_place(auth_client):
    # Re-saving an existing (user, mode, name) overwrites the stored filter
    # rather than creating a duplicate row; 200 (vs 201) tells the client to
    # toast "updated".
    first = {"name": {"modifier": "INCLUDES", "value": "halo"}}
    second = {"name": {"modifier": "INCLUDES", "value": "doom"}}

    assert _save(auth_client, name="Backlog", filter=first).status_code == 201
    assert _save(auth_client, name="Backlog", filter=second).status_code == 200

    preset = FilterPreset.objects.get(name="Backlog")  # exactly one row
    assert preset.object_filter == second


def test_same_name_different_user_is_separate_row(auth_client, second_auth_client):
    _save(auth_client, name="Backlog", filter=None)
    _save(second_auth_client, name="Backlog", filter=None)
    assert FilterPreset.objects.filter(name="Backlog").count() == 2


def test_same_name_different_mode_is_separate_row(auth_client):
    _save(auth_client, name="Backlog", mode="games", filter=None)
    _save(auth_client, name="Backlog", mode="sessions", filter=None)
    assert FilterPreset.objects.filter(name="Backlog").count() == 2


def test_case_differing_names_are_distinct(auth_client):
    # The constraint uses SQLite's default (case-sensitive) collation, so these
    # are two presets — mirrored by the case-sensitive client-side warning.
    _save(auth_client, name="Backlog", filter=None)
    response = _save(auth_client, name="backlog", filter=None)
    assert response.status_code == 201
    assert FilterPreset.objects.filter(mode="games").count() == 2


def test_unique_constraint_enforced_at_db(user):
    FilterPreset.objects.create(user=user, name="Dup", mode="games")
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            FilterPreset.objects.create(user=user, name="Dup", mode="games")
