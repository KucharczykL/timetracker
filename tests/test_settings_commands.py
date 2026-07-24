"""Contract tests for the site-setting command boundary."""

import json
from dataclasses import dataclass
from typing import NamedTuple

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from timetracker import config as config_module
from timetracker import settings_resolver
from timetracker.config import RawConfigValue, ResolvedSetting, SettingSource
from timetracker.settings_commands import (
    SettingMutation,
    SettingOperation,
    change_site_setting,
)
from timetracker.settings_registry import (
    SETTINGS_REGISTRY,
    get_definition,
)


@dataclass(frozen=True, slots=True)
class SiteSettingCase:
    key: str
    valid_input: object
    canonical_value: object
    alternate_value: object
    invalid_input: object


class DevicePair(NamedTuple):
    primary_id: int
    alternate_id: int
    missing_id: int


DEVICE_PRIMARY = "<primary-device>"
DEVICE_ALTERNATE = "<alternate-device>"
DEVICE_MISSING = "<missing-device>"

SITE_SETTING_CASES = (
    SiteSettingCase("DEFAULT_CURRENCY", "eur", "EUR", "USD", "EURO"),
    SiteSettingCase(
        "DEFAULT_DEVICE",
        DEVICE_PRIMARY,
        DEVICE_PRIMARY,
        DEVICE_ALTERNATE,
        DEVICE_MISSING,
    ),
    SiteSettingCase(
        "DEFAULT_LANDING_PAGE",
        "games:list_games",
        "games:list_games",
        "games:list_sessions",
        "games:detail_game",
    ),
    SiteSettingCase("DEFAULT_PAGE_SIZE", "50", 50, 100, 20),
    SiteSettingCase("THEME", "dark", "dark", "light", "sepia"),
    SiteSettingCase(
        "DISPLAY_TIME_ZONE",
        "Pacific/Kiritimati",
        "Pacific/Kiritimati",
        "UTC",
        "Mars/Olympus",
    ),
    SiteSettingCase("DATE_FORMAT_LOCALE", "CS", "cs", "en-us", "de"),
    SiteSettingCase(
        "DATETIME_FORMAT",
        "dmy_24h",
        "dmy_24h",
        "mdy_12h",
        "rfc_3339",
    ),
)

SITE_SETTING_KEYS = tuple(case.key for case in SITE_SETTING_CASES)


@pytest.fixture
def clean_site_setting_sources(monkeypatch, tmp_path):
    for key in SITE_SETTING_KEYS:
        monkeypatch.delenv(key, raising=False)
        monkeypatch.delenv(f"{key}__FILE", raising=False)
    monkeypatch.setenv("ENV_FILE", str(tmp_path / "missing.env"))
    monkeypatch.setenv("INI_FILE", str(tmp_path / "missing.ini"))
    config_module.reset_caches()
    settings_resolver.clear_cache()
    yield


@pytest.fixture
def device_pair(db) -> DevicePair:
    from games.models import Device

    primary = Device.objects.create(name="Contract Deck", type=Device.HANDHELD)
    alternate = Device.objects.create(name="Contract PC", type=Device.PC)
    return DevicePair(primary.pk, alternate.pk, alternate.pk + 100_000)


@pytest.fixture
def superuser_client(db):
    user = get_user_model().objects.create_superuser(
        username="settings-command-admin",
        password="pw",
    )
    client = Client()
    client.force_login(user)
    return client


@pytest.fixture
def overlayless_user(db):
    return get_user_model().objects.create_user(
        username="settings-command-user",
        password="pw",
    )


def _site_patch_url(key: str) -> str:
    return reverse("api-1.0.0:update_site_setting", args=[key])


def _patch_site(client: Client, key: str, value: object):
    return client.patch(
        _site_patch_url(key),
        json.dumps({"value": value}),
        content_type="application/json",
    )


def _materialize(value: object, devices: DevicePair) -> object:
    if value == DEVICE_PRIMARY:
        return devices.primary_id
    if value == DEVICE_ALTERNATE:
        return devices.alternate_id
    if value == DEVICE_MISSING:
        return devices.missing_id
    return value


