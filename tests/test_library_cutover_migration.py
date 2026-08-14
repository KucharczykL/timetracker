import json
import re
from collections import Counter
from copy import deepcopy
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from django.core.management import call_command
from django.db import connection, models
from django.db.migrations.executor import MigrationExecutor

pytestmark = pytest.mark.django_db(transaction=True)

BEFORE_CUTOVER = ("games", "0003_userlibrary")
WITH_CUTOVER = ("games", "0004_user_library_ownership_cutover")
MANIFEST_ENV = "TIMETRACKER_OWN_CUTOVER_MANIFEST"
FIRST_COMMIT_AT = datetime.fromisoformat("2022-12-31T14:18:27+01:00")
BUILT_IN_PLATFORMS = {
    ("Steam", "PC"),
    ("Xbox Gamepass", "PC"),
    ("Epic Games Store", "PC"),
    ("Playstation 5", "Playstation"),
    ("Playstation 4", "Playstation"),
    ("Nintendo Switch", "Nintendo"),
    ("Nintendo 3DS", "Nintendo"),
}
ROW_COUNT_MODELS = {
    "users": ("auth", "User"),
    "sessions": ("games", "Session"),
    "games": ("games", "Game"),
    "devices": ("games", "Device"),
    "platforms": ("games", "Platform"),
    "purchases": ("games", "Purchase"),
    "play_events": ("games", "PlayEvent"),
    "status_changes": ("games", "GameStatusChange"),
    "filter_presets": ("games", "FilterPreset"),
}


class CutoverHarness:
    def __init__(self, apps, monkeypatch):
        self.apps = apps
        self.monkeypatch = monkeypatch

    def install_manifest(self, tmp_path: Path, manifest: dict) -> Path:
        path = tmp_path / "own-02-manifest.json"
        path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        self.monkeypatch.setenv(MANIFEST_ENV, str(path.resolve()))
        return path

    def migrate(self):
        executor = MigrationExecutor(connection)
        if WITH_CUTOVER not in executor.loader.graph.nodes:
            pytest.fail("missing migration games.0004_user_library_ownership_cutover")
        executor.migrate([WITH_CUTOVER])
        return executor.loader.project_state([WITH_CUTOVER]).apps

    def assert_refused(self, message: str) -> None:
        with pytest.raises(RuntimeError, match=re.escape(message)):
            self.migrate()
        UserLibrary = self.apps.get_model("games", "UserLibrary")
        assert UserLibrary.objects.count() == 0


@pytest.fixture
def cutover_harness(monkeypatch, settings, tmp_path):
    monkeypatch.delenv(MANIFEST_ENV, raising=False)
    monkeypatch.delenv("DEFAULT_CURRENCY", raising=False)
    monkeypatch.delenv("DEFAULT_DEVICE", raising=False)
    monkeypatch.setenv("ENV_FILE", str(tmp_path / "missing.env"))
    monkeypatch.setenv("INI_FILE", str(tmp_path / "missing.ini"))
    settings.DEFAULT_CURRENCY = "CZK"
    executor = MigrationExecutor(connection)
    executor.migrate([BEFORE_CUTOVER])
    call_command("flush", interactive=False, verbosity=0)
    old_apps = executor.loader.project_state([BEFORE_CUTOVER]).apps
    yield CutoverHarness(old_apps, monkeypatch)

    monkeypatch.delenv(MANIFEST_ENV, raising=False)
    call_command("flush", interactive=False, verbosity=0)
    executor = MigrationExecutor(connection)
    executor.migrate([BEFORE_CUTOVER])
    executor = MigrationExecutor(connection)
    leaf = (
        WITH_CUTOVER if WITH_CUTOVER in executor.loader.graph.nodes else BEFORE_CUTOVER
    )
    executor.migrate([leaf])


