"""Tests for the /api/settings endpoints (games/api.py, Stage 2).

- user GET/PATCH is scoped to request.user (no cross-user access, no id param);
- site GET/PATCH is superuser-gated (403 for a normal user, 401 for anonymous);
- values are validated server-side; a bad value writes nothing;
- value:null clears a pref back to unset.

Fixtures are duplicated here (they are module-local in test_filter_presets.py,
not in conftest) matching the repo's per-file style.
"""

import json

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse


@pytest.fixture
def no_currency_env(monkeypatch):
    monkeypatch.delenv("DEFAULT_CURRENCY", raising=False)
    monkeypatch.delenv("DEFAULT_CURRENCY__FILE", raising=False)
    yield


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


@pytest.fixture
def superuser(db):
    return get_user_model().objects.create_superuser(username="boss", password="pw")


@pytest.fixture
def superuser_client(superuser):
    client = Client()
    client.force_login(superuser)
    return client


def _user_url() -> str:
    return reverse("api-1.0.0:list_user_settings")


def _user_patch_url(key: str) -> str:
    return reverse("api-1.0.0:update_user_setting", args=[key])


def _site_url() -> str:
    return reverse("api-1.0.0:list_site_settings")


def _site_patch_url(key: str) -> str:
    return reverse("api-1.0.0:update_site_setting", args=[key])


def _patch(client, url, value):
    return client.patch(
        url, json.dumps({"value": value}), content_type="application/json"
    )


def _currency(payload_list) -> dict:
    return next(row for row in payload_list if row["key"] == "DEFAULT_CURRENCY")


# --- auth -----------------------------------------------------------------


def test_anonymous_is_rejected(db):
    anonymous = Client()
    assert anonymous.get(_user_url()).status_code == 401
    assert anonymous.get(_site_url()).status_code == 401
    assert _patch(
        anonymous, _user_patch_url("DEFAULT_CURRENCY"), "EUR"
    ).status_code == (401)


def test_site_endpoints_forbidden_for_non_superuser(auth_client):
    assert auth_client.get(_site_url()).status_code == 403
    assert _patch(
        auth_client, _site_patch_url("DEFAULT_CURRENCY"), "EUR"
    ).status_code == (403)


def test_site_endpoints_allowed_for_superuser(superuser_client):
    assert superuser_client.get(_site_url()).status_code == 200


# --- user scoping ---------------------------------------------------------


def test_user_patch_and_get_round_trip(auth_client, no_currency_env):
    assert _patch(
        auth_client, _user_patch_url("DEFAULT_CURRENCY"), "EUR"
    ).status_code == (204)
    body = auth_client.get(_user_url()).json()
    currency = _currency(body)
    assert currency["value"] == "EUR"
    assert currency["source"] == "user"


def test_user_patch_emits_saved_success_toast(auth_client, no_currency_env):
    response = _patch(auth_client, _user_patch_url("DEFAULT_CURRENCY"), "EUR")
    trigger = json.loads(response.headers["HX-Trigger"])
    assert trigger["show-toast"] == {
        "message": "Default currency saved",
        "type": "success",
    }


def test_user_settings_are_scoped_per_user(
    auth_client, second_auth_client, no_currency_env
):
    _patch(auth_client, _user_patch_url("DEFAULT_CURRENCY"), "EUR")
    # The second user sees no personal override, so not EUR.
    other_currency = _currency(second_auth_client.get(_user_url()).json())
    assert other_currency["value"] != "EUR"
    assert other_currency["source"] != "user"
    # And the second user's write does not touch the first user's value.
    _patch(second_auth_client, _user_patch_url("DEFAULT_CURRENCY"), "GBP")
    first_currency = _currency(auth_client.get(_user_url()).json())
    assert first_currency["value"] == "EUR"


def test_user_null_clears_back_to_fallback(auth_client, no_currency_env):
    from games.models import UserPreferences

    _patch(auth_client, _user_patch_url("DEFAULT_CURRENCY"), "EUR")
    assert _patch(
        auth_client, _user_patch_url("DEFAULT_CURRENCY"), None
    ).status_code == (204)
    preferences = UserPreferences.objects.get(user__username="tester")
    assert preferences.default_currency is None
    currency = _currency(auth_client.get(_user_url()).json())
    assert currency["source"] != "user"