@pytest.mark.parametrize("case", SITE_SETTING_CASES, ids=lambda case: case.key)
def test_site_setting_backend_contract_matrix(
    case,
    device_pair,
    overlayless_user,
    superuser_client,
    clean_site_setting_sources,
    django_capture_on_commit_callbacks,
):
    from games.models import SiteSetting
    from timetracker.settings_registry import get_definition
    from timetracker.settings_resolver import (
        resolve_for_user_with_origin,
        resolve_with_origin,
        set_user_preference,
    )

    valid_input = _materialize(case.valid_input, device_pair)
    canonical_value = _materialize(case.canonical_value, device_pair)
    alternate_value = _materialize(case.alternate_value, device_pair)
    invalid_input = _materialize(case.invalid_input, device_pair)

    with django_capture_on_commit_callbacks(execute=True) as save_callbacks:
        saved_response = _patch_site(superuser_client, case.key, valid_input)

    assert len(save_callbacks) == 1
    assert saved_response.status_code == 200
    assert saved_response.json() == {
        "key": case.key,
        "value": canonical_value,
        "source": "database",
        "locked": False,
    }
    assert SiteSetting.objects.get(key=case.key).value == canonical_value
    assert resolve_with_origin(case.key) == ResolvedSetting(
        canonical_value,
        SettingSource.DATABASE,
        False,
    )

    inherited = resolve_for_user_with_origin(overlayless_user, case.key)
    assert inherited == ResolvedSetting(
        canonical_value,
        SettingSource.DATABASE,
        False,
    )

    with django_capture_on_commit_callbacks(execute=True):
        set_user_preference(overlayless_user, case.key, alternate_value)
    personal = resolve_for_user_with_origin(overlayless_user, case.key)
    assert personal == ResolvedSetting(alternate_value, SettingSource.USER, False)

    invalid_response = _patch_site(superuser_client, case.key, invalid_input)
    assert invalid_response.status_code == 400
    assert SiteSetting.objects.get(key=case.key).value == canonical_value

    fallback = get_definition(case.key).default_factory()
    with django_capture_on_commit_callbacks(execute=True) as clear_callbacks:
        cleared_response = _patch_site(superuser_client, case.key, None)

    assert len(clear_callbacks) == 1
    assert cleared_response.status_code == 200
    assert cleared_response.json() == {
        "key": case.key,
        "value": fallback,
        "source": "default",
        "locked": False,
    }
    assert not SiteSetting.objects.filter(key=case.key).exists()
    assert resolve_with_origin(case.key) == ResolvedSetting(
        fallback,
        SettingSource.DEFAULT,
        False,
    )


def _configure_locked_source(monkeypatch, tmp_path, source: SettingSource) -> None:
    monkeypatch.delenv("DEFAULT_CURRENCY", raising=False)
    monkeypatch.delenv("DEFAULT_CURRENCY__FILE", raising=False)
    monkeypatch.setenv("ENV_FILE", str(tmp_path / "missing.env"))
    monkeypatch.setenv("INI_FILE", str(tmp_path / "missing.ini"))
    if source is SettingSource.ENV_FILE:
        value_path = tmp_path / "currency.secret"
        value_path.write_text("USD\n")
        monkeypatch.setenv("DEFAULT_CURRENCY__FILE", str(value_path))
    elif source is SettingSource.ENV:
        monkeypatch.setenv("DEFAULT_CURRENCY", "USD")
    elif source is SettingSource.DOTENV:
        env_path = tmp_path / "settings.env"
        env_path.write_text("DEFAULT_CURRENCY=USD\n")
        monkeypatch.setenv("ENV_FILE", str(env_path))
    elif source is SettingSource.INI:
        ini_path = tmp_path / "settings.ini"
        ini_path.write_text("[timetracker]\nDEFAULT_CURRENCY = USD\n")
        monkeypatch.setenv("INI_FILE", str(ini_path))
    else:
        raise AssertionError(f"Unsupported locked source {source!r}.")
    config_module.reset_caches()
    settings_resolver.clear_cache()