def create_legacy_state(apps) -> dict[str, int]:
    User = apps.get_model("auth", "User")
    Platform = apps.get_model("games", "Platform")
    Device = apps.get_model("games", "Device")
    Game = apps.get_model("games", "Game")
    Purchase = apps.get_model("games", "Purchase")
    Session = apps.get_model("games", "Session")
    PlayEvent = apps.get_model("games", "PlayEvent")
    GameStatusChange = apps.get_model("games", "GameStatusChange")
    FilterPreset = apps.get_model("games", "FilterPreset")
    UserPreferences = apps.get_model("games", "UserPreferences")

    user = User.objects.create(id=41, username="manifest-owner")
    platforms = {
        (name, group): Platform.objects.create(name=name, group=group, icon="fixture")
        for name, group in sorted(BUILT_IN_PLATFORMS)
    }
    custom = Platform.objects.create(
        id=29,
        name="Hand-built launcher",
        group="Custom",
        icon="custom",
    )
    device = Device.objects.create(id=17, name="Manifest Deck", type="Handheld")
    game = Game.objects.create(
        id=23,
        name="Manifest Game",
        year_released=2024,
        platform=platforms[("Steam", "PC")],
    )
    purchase = Purchase.objects.create(
        id=31,
        date_purchased=date(2025, 1, 2),
        price=42,
        price_currency="EUR",
        converted_price=1050,
        converted_currency="CZK",
        needs_price_update=False,
        num_purchases=1,
        platform=custom,
    )
    purchase.games.add(game)
    Session.objects.create(
        game=game,
        device=device,
        timestamp_start=datetime(2025, 1, 3, 10, tzinfo=UTC),
    )
    Session.objects.create(
        game=game,
        device=None,
        timestamp_start=datetime(2025, 1, 4, 10, tzinfo=UTC),
    )
    PlayEvent.objects.create(
        game=game,
        started=date(2025, 1, 3),
        ended=date(2025, 1, 4),
    )
    GameStatusChange.objects.create(
        game=game,
        old_status="u",
        new_status="p",
        timestamp=datetime(2025, 1, 4, 11, tzinfo=UTC),
    )
    FilterPreset.objects.create(
        user=user,
        name="Manifest preset",
        mode="sessions",
        object_filter={"game": {"modifier": "INCLUDES", "value": [str(game.pk)]}},
    )
    UserPreferences.objects.create(
        user=user,
        default_currency="EUR",
        default_device=device,
        theme="dark",
    )
    return {
        "user_id": user.pk,
        "device_id": device.pk,
        "game_id": game.pk,
        "purchase_id": purchase.pk,
    }


def row_counts(apps) -> dict[str, int]:
    counts = {
        key: apps.get_model(*model).objects.count()
        for key, model in ROW_COUNT_MODELS.items()
    }
    Purchase = apps.get_model("games", "Purchase")
    counts["purchase_games"] = Purchase.games.through.objects.count()
    return counts


def raw_setting_row(apps, key: str) -> dict:
    SiteSetting = apps.get_model("games", "SiteSetting")
    values = list(SiteSetting.objects.filter(key=key).values_list("value", flat=True))
    return {"present": bool(values), "value": values[0] if values else None}


def build_manifest(apps) -> dict:
    User = apps.get_model("auth", "User")
    Session = apps.get_model("games", "Session")
    Purchase = apps.get_model("games", "Purchase")
    UserPreferences = apps.get_model("games", "UserPreferences")
    SiteSetting = apps.get_model("games", "SiteSetting")
    Device = apps.get_model("games", "Device")

    user = User.objects.get()
    preferences = UserPreferences.objects.get(user_id=user.pk)
    default_device = Device.objects.get(pk=preferences.default_device_id)
    purchases = list(
        Purchase.objects.order_by("pk").values(
            "price_currency",
            "converted_price",
            "converted_currency",
            "needs_price_update",
        )
    )
    original_counts = dict(
        sorted(Counter(row["price_currency"] for row in purchases).items())
    )
    converted_currency = next(
        (row["converted_currency"] for row in purchases if row["converted_currency"]),
        "CZK",
    )
    mixed_count = sum(
        (row["converted_price"] is None) != (row["converted_currency"] == "")
        for row in purchases
    )
    return {
        "schema_version": 1,
        "source": {
            "deployment_version": "main-a1b2c3d",
            "git_commit_short": "a1b2c3d",
            "database_name": "timetracker_test",
            "postgres_version": "18.4",
            "dump_filename": "timetracker-pre-630.dump",
            "dump_sha256": "a" * 64,
        },
        "expected_legacy_state": {
            "user_id": user.pk,
            "username": user.username,
            "row_counts": row_counts(apps),
            "null_session_game_count": Session.objects.filter(game_id=None).count(),
            "null_session_device_count": Session.objects.filter(device_id=None).count(),
        },
        "observed_setting_state": {
            "user_preferences_row_count": UserPreferences.objects.count(),
            "site_setting_row_count": SiteSetting.objects.count(),
            "old_site_currency_row": raw_setting_row(apps, "DEFAULT_CURRENCY"),
            "old_site_default_device_row": raw_setting_row(apps, "DEFAULT_DEVICE"),
            "old_personal_currency_value": preferences.default_currency,
            "old_personal_default_device_id": preferences.default_device_id,
        },
        "operator_confirmed_settings": {
            "old_site_currency": {
                "value": "CZK",
                "source": "default",
                "locked": False,
            },
            "old_personal_currency": {
                "value": preferences.default_currency,
                "source": "user",
                "locked": False,
            },
            "effective_purchase_currency": preferences.default_currency,
            "effective_display_currency": "CZK",
            "effective_default_device_id": default_device.pk,
            "effective_default_device_name": default_device.name,
            "effective_default_device_source": "user",
        },
        "observed_purchase_state": {
            "purchase_count": len(purchases),
            "original_currency_counts": original_counts,
            "converted_cache_currency": converted_currency,
            "converted_cache_count": sum(
                row["converted_currency"] == converted_currency for row in purchases
            ),
            "null_converted_price_count": sum(
                row["converted_price"] is None for row in purchases
            ),
            "blank_converted_currency_count": sum(
                row["converted_currency"] == "" for row in purchases
            ),
            "needs_price_update_count": sum(
                row["needs_price_update"] for row in purchases
            ),
            "mixed_cache_nullability_count": mixed_count,
        },
    }