# --- validation -----------------------------------------------------------


def test_user_patch_rejects_bad_currency_and_writes_nothing(auth_client):
    from games.models import UserPreferences

    assert (
        _patch(auth_client, _user_patch_url("DEFAULT_CURRENCY"), "EURO").status_code
        == 400
    )
    assert not UserPreferences.objects.filter(user__username="tester").exists()


def test_user_patch_rejects_unknown_key(auth_client):
    assert _patch(auth_client, _user_patch_url("NOPE"), "x").status_code == 400


def test_user_patch_rejects_non_user_key(auth_client):
    # TZ is infra-scoped, not a personal pref.
    assert _patch(auth_client, _user_patch_url("TZ"), "Europe/Prague").status_code == (
        400
    )


def test_user_patch_rejects_missing_device(auth_client):
    assert _patch(auth_client, _user_patch_url("DEFAULT_DEVICE"), 9999).status_code == (
        400
    )


def test_user_patch_rejects_unsupported_landing_page_and_writes_nothing(auth_client):
    from games.models import UserPreferences

    response = _patch(
        auth_client,
        _user_patch_url("DEFAULT_LANDING_PAGE"),
        "games:stats_alltime",
    )

    assert response.status_code == 400
    assert not UserPreferences.objects.filter(user__username="tester").exists()


def test_site_patch_rejects_infra_key(superuser_client):
    assert _patch(
        superuser_client, _site_patch_url("TZ"), "Europe/Prague"
    ).status_code == (400)


# --- device pref: int serialization + clear ------------------------------


def test_user_device_round_trips_as_int(auth_client, db):
    from games.models import Device

    device = Device.objects.create(name="Deck", type=Device.HANDHELD)
    assert (
        _patch(auth_client, _user_patch_url("DEFAULT_DEVICE"), device.pk).status_code
        == 204
    )
    row = next(
        r for r in auth_client.get(_user_url()).json() if r["key"] == "DEFAULT_DEVICE"
    )
    # The SettingOut value field must carry the int id (a str-only field would 500).
    assert row["value"] == device.pk
    assert row["source"] == "user"


def test_user_device_null_clears(auth_client, db):
    from games.models import Device, UserPreferences

    device = Device.objects.create(name="Deck", type=Device.HANDHELD)
    _patch(auth_client, _user_patch_url("DEFAULT_DEVICE"), device.pk)
    assert (
        _patch(auth_client, _user_patch_url("DEFAULT_DEVICE"), None).status_code == 204
    )
    preferences = UserPreferences.objects.get(user__username="tester")
    assert preferences.default_device_id is None


# --- locked is always False on the user endpoint --------------------------


def test_user_endpoint_reports_unlocked_even_when_env_pins(
    auth_client, monkeypatch, django_capture_on_commit_callbacks
):
    # An env-pinned USER key with no personal override still reports locked=False
    # on /user, because the user can always PATCH a personal override.
    monkeypatch.setenv("DEFAULT_CURRENCY", "USD")
    from timetracker import config as config_module
    from timetracker import settings_resolver

    config_module.reset_caches()
    settings_resolver.clear_cache()
    currency = _currency(auth_client.get(_user_url()).json())
    assert currency["locked"] is False


# --- error message shape --------------------------------------------------


def test_bad_currency_400_message_is_clean(auth_client):
    # The client must not see a Python list-repr like ['Currency must be ...'].
    response = _patch(auth_client, _user_patch_url("DEFAULT_CURRENCY"), "EURO")
    assert response.status_code == 400
    assert "[" not in response.json()["detail"]


# --- site round-trip becomes the fallback under user prefs ----------------


def test_site_patch_sets_fallback_for_overlayless_user(
    superuser_client, auth_client, no_currency_env, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        assert (
            _patch(
                superuser_client, _site_patch_url("DEFAULT_CURRENCY"), "USD"
            ).status_code
            == 204
        )
    currency = _currency(auth_client.get(_user_url()).json())
    assert currency["value"] == "USD"
    assert currency["source"] == "database"