@pytest.mark.parametrize(
    "source",
    (
        SettingSource.ENV_FILE,
        SettingSource.ENV,
        SettingSource.DOTENV,
        SettingSource.INI,
    ),
)
def test_locked_site_set_returns_409_without_mutation(
    source,
    superuser_client,
    monkeypatch,
    tmp_path,
):
    from games.models import SiteSetting
    from timetracker import settings_commands
    from timetracker.settings_commands import (
        SettingLockedError,
        change_site_setting,
    )

    SiteSetting.objects.create(key="DEFAULT_CURRENCY", value="EUR")
    if source is SettingSource.ENV_FILE:
        # No live site key currently opts into ``allow_file``. Exercise the
        # command's full locked-source contract through the resolver boundary.
        monkeypatch.setattr(
            settings_commands,
            "resolve_raw_with_source",
            lambda name, **kwargs: RawConfigValue("USD", SettingSource.ENV_FILE),
        )
    else:
        _configure_locked_source(monkeypatch, tmp_path, source)

    with pytest.raises(SettingLockedError) as raised:
        change_site_setting("DEFAULT_CURRENCY", "GBP")

    assert raised.value.key == "DEFAULT_CURRENCY"
    assert raised.value.source is source
    assert SiteSetting.objects.get(key="DEFAULT_CURRENCY").value == "EUR"

    response = _patch_site(superuser_client, "DEFAULT_CURRENCY", "GBP")
    assert response.status_code == 409
    assert SiteSetting.objects.get(key="DEFAULT_CURRENCY").value == "EUR"


@pytest.mark.parametrize(
    "source",
    (
        SettingSource.ENV_FILE,
        SettingSource.ENV,
        SettingSource.DOTENV,
        SettingSource.INI,
    ),
)
def test_locked_site_clear_succeeds_without_mutation_to_db(
    source,
    superuser_client,
    monkeypatch,
    tmp_path,
):
    from games.models import SiteSetting
    from timetracker.settings_commands import change_site_setting

    SiteSetting.objects.create(key="DEFAULT_CURRENCY", value="EUR")
    if source is not SettingSource.ENV_FILE:
        # ENV_FILE requires allow_file; no live site key opts in, so skip real
        # setup — CLEAR never lock-checks, so the source is irrelevant here.
        _configure_locked_source(monkeypatch, tmp_path, source)
    else:
        # Simulate ENV_FILE by setting the ENV source (functionally equivalent
        # for CLEAR: it never queries locked sources at all).
        monkeypatch.setenv("DEFAULT_CURRENCY", "USD")
        config_module.reset_caches()
        settings_resolver.clear_cache()

    # CLEAR must NOT raise even when a locked source is present.
    result = change_site_setting("DEFAULT_CURRENCY", None)
    assert result.changed is True
    assert not SiteSetting.objects.filter(key="DEFAULT_CURRENCY").exists()

    # Re-create the row so the endpoint's second call also clears something.
    SiteSetting.objects.create(key="DEFAULT_CURRENCY", value="EUR")
    response = _patch_site(superuser_client, "DEFAULT_CURRENCY", None)
    assert response.status_code == 200


@pytest.mark.parametrize(
    ("key", "value", "expected_exception"),
    (
        ("NOPE", "x", KeyError),
        ("TZ", "Europe/Prague", ValueError),
    ),
)
def test_unknown_and_infra_site_writes_return_400_without_mutation(
    key,
    value,
    expected_exception,
    superuser_client,
    clean_site_setting_sources,
):
    from games.models import SiteSetting
    from timetracker.settings_commands import change_site_setting

    SiteSetting.objects.create(key=key, value="unchanged")

    with pytest.raises(expected_exception):
        change_site_setting(key, value)
    assert SiteSetting.objects.get(key=key).value == "unchanged"

    response = _patch_site(superuser_client, key, value)
    assert response.status_code == 400
    assert SiteSetting.objects.get(key=key).value == "unchanged"