def set_path(value: dict, path: str, replacement) -> None:
    parts = path.split(".")
    target = value
    for part in parts[:-1]:
        target = target[part]
    target[parts[-1]] = replacement


def delete_path(value: dict, path: str) -> None:
    parts = path.split(".")
    target = value
    for part in parts[:-1]:
        target = target[part]
    del target[parts[-1]]


def test_known_legacy_shape_backfills_exactly_one_manifest_selected_library(
    cutover_harness, tmp_path, capsys
):
    ids = create_legacy_state(cutover_harness.apps)
    manifest = build_manifest(cutover_harness.apps)
    cutover_harness.install_manifest(tmp_path, manifest)

    new_apps = cutover_harness.migrate()

    UserLibrary = new_apps.get_model("games", "UserLibrary")
    library = UserLibrary.objects.get()
    assert (
        library.user_id
        == ids["user_id"]
        == manifest["expected_legacy_state"]["user_id"]
    )
    assert library.created_at == FIRST_COMMIT_AT
    assert UserLibrary.objects.count() == 1
    Game = new_apps.get_model("games", "Game")
    Platform = new_apps.get_model("games", "Platform")
    Purchase = new_apps.get_model("games", "Purchase")
    Device = new_apps.get_model("games", "Device")
    FilterPreset = new_apps.get_model("games", "FilterPreset")
    preferences = new_apps.get_model("games", "UserLibraryPreferences").objects.get()
    state = new_apps.get_model("games", "PurchaseConversionState").objects.get()
    assert {
        Game.objects.get().library_id,
        Purchase.objects.get().library_id,
        Device.objects.get().library_id,
        FilterPreset.objects.get().library_id,
    } == {library.pk}
    assert Platform.objects.filter(library_id=None).count() == len(BUILT_IN_PLATFORMS)
    assert Platform.objects.get(name="Hand-built launcher").library_id == library.pk
    assert (
        preferences.library_id == library.pk
        and preferences.default_device_id == ids["device_id"]
    )
    assert (
        state.requested_version,
        state.requested_currency,
        state.published_version,
        state.published_currency,
        state.status,
        state.retry_at,
        state.last_error,
    ) == (1, "CZK", 1, "CZK", "complete", None, "")
    output = capsys.readouterr().out
    assert manifest["source"]["deployment_version"] in output
    assert manifest["source"]["dump_sha256"] in output
    assert str(library.pk) in output


def test_pristine_install_needs_no_manifest_and_creates_no_library(cutover_harness):
    new_apps = cutover_harness.migrate()
    assert new_apps.get_model("auth", "User").objects.count() == 0
    assert new_apps.get_model("games", "UserLibrary").objects.count() == 0


def orphan_game(apps):
    apps.get_model("games", "Game").objects.create(name="orphan")