def test_rolled_back_command_returns_canonical_without_caching_uncommitted_data(
    db,
    clean_site_setting_sources,
):
    from django.db import transaction
    from games.models import SiteSetting
    from timetracker.settings_commands import change_site_setting
    from timetracker.settings_resolver import resolve_with_origin

    with transaction.atomic():
        result = change_site_setting("DEFAULT_CURRENCY", "eur")
        assert result.effective == ResolvedSetting("EUR", SettingSource.DATABASE, False)
        assert SiteSetting.objects.get(key="DEFAULT_CURRENCY").value == "EUR"
        transaction.set_rollback(True)

    assert not SiteSetting.objects.filter(key="DEFAULT_CURRENCY").exists()
    assert resolve_with_origin("DEFAULT_CURRENCY").source is SettingSource.DEFAULT


@pytest.mark.parametrize("operation", ("set", "clear"))
def test_site_save_and_clear_invalidate_resolver_only_on_commit(
    operation,
    db,
    clean_site_setting_sources,
    django_capture_on_commit_callbacks,
):
    from games.models import SiteSetting
    from timetracker.settings_commands import change_site_setting
    from timetracker.settings_registry import get_definition
    from timetracker.settings_resolver import resolve_with_origin

    if operation == "clear":
        with django_capture_on_commit_callbacks(execute=True):
            SiteSetting.objects.create(key="DEFAULT_CURRENCY", value="USD")
        before = ResolvedSetting("USD", SettingSource.DATABASE, False)
        requested_value = None
    else:
        before = ResolvedSetting(
            get_definition("DEFAULT_CURRENCY").default_factory(),
            SettingSource.DEFAULT,
            False,
        )
        requested_value = "EUR"

    assert resolve_with_origin("DEFAULT_CURRENCY") == before

    with django_capture_on_commit_callbacks(execute=True) as callbacks:
        change_site_setting("DEFAULT_CURRENCY", requested_value)
        assert resolve_with_origin("DEFAULT_CURRENCY") == before

    assert len(callbacks) == 1
    expected_source = (
        SettingSource.DEFAULT if operation == "clear" else SettingSource.DATABASE
    )
    assert resolve_with_origin("DEFAULT_CURRENCY").source is expected_source


def test_site_endpoint_returns_command_result_without_resolver_readback(
    superuser_client,
    monkeypatch,
):
    from games import api as api_module

    command_calls: list[tuple[str, object]] = []

    def fake_change_site_setting(key, value):
        command_calls.append((key, value))
        return SettingMutation(
            ResolvedSetting("EUR", SettingSource.DATABASE, False),
            SettingOperation.SET,
            True,
            "EUR",
            True,
        )

    def fail_resolver_read(*args, **kwargs):
        raise AssertionError("PATCH must return the command result directly.")

    monkeypatch.setattr(api_module, "change_site_setting", fake_change_site_setting)
    monkeypatch.setattr(api_module, "resolve_with_origin", fail_resolver_read)

    response = _patch_site(superuser_client, "DEFAULT_CURRENCY", "eur")

    assert response.status_code == 200
    assert response.json() == {
        "key": "DEFAULT_CURRENCY",
        "value": "EUR",
        "source": "database",
        "locked": False,
    }
    assert command_calls == [("DEFAULT_CURRENCY", "eur")]


def test_settings_resolver_has_no_public_site_mutation_helpers():
    assert not hasattr(settings_resolver, "set_site_setting")
    assert not hasattr(settings_resolver, "clear_site_setting")
    assert "set_site_setting" not in settings_resolver.__all__
    assert "clear_site_setting" not in settings_resolver.__all__


@pytest.mark.django_db
def test_default_device_write_validator_rejects_missing_device():
    from django.core.exceptions import ValidationError

    validator = get_definition("DEFAULT_DEVICE").write_validator
    assert validator is not None
    with pytest.raises(ValidationError):
        validator(9_999_999)  # no such device


def test_only_default_device_declares_a_write_validator():
    with_validator = [
        key
        for key, definition in SETTINGS_REGISTRY.items()
        if definition.write_validator is not None
    ]
    assert with_validator == ["DEFAULT_DEVICE"]