def orphan_device(apps):
    apps.get_model("games", "Device").objects.create(name="orphan")


def orphan_platform(apps):
    apps.get_model("games", "Platform").objects.create(name="orphan")


def orphan_purchase(apps):
    apps.get_model("games", "Purchase").objects.create(date_purchased=date(2025, 1, 1))


def orphan_session(apps):
    apps.get_model("games", "Session").objects.create(
        timestamp_start=datetime(2025, 1, 1, tzinfo=UTC)
    )


def orphan_play_event(apps):
    game = apps.get_model("games", "Game").objects.create(name="parent")
    apps.get_model("games", "PlayEvent").objects.create(game=game)


def orphan_status_change(apps):
    game = apps.get_model("games", "Game").objects.create(name="parent")
    apps.get_model("games", "GameStatusChange").objects.create(
        game=game, new_status="p"
    )


def orphan_purchase_game(apps):
    game = apps.get_model("games", "Game").objects.create(name="parent")
    purchase = apps.get_model("games", "Purchase").objects.create(
        date_purchased=date(2025, 1, 1)
    )
    purchase.games.add(game)


def orphan_site_setting(apps):
    apps.get_model("games", "SiteSetting").objects.create(
        key="DEFAULT_CURRENCY", value="EUR"
    )


@pytest.mark.parametrize(
    ("seed", "reported_model"),
    [
        (orphan_game, "Game"),
        (orphan_device, "Device"),
        (orphan_platform, "Platform"),
        (orphan_purchase, "Purchase"),
        (orphan_session, "Session"),
        (orphan_play_event, "PlayEvent"),
        (orphan_status_change, "GameStatusChange"),
        (orphan_purchase_game, "Purchase.games"),
        (orphan_site_setting, "SiteSetting"),
    ],
)
def test_zero_user_install_rejects_orphaned_legacy_state(
    cutover_harness, seed, reported_model
):
    seed(cutover_harness.apps)
    cutover_harness.assert_refused(
        f"OWN cutover found orphaned legacy state: {reported_model}"
    )


def test_two_users_are_refused_before_manifest_loading(cutover_harness):
    User = cutover_harness.apps.get_model("auth", "User")
    User.objects.create(username="one")
    User.objects.create(username="two")
    cutover_harness.assert_refused("OWN cutover requires zero or exactly one User")


@pytest.mark.parametrize("modifier", ["IS_NULL", "NOT_NULL"])
def test_saved_session_game_null_predicates_are_refused(
    cutover_harness, tmp_path, modifier
):
    create_legacy_state(cutover_harness.apps)
    FilterPreset = cutover_harness.apps.get_model("games", "FilterPreset")
    FilterPreset.objects.update(
        object_filter={
            "OR": [{"game": {"modifier": modifier, "value": []}}],
        }
    )
    cutover_harness.install_manifest(tmp_path, build_manifest(cutover_harness.apps))
    cutover_harness.assert_refused(
        "OWN cutover saved Session filter depends on nullable game"
    )


@pytest.mark.parametrize(
    ("mutate_database", "message"),
    [
        (
            lambda apps: apps.get_model("games", "Session").objects.create(
                timestamp_start=datetime(2025, 2, 1, tzinfo=UTC)
            ),
            "OWN cutover requires every Session to have a Game",
        ),
        (
            lambda apps: apps.get_model("games", "Platform").objects.create(
                name="Steam", group="PC", icon="duplicate"
            ),
            "OWN cutover built-in Platform classification is ambiguous: Steam|PC",
        ),
        (
            lambda apps: apps.get_model("games", "Purchase").objects.update(
                needs_price_update=True
            ),
            "OWN cutover Purchase converted cache is incomplete",
        ),
        (
            lambda apps: apps.get_model("games", "Purchase").objects.update(
                converted_price=None
            ),
            "OWN cutover Purchase converted cache has mixed nullability",
        ),
    ],
)
def test_invalid_legacy_shapes_are_refused_before_backfill(
    cutover_harness, tmp_path, mutate_database, message
):
    create_legacy_state(cutover_harness.apps)
    mutate_database(cutover_harness.apps)
    cutover_harness.install_manifest(tmp_path, build_manifest(cutover_harness.apps))
    cutover_harness.assert_refused(message)


def test_one_user_requires_manifest_path(cutover_harness):
    create_legacy_state(cutover_harness.apps)
    cutover_harness.assert_refused(
        "OWN cutover requires TIMETRACKER_OWN_CUTOVER_MANIFEST"
    )


def test_manifest_path_must_be_absolute(cutover_harness):
    create_legacy_state(cutover_harness.apps)
    cutover_harness.monkeypatch.setenv(MANIFEST_ENV, "relative.json")
    cutover_harness.assert_refused("OWN cutover manifest path must be absolute")


def test_missing_manifest_file_is_refused(cutover_harness, tmp_path):
    create_legacy_state(cutover_harness.apps)
    missing = (tmp_path / "missing.json").resolve()
    cutover_harness.monkeypatch.setenv(MANIFEST_ENV, str(missing))
    cutover_harness.assert_refused("OWN cutover manifest is unreadable")


def test_invalid_manifest_json_is_refused(cutover_harness, tmp_path):
    create_legacy_state(cutover_harness.apps)
    path = tmp_path / "invalid.json"
    path.write_text("{not json", encoding="utf-8")
    cutover_harness.monkeypatch.setenv(MANIFEST_ENV, str(path.resolve()))
    cutover_harness.assert_refused("OWN cutover manifest is not valid JSON")


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda value: set_path(value, "schema_version", 2), "manifest.schema_version"),
        (
            lambda value: delete_path(value, "source.dump_sha256"),
            "manifest.source.dump_sha256",
        ),
        (
            lambda value: set_path(value, "expected_legacy_state.user_id", True),
            "manifest.expected_legacy_state.user_id",
        ),
        (
            lambda value: value.update({"unexpected": {}}),
            "manifest has unexpected fields",
        ),
        (
            lambda value: set_path(value, "source.dump_sha256", "NOT-A-HASH"),
            "manifest.source.dump_sha256",
        ),
    ],
)
def test_manifest_schema_is_strict(cutover_harness, tmp_path, mutation, message):
    create_legacy_state(cutover_harness.apps)
    manifest = build_manifest(cutover_harness.apps)
    mutation(manifest)
    cutover_harness.install_manifest(tmp_path, manifest)
    cutover_harness.assert_refused(f"OWN cutover {message}")


@pytest.mark.parametrize(
    ("path", "replacement"),
    [
        ("expected_legacy_state.user_id", 42),
        ("expected_legacy_state.username", "somebody-else"),
    ],
)
def test_manifest_user_identity_drift_is_refused(
    cutover_harness, tmp_path, path, replacement
):
    create_legacy_state(cutover_harness.apps)
    manifest = build_manifest(cutover_harness.apps)
    set_path(manifest, path, replacement)
    cutover_harness.install_manifest(tmp_path, manifest)
    cutover_harness.assert_refused(f"OWN cutover {path} mismatch")


@pytest.mark.parametrize("count_key", [*ROW_COUNT_MODELS, "purchase_games"])
def test_every_manifest_row_count_drift_is_refused(
    cutover_harness, tmp_path, count_key
):
    create_legacy_state(cutover_harness.apps)
    manifest = build_manifest(cutover_harness.apps)
    path = f"expected_legacy_state.row_counts.{count_key}"
    set_path(
        manifest, path, manifest["expected_legacy_state"]["row_counts"][count_key] + 1
    )
    cutover_harness.install_manifest(tmp_path, manifest)
    cutover_harness.assert_refused(f"OWN cutover {path} mismatch")


SETTING_DRIFT_CASES = [
    ("observed_setting_state.user_preferences_row_count", 2),
    ("observed_setting_state.site_setting_row_count", 1),
    ("observed_setting_state.old_site_currency_row.present", True),
    ("observed_setting_state.old_site_currency_row.value", "EUR"),
    ("observed_setting_state.old_site_default_device_row.present", True),
    ("observed_setting_state.old_site_default_device_row.value", 999),
    ("observed_setting_state.old_personal_currency_value", "USD"),
    ("observed_setting_state.old_personal_default_device_id", 999),
    ("operator_confirmed_settings.old_site_currency.value", "USD"),
    ("operator_confirmed_settings.old_site_currency.source", "database"),
    ("operator_confirmed_settings.old_site_currency.locked", True),
    ("operator_confirmed_settings.old_personal_currency.value", "USD"),
    ("operator_confirmed_settings.old_personal_currency.source", "default"),
    ("operator_confirmed_settings.old_personal_currency.locked", True),
    ("operator_confirmed_settings.effective_purchase_currency", "USD"),
    ("operator_confirmed_settings.effective_display_currency", "USD"),
    ("operator_confirmed_settings.effective_default_device_id", 999),
    ("operator_confirmed_settings.effective_default_device_name", "Wrong device"),
    ("operator_confirmed_settings.effective_default_device_source", "default"),
]