@pytest.mark.django_db
def test_fallthrough_uncached_skip_db_uses_env_normalized(settings, monkeypatch):
    from timetracker.settings_resolver import resolve_fallthrough_uncached

    # env shadows DEFAULT_PAGE_SIZE with a string; must come back as a normalized int.
    monkeypatch.setenv("DEFAULT_PAGE_SIZE", "100")
    config_module._env_file_cache = None  # env is read live; no file cache interference
    resolved = resolve_fallthrough_uncached("DEFAULT_PAGE_SIZE", skip_db=True)
    assert resolved.value == 100
    assert resolved.source == SettingSource.ENV
    assert resolved.locked is True


@pytest.mark.django_db
def test_fallthrough_uncached_degrades_malformed_locked_env_to_default(monkeypatch):
    from timetracker.settings_resolver import resolve_fallthrough_uncached
    from timetracker.settings_registry import get_definition

    monkeypatch.setenv("DEFAULT_PAGE_SIZE", "not-a-number")
    resolved = resolve_fallthrough_uncached("DEFAULT_PAGE_SIZE", skip_db=True)
    assert resolved.value == get_definition("DEFAULT_PAGE_SIZE").default_factory()
    assert resolved.source == SettingSource.DEFAULT
    assert resolved.locked is False


@pytest.mark.django_db
def test_site_set_then_noop_set_distinguishable():
    first = change_site_setting("DEFAULT_CURRENCY", "eur")
    assert first.operation is SettingOperation.SET
    assert first.changed is True
    assert first.effective == ResolvedSetting("EUR", SettingSource.DATABASE, False)

    second = change_site_setting("DEFAULT_CURRENCY", "EUR")
    assert second.operation is SettingOperation.SET
    assert second.changed is False  # already stored
    assert second.stored_present is True


@pytest.mark.django_db
def test_site_clear_then_noop_clear_distinguishable():
    change_site_setting("DEFAULT_CURRENCY", "eur")
    cleared = change_site_setting("DEFAULT_CURRENCY", None)
    assert cleared.operation is SettingOperation.CLEAR
    assert cleared.changed is True
    assert cleared.stored_present is False

    noop = change_site_setting("DEFAULT_CURRENCY", None)
    assert noop.changed is False


@pytest.mark.django_db
def test_site_clear_allowed_under_env_lock_and_reports_env_effective(monkeypatch):
    from games.models import SiteSetting

    SiteSetting.objects.create(key="DEFAULT_PAGE_SIZE", value=50)
    monkeypatch.setenv("DEFAULT_PAGE_SIZE", "100")  # ENV is a locked source
    settings_resolver.clear_cache()

    result = change_site_setting("DEFAULT_PAGE_SIZE", None)  # must NOT raise
    assert result.changed is True
    assert not SiteSetting.objects.filter(key="DEFAULT_PAGE_SIZE").exists()
    assert result.effective.value == 100  # normalized int, from env
    assert result.effective.source == SettingSource.ENV
    assert result.effective.locked is True


@pytest.mark.django_db
def test_site_set_under_env_lock_still_raises(monkeypatch):
    from timetracker.settings_commands import SettingLockedError

    monkeypatch.setenv("DEFAULT_PAGE_SIZE", "100")
    settings_resolver.clear_cache()
    with pytest.raises(SettingLockedError):
        change_site_setting("DEFAULT_PAGE_SIZE", 50)


@pytest.mark.django_db
def test_site_clear_repairs_poisoned_row(monkeypatch):
    from games.models import SiteSetting

    SiteSetting.objects.create(key="DEFAULT_PAGE_SIZE", value="garbage")
    result = change_site_setting("DEFAULT_PAGE_SIZE", None)  # must NOT raise
    assert result.changed is True
    assert not SiteSetting.objects.filter(key="DEFAULT_PAGE_SIZE").exists()


@pytest.mark.django_db
def test_site_noop_fires_no_cache_invalidation(monkeypatch):
    from django.db import transaction

    change_site_setting("DEFAULT_CURRENCY", "eur")
    calls: list[int] = []
    monkeypatch.setattr(settings_resolver, "clear_cache", lambda: calls.append(1))
    with transaction.atomic():
        change_site_setting("DEFAULT_CURRENCY", "EUR")  # no-op
    assert calls == []  # no post_save -> no on_commit clear