@pytest.mark.parametrize(("path", "replacement"), SETTING_DRIFT_CASES)
def test_every_manifest_setting_drift_is_refused(
    cutover_harness, tmp_path, path, replacement
):
    create_legacy_state(cutover_harness.apps)
    manifest = build_manifest(cutover_harness.apps)
    set_path(manifest, path, replacement)
    cutover_harness.install_manifest(tmp_path, manifest)
    cutover_harness.assert_refused(f"OWN cutover {path} mismatch")


PURCHASE_DRIFT_CASES = [
    ("observed_purchase_state.purchase_count", 2),
    ("observed_purchase_state.original_currency_counts", {"EUR": 2}),
    ("observed_purchase_state.converted_cache_currency", "USD"),
    ("observed_purchase_state.converted_cache_count", 2),
    ("observed_purchase_state.null_converted_price_count", 1),
    ("observed_purchase_state.blank_converted_currency_count", 1),
    ("observed_purchase_state.needs_price_update_count", 1),
    ("observed_purchase_state.mixed_cache_nullability_count", 1),
]


@pytest.mark.parametrize(("path", "replacement"), PURCHASE_DRIFT_CASES)
def test_every_manifest_purchase_cache_drift_is_refused(
    cutover_harness, tmp_path, path, replacement
):
    create_legacy_state(cutover_harness.apps)
    manifest = deepcopy(build_manifest(cutover_harness.apps))
    set_path(manifest, path, replacement)
    cutover_harness.install_manifest(tmp_path, manifest)
    cutover_harness.assert_refused(f"OWN cutover {path} mismatch")


def test_complete_cache_currency_must_match_effective_display_currency(
    cutover_harness, tmp_path
):
    create_legacy_state(cutover_harness.apps)
    Purchase = cutover_harness.apps.get_model("games", "Purchase")
    Purchase.objects.update(converted_currency="USD")
    manifest = build_manifest(cutover_harness.apps)
    cutover_harness.install_manifest(tmp_path, manifest)

    cutover_harness.assert_refused(
        "OWN cutover Purchase converted cache currency does not match "
        "effective display currency"
    )


def test_same_value_boot_currency_source_drift_is_refused(
    cutover_harness, tmp_path, monkeypatch
):
    create_legacy_state(cutover_harness.apps)
    manifest = build_manifest(cutover_harness.apps)
    monkeypatch.setenv("DEFAULT_CURRENCY", "CZK")
    cutover_harness.install_manifest(tmp_path, manifest)
    cutover_harness.assert_refused(
        "OWN cutover operator_confirmed_settings.old_site_currency.source mismatch"
    )


def test_same_value_boot_currency_lock_drift_is_refused(
    cutover_harness, tmp_path, monkeypatch
):
    create_legacy_state(cutover_harness.apps)
    manifest = build_manifest(cutover_harness.apps)
    monkeypatch.setenv("DEFAULT_CURRENCY", "CZK")
    set_path(
        manifest,
        "operator_confirmed_settings.old_site_currency.source",
        "env",
    )
    set_path(
        manifest,
        "operator_confirmed_settings.old_site_currency.locked",
        False,
    )
    cutover_harness.install_manifest(tmp_path, manifest)
    cutover_harness.assert_refused(
        "OWN cutover operator_confirmed_settings.old_site_currency.locked mismatch"
    )


@pytest.mark.parametrize("source", ["env", "dotenv", "ini"])
def test_valid_boot_currency_origins_are_accepted(
    cutover_harness, tmp_path, monkeypatch, settings, source
):
    ids = create_legacy_state(cutover_harness.apps)
    Purchase = cutover_harness.apps.get_model("games", "Purchase")
    Purchase.objects.update(converted_currency="USD")
    settings.DEFAULT_CURRENCY = "USD"
    if source == "env":
        monkeypatch.setenv("DEFAULT_CURRENCY", "usd")
    elif source == "dotenv":
        env_path = tmp_path / ".env"
        env_path.write_text("DEFAULT_CURRENCY=usd\n", encoding="utf-8")
        monkeypatch.setenv("ENV_FILE", str(env_path))
    else:
        ini_path = tmp_path / "settings.ini"
        ini_path.write_text("[timetracker]\nDEFAULT_CURRENCY = usd\n", encoding="utf-8")
        monkeypatch.setenv("INI_FILE", str(ini_path))
    manifest = build_manifest(cutover_harness.apps)
    set_path(
        manifest,
        "operator_confirmed_settings.old_site_currency.value",
        "USD",
    )
    set_path(
        manifest,
        "operator_confirmed_settings.old_site_currency.source",
        source,
    )
    set_path(
        manifest,
        "operator_confirmed_settings.old_site_currency.locked",
        True,
    )
    set_path(
        manifest,
        "operator_confirmed_settings.effective_display_currency",
        "USD",
    )
    cutover_harness.install_manifest(tmp_path, manifest)

    new_apps = cutover_harness.migrate()

    UserLibrary = new_apps.get_model("games", "UserLibrary")
    assert UserLibrary.objects.get().user_id == ids["user_id"]


def test_cutover_replay_does_not_depend_on_runtime_default_currency_setting(
    cutover_harness, tmp_path, settings
):
    create_legacy_state(cutover_harness.apps)
    manifest = build_manifest(cutover_harness.apps)
    del settings.DEFAULT_CURRENCY
    cutover_harness.install_manifest(tmp_path, manifest)

    new_apps = cutover_harness.migrate()

    assert new_apps.get_model("games", "UserLibrary").objects.count() == 1


def test_stale_site_default_device_is_refused_with_actionable_error(
    cutover_harness, tmp_path
):
    create_legacy_state(cutover_harness.apps)
    manifest = build_manifest(cutover_harness.apps)
    UserPreferences = cutover_harness.apps.get_model("games", "UserPreferences")
    SiteSetting = cutover_harness.apps.get_model("games", "SiteSetting")
    UserPreferences.objects.update(default_device_id=None)
    SiteSetting.objects.create(key="DEFAULT_DEVICE", value=999)
    set_path(manifest, "observed_setting_state.site_setting_row_count", 1)
    set_path(
        manifest,
        "observed_setting_state.old_site_default_device_row",
        {"present": True, "value": 999},
    )
    set_path(manifest, "observed_setting_state.old_personal_default_device_id", None)
    set_path(manifest, "operator_confirmed_settings.effective_default_device_id", 999)
    set_path(
        manifest,
        "operator_confirmed_settings.effective_default_device_name",
        "Missing device",
    )
    set_path(
        manifest,
        "operator_confirmed_settings.effective_default_device_source",
        "database",
    )
    cutover_harness.install_manifest(tmp_path, manifest)
    cutover_harness.assert_refused(
        "OWN cutover operator_confirmed_settings.effective_default_device_id "
        "references missing Device"
    )


def test_present_null_site_default_device_keeps_database_origin(
    cutover_harness, tmp_path
):
    ids = create_legacy_state(cutover_harness.apps)
    manifest = build_manifest(cutover_harness.apps)
    UserPreferences = cutover_harness.apps.get_model("games", "UserPreferences")
    SiteSetting = cutover_harness.apps.get_model("games", "SiteSetting")
    UserPreferences.objects.update(default_device_id=None)
    SiteSetting.objects.create(
        key="DEFAULT_DEVICE",
        value=models.Value(None, output_field=models.JSONField()),
    )
    set_path(manifest, "observed_setting_state.site_setting_row_count", 1)
    set_path(
        manifest,
        "observed_setting_state.old_site_default_device_row",
        {"present": True, "value": None},
    )
    set_path(
        manifest,
        "observed_setting_state.old_personal_default_device_id",
        None,
    )
    set_path(
        manifest,
        "operator_confirmed_settings.effective_default_device_id",
        None,
    )
    set_path(
        manifest,
        "operator_confirmed_settings.effective_default_device_name",
        None,
    )
    set_path(
        manifest,
        "operator_confirmed_settings.effective_default_device_source",
        "database",
    )
    cutover_harness.install_manifest(tmp_path, manifest)

    new_apps = cutover_harness.migrate()

    UserLibrary = new_apps.get_model("games", "UserLibrary")
    assert UserLibrary.objects.get().user_id == ids["user_id"]
