import json
import os
import re
from collections import Counter
from configparser import ConfigParser
from configparser import Error as ConfigParserError
from datetime import datetime
from pathlib import Path

import django.db.models.deletion
from django.db import migrations, models
from django.db.models import F, Q
from django.db.models.functions import Lower, Trim
from django.utils import timezone

MANIFEST_ENV = "TIMETRACKER_OWN_CUTOVER_MANIFEST"
LEGACY_DEFAULT_CURRENCY = "CZK"
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
LEGACY_ROW_MODELS = (
    ("Purchase.games", "games", "Purchase", "games"),
    ("PlayEvent", "games", "PlayEvent", None),
    ("GameStatusChange", "games", "GameStatusChange", None),
    ("Session", "games", "Session", None),
    ("Purchase", "games", "Purchase", None),
    ("FilterPreset", "games", "FilterPreset", None),
    ("UserPreferences", "games", "UserPreferences", None),
    ("Game", "games", "Game", None),
    ("Device", "games", "Device", None),
    ("Platform", "games", "Platform", None),
    ("SiteSetting", "games", "SiteSetting", None),
)
CURRENCY_COUNTS = object()
MANIFEST_SCHEMA = {
    "schema_version": int,
    "source": {
        "deployment_version": str,
        "git_commit_short": str,
        "database_name": str,
        "postgres_version": str,
        "dump_filename": str,
        "dump_sha256": str,
    },
    "expected_legacy_state": {
        "user_id": int,
        "username": str,
        "row_counts": {
            "users": int,
            "sessions": int,
            "games": int,
            "devices": int,
            "platforms": int,
            "purchases": int,
            "purchase_games": int,
            "play_events": int,
            "status_changes": int,
            "filter_presets": int,
        },
        "null_session_game_count": int,
        "null_session_device_count": int,
    },
    "observed_setting_state": {
        "user_preferences_row_count": int,
        "site_setting_row_count": int,
        "old_site_currency_row": {
            "present": bool,
            "value": (str, type(None)),
        },
        "old_site_default_device_row": {
            "present": bool,
            "value": (int, type(None)),
        },
        "old_personal_currency_value": (str, type(None)),
        "old_personal_default_device_id": (int, type(None)),
    },
    "operator_confirmed_settings": {
        "old_site_currency": {
            "value": str,
            "source": str,
            "locked": bool,
        },
        "old_personal_currency": {
            "value": str,
            "source": str,
            "locked": bool,
        },
        "effective_purchase_currency": str,
        "effective_display_currency": str,
        "effective_default_device_id": (int, type(None)),
        "effective_default_device_name": (str, type(None)),
        "effective_default_device_source": str,
    },
    "observed_purchase_state": {
        "purchase_count": int,
        "original_currency_counts": CURRENCY_COUNTS,
        "converted_cache_currency": str,
        "converted_cache_count": int,
        "null_converted_price_count": int,
        "blank_converted_currency_count": int,
        "needs_price_update_count": int,
        "mixed_cache_nullability_count": int,
    },
}


def manifest_error(path, detail):
    raise RuntimeError(f"OWN cutover {path} {detail}")


def validate_typed_value(value, schema, path):
    if schema is CURRENCY_COUNTS:
        if type(value) is not dict:
            manifest_error(path, "must be an object")
        for key, count in value.items():
            if type(key) is not str or type(count) is not int or count < 0:
                manifest_error(
                    path, "must map currency strings to non-negative integers"
                )
        return
    if type(schema) is dict:
        if type(value) is not dict:
            manifest_error(path, "must be an object")
        missing = sorted(set(schema) - set(value))
        if missing:
            manifest_error(f"{path}.{missing[0]}", "is missing")
        unexpected = sorted(set(value) - set(schema))
        if unexpected:
            manifest_error(path, f"has unexpected fields: {', '.join(unexpected)}")
        for key, child_schema in schema.items():
            validate_typed_value(value[key], child_schema, f"{path}.{key}")
        return
    allowed_types = schema if type(schema) is tuple else (schema,)
    if type(value) not in allowed_types:
        names = "/".join(item.__name__ for item in allowed_types)
        manifest_error(path, f"must have type {names}")


def validate_manifest_schema(manifest):
    validate_typed_value(manifest, MANIFEST_SCHEMA, "manifest")
    if manifest["schema_version"] != 1:
        manifest_error("manifest.schema_version", "must equal 1")
    if not re.fullmatch(r"[0-9a-f]{64}", manifest["source"]["dump_sha256"]):
        manifest_error(
            "manifest.source.dump_sha256", "must be 64 lowercase hexadecimal characters"
        )
    for key in (
        "deployment_version",
        "git_commit_short",
        "database_name",
        "postgres_version",
        "dump_filename",
    ):
        if not manifest["source"][key]:
            manifest_error(f"manifest.source.{key}", "must not be empty")
    for path, count in manifest_counts(manifest):
        if count < 0:
            manifest_error(path, "must be non-negative")


def manifest_counts(manifest):
    expected = manifest["expected_legacy_state"]
    observed_settings = manifest["observed_setting_state"]
    observed_purchases = manifest["observed_purchase_state"]
    for key, value in expected["row_counts"].items():
        yield f"manifest.expected_legacy_state.row_counts.{key}", value
    yield (
        "manifest.expected_legacy_state.null_session_game_count",
        expected["null_session_game_count"],
    )
    yield (
        "manifest.expected_legacy_state.null_session_device_count",
        expected["null_session_device_count"],
    )
    yield (
        "manifest.observed_setting_state.user_preferences_row_count",
        observed_settings["user_preferences_row_count"],
    )
    yield (
        "manifest.observed_setting_state.site_setting_row_count",
        observed_settings["site_setting_row_count"],
    )
    for key in (
        "purchase_count",
        "converted_cache_count",
        "null_converted_price_count",
        "blank_converted_currency_count",
        "needs_price_update_count",
        "mixed_cache_nullability_count",
    ):
        yield f"manifest.observed_purchase_state.{key}", observed_purchases[key]


def load_and_validate_manifest(apps, path_value):
    del apps
    if not path_value:
        raise RuntimeError(f"OWN cutover requires {MANIFEST_ENV}")
    path = Path(path_value)
    if not path.is_absolute():
        raise RuntimeError("OWN cutover manifest path must be absolute")
    try:
        contents = path.read_text(encoding="utf-8")
    except OSError:
        raise RuntimeError("OWN cutover manifest is unreadable") from None
    try:
        manifest = json.loads(contents)
    except json.JSONDecodeError, UnicodeDecodeError:
        raise RuntimeError("OWN cutover manifest is not valid JSON") from None
    validate_manifest_schema(manifest)
    return manifest


def legacy_rows(apps):
    populated = []
    for label, app_label, model_name, relation_name in LEGACY_ROW_MODELS:
        model = apps.get_model(app_label, model_name)
        manager = (
            getattr(model, relation_name).through.objects
            if relation_name
            else model.objects
        )
        if manager.exists():
            populated.append(label)
    return populated


def legacy_rows_exist(apps):
    return bool(legacy_rows(apps))


def select_cutover_input(apps):
    User = apps.get_model("auth", "User")
    user_count = User.objects.count()
    if user_count == 0:
        populated = legacy_rows(apps)
        if populated:
            raise RuntimeError(
                f"OWN cutover found orphaned legacy state: {', '.join(populated)}"
            )
        return None
    if user_count != 1:
        raise RuntimeError("OWN cutover requires zero or exactly one User")
    UserLibrary = apps.get_model("games", "UserLibrary")
    if UserLibrary.objects.exists():
        raise RuntimeError("OWN cutover requires no pre-existing UserLibrary")
    return load_and_validate_manifest(apps, os.environ.get(MANIFEST_ENV))


def require_match(path, actual, expected):
    if actual != expected:
        raise RuntimeError(f"OWN cutover {path} mismatch")


def actual_row_counts(apps):
    counts = {
        key: apps.get_model(*model).objects.count()
        for key, model in ROW_COUNT_MODELS.items()
    }
    Purchase = apps.get_model("games", "Purchase")
    counts["purchase_games"] = Purchase.games.through.objects.count()
    return counts


def raw_setting_row(apps, key):
    SiteSetting = apps.get_model("games", "SiteSetting")
    values = list(SiteSetting.objects.filter(key=key).values_list("value", flat=True))
    return {"present": bool(values), "value": values[0] if values else None}


def contains_session_game_null_predicate(value):
    if type(value) is dict:
        game = value.get("game")
        if type(game) is dict and game.get("modifier") in {"IS_NULL", "NOT_NULL"}:
            return True
        return any(
            contains_session_game_null_predicate(child) for child in value.values()
        )
    if type(value) is list:
        return any(contains_session_game_null_predicate(child) for child in value)
    return False


def validate_identity_and_counts(apps, manifest):
    User = apps.get_model("auth", "User")
    user = User.objects.get()
    expected = manifest["expected_legacy_state"]
    require_match("expected_legacy_state.user_id", user.pk, expected["user_id"])
    require_match("expected_legacy_state.username", user.username, expected["username"])
    counts = actual_row_counts(apps)
    for key, expected_count in expected["row_counts"].items():
        require_match(
            f"expected_legacy_state.row_counts.{key}", counts[key], expected_count
        )
    Session = apps.get_model("games", "Session")
    null_game_count = Session.objects.filter(game_id=None).count()
    null_device_count = Session.objects.filter(device_id=None).count()
    require_match(
        "expected_legacy_state.null_session_game_count",
        null_game_count,
        expected["null_session_game_count"],
    )
    require_match(
        "expected_legacy_state.null_session_device_count",
        null_device_count,
        expected["null_session_device_count"],
    )
    if null_game_count:
        raise RuntimeError("OWN cutover requires every Session to have a Game")


def validate_platforms_and_presets(apps):
    Platform = apps.get_model("games", "Platform")
    for name, group in sorted(BUILT_IN_PLATFORMS):
        if Platform.objects.filter(name=name, group=group).count() != 1:
            raise RuntimeError(
                f"OWN cutover built-in Platform classification is ambiguous: {name}|{group}"
            )
    seen = set()
    for name, group in Platform.objects.values_list("name", "group"):
        normalized = (name.strip().casefold(), group.strip().casefold())
        if normalized in seen:
            raise RuntimeError(
                "OWN cutover Platform names collide after trim/case normalization"
            )
        seen.add(normalized)
    FilterPreset = apps.get_model("games", "FilterPreset")
    for preset in FilterPreset.objects.filter(mode="sessions").only("object_filter"):
        if contains_session_game_null_predicate(preset.object_filter):
            raise RuntimeError(
                "OWN cutover saved Session filter depends on nullable game"
            )


def unquote_env_value(value):
    if not value:
        return value
    quote = value[0]
    if quote in "\"'":
        closing = value.find(quote, 1)
        return value[1:closing] if closing != -1 else value[1:]
    comment_index = value.find("#")
    if comment_index != -1:
        value = value[:comment_index]
    return value.strip()


def parse_env_file(path):
    values = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        if "=" not in line:
            continue
        name, _, value = line.partition("=")
        name = name.strip()
        if name:
            values[name] = unquote_env_value(value.strip())
    return values


def legacy_boot_config_value(name):
    # DEFAULT_CURRENCY and DEFAULT_DEVICE did not opt into NAME__FILE in the
    # legacy registry, so the frozen precedence is env -> .env -> INI -> default.
    if name in os.environ:
        return os.environ[name], "env"
    base_dir = Path(__file__).resolve().parents[2]
    env_path = Path(os.environ.get("ENV_FILE", base_dir / ".env"))
    try:
        env_values = parse_env_file(env_path) if env_path.is_file() else {}
    except OSError, UnicodeError:
        raise RuntimeError(
            "OWN cutover legacy .env configuration is unreadable"
        ) from None
    if name in env_values:
        return env_values[name], "dotenv"
    ini_path = Path(os.environ.get("INI_FILE", base_dir / "settings.ini"))
    try:
        ini_contents = (
            ini_path.read_text(encoding="utf-8") if ini_path.is_file() else ""
        )
        parser = ConfigParser()
        parser.optionxform = str
        if ini_contents:
            parser.read_string(ini_contents)
        ini_values = (
            dict(parser["timetracker"]) if parser.has_section("timetracker") else {}
        )
    except OSError, UnicodeError, ConfigParserError:
        raise RuntimeError(
            "OWN cutover legacy INI configuration is unreadable"
        ) from None
    if name in ini_values:
        return ini_values[name], "ini"
    return None


def normalize_currency(value, path):
    currency = str(value).strip().upper()
    if len(currency) != 3 or not currency.isascii() or not currency.isalpha():
        raise RuntimeError(f"OWN cutover {path} is invalid")
    return currency


def legacy_site_currency(apps):
    boot_value = legacy_boot_config_value("DEFAULT_CURRENCY")
    if boot_value is not None:
        value, source = boot_value
        return normalize_currency(value, "legacy DEFAULT_CURRENCY"), source, True
    row = raw_setting_row(apps, "DEFAULT_CURRENCY")
    if row["present"]:
        try:
            return (
                normalize_currency(row["value"], "legacy DEFAULT_CURRENCY row"),
                "database",
                False,
            )
        except RuntimeError:
            # The old resolver logged an invalid DB value and fell through.
            pass
    return LEGACY_DEFAULT_CURRENCY, "default", False


def normalize_device_id(value, path):
    if type(value) is str:
        try:
            value = int(value)
        except ValueError:
            raise RuntimeError(f"OWN cutover {path} is invalid") from None
    if type(value) is not int:
        raise RuntimeError(f"OWN cutover {path} is invalid")
    return value


def validate_settings(apps, manifest):
    observed = manifest["observed_setting_state"]
    confirmed = manifest["operator_confirmed_settings"]
    UserPreferences = apps.get_model("games", "UserPreferences")
    SiteSetting = apps.get_model("games", "SiteSetting")
    Device = apps.get_model("games", "Device")
    require_match(
        "observed_setting_state.user_preferences_row_count",
        UserPreferences.objects.count(),
        observed["user_preferences_row_count"],
    )
    require_match(
        "observed_setting_state.site_setting_row_count",
        SiteSetting.objects.count(),
        observed["site_setting_row_count"],
    )
    if UserPreferences.objects.count() != 1:
        raise RuntimeError("OWN cutover requires exactly one UserPreferences row")
    preferences = UserPreferences.objects.get()
    for key, setting_name in (
        ("old_site_currency_row", "DEFAULT_CURRENCY"),
        ("old_site_default_device_row", "DEFAULT_DEVICE"),
    ):
        actual = raw_setting_row(apps, setting_name)
        require_match(
            f"observed_setting_state.{key}.present",
            actual["present"],
            observed[key]["present"],
        )
        require_match(
            f"observed_setting_state.{key}.value",
            actual["value"],
            observed[key]["value"],
        )
    require_match(
        "observed_setting_state.old_personal_currency_value",
        preferences.default_currency,
        observed["old_personal_currency_value"],
    )
    require_match(
        "observed_setting_state.old_personal_default_device_id",
        preferences.default_device_id,
        observed["old_personal_default_device_id"],
    )

    site_currency, site_source, site_locked = legacy_site_currency(apps)
    expected_site = {
        "value": site_currency,
        "source": site_source,
        "locked": site_locked,
    }
    for key, actual in expected_site.items():
        require_match(
            f"operator_confirmed_settings.old_site_currency.{key}",
            actual,
            confirmed["old_site_currency"][key],
        )

    if preferences.default_currency is not None:
        try:
            personal_currency = normalize_currency(
                preferences.default_currency, "legacy personal DEFAULT_CURRENCY"
            )
        except RuntimeError:
            personal_currency = site_currency
            personal_source = site_source
            personal_locked = site_locked
        else:
            personal_source = "user"
            personal_locked = False
    else:
        personal_currency = site_currency
        personal_source = site_source
        personal_locked = site_locked
    expected_personal = {
        "value": personal_currency,
        "source": personal_source,
        "locked": personal_locked,
    }
    for key, actual in expected_personal.items():
        require_match(
            f"operator_confirmed_settings.old_personal_currency.{key}",
            actual,
            confirmed["old_personal_currency"][key],
        )
    require_match(
        "operator_confirmed_settings.effective_purchase_currency",
        personal_currency,
        confirmed["effective_purchase_currency"],
    )
    require_match(
        "operator_confirmed_settings.effective_display_currency",
        site_currency,
        confirmed["effective_display_currency"],
    )

    site_device_row = raw_setting_row(apps, "DEFAULT_DEVICE")
    if preferences.default_device_id is not None:
        default_device_id = preferences.default_device_id
        default_device_source = "user"
    else:
        boot_device = legacy_boot_config_value("DEFAULT_DEVICE")
        if boot_device is not None:
            raw_device_id, default_device_source = boot_device
            default_device_id = normalize_device_id(
                raw_device_id, "legacy DEFAULT_DEVICE"
            )
        elif site_device_row["present"]:
            if site_device_row["value"] is None:
                default_device_id = None
                default_device_source = "database"
            else:
                try:
                    default_device_id = normalize_device_id(
                        site_device_row["value"], "legacy DEFAULT_DEVICE row"
                    )
                except RuntimeError:
                    default_device_id = None
                    default_device_source = "default"
                else:
                    default_device_source = "database"
        else:
            default_device_id = None
            default_device_source = "default"
    default_device_name = None
    if default_device_id is not None:
        default_device_name = (
            Device.objects.filter(pk=default_device_id)
            .values_list("name", flat=True)
            .first()
        )
        if default_device_name is None:
            raise RuntimeError(
                "OWN cutover operator_confirmed_settings.effective_default_device_id "
                "references missing Device"
            )
    for key, actual in (
        ("effective_default_device_id", default_device_id),
        ("effective_default_device_name", default_device_name),
        ("effective_default_device_source", default_device_source),
    ):
        require_match(f"operator_confirmed_settings.{key}", actual, confirmed[key])


def validate_purchase_state(apps, manifest):
    Purchase = apps.get_model("games", "Purchase")
    observed = manifest["observed_purchase_state"]
    purchases = list(
        Purchase.objects.values(
            "price_currency",
            "converted_price",
            "converted_currency",
            "needs_price_update",
        )
    )
    original_counts = dict(
        sorted(Counter(row["price_currency"] for row in purchases).items())
    )
    currencies = {
        row["converted_currency"] for row in purchases if row["converted_currency"]
    }
    actual_currency = next(iter(currencies)) if len(currencies) == 1 else None
    if not purchases:
        actual_currency = manifest["operator_confirmed_settings"][
            "effective_display_currency"
        ]
    actual = {
        "purchase_count": len(purchases),
        "original_currency_counts": original_counts,
        "converted_cache_currency": actual_currency,
        "converted_cache_count": sum(
            row["converted_currency"] == actual_currency for row in purchases
        ),
        "null_converted_price_count": sum(
            row["converted_price"] is None for row in purchases
        ),
        "blank_converted_currency_count": sum(
            row["converted_currency"] == "" for row in purchases
        ),
        "needs_price_update_count": sum(row["needs_price_update"] for row in purchases),
        "mixed_cache_nullability_count": sum(
            (row["converted_price"] is None) != (row["converted_currency"] == "")
            for row in purchases
        ),
    }
    for key, actual_value in actual.items():
        require_match(f"observed_purchase_state.{key}", actual_value, observed[key])
    if actual["mixed_cache_nullability_count"]:
        raise RuntimeError("OWN cutover Purchase converted cache has mixed nullability")
    if (
        len(currencies) > 1
        or actual["converted_cache_count"] != len(purchases)
        or actual["null_converted_price_count"]
        or actual["blank_converted_currency_count"]
        or actual["needs_price_update_count"]
    ):
        raise RuntimeError("OWN cutover Purchase converted cache is incomplete")
    if "" in original_counts:
        raise RuntimeError("OWN cutover Purchase original currency is blank")


def validate_legacy_shape(apps, manifest):
    validate_identity_and_counts(apps, manifest)
    validate_platforms_and_presets(apps)
    validate_settings(apps, manifest)
    validate_purchase_state(apps, manifest)


def backfill_known_library(apps, manifest):
    UserLibrary = apps.get_model("games", "UserLibrary")
    return UserLibrary.objects.create(
        user_id=manifest["expected_legacy_state"]["user_id"],
        created_at=FIRST_COMMIT_AT,
    )


def backfill_ownership_and_state(apps, manifest, library):
    Game = apps.get_model("games", "Game")
    Platform = apps.get_model("games", "Platform")
    Purchase = apps.get_model("games", "Purchase")
    Device = apps.get_model("games", "Device")
    FilterPreset = apps.get_model("games", "FilterPreset")
    UserPreferences = apps.get_model("games", "UserPreferences")
    UserLibraryPreferences = apps.get_model("games", "UserLibraryPreferences")
    PurchaseConversionState = apps.get_model("games", "PurchaseConversionState")

    Game.objects.update(library_id=library.pk)
    Purchase.objects.update(library_id=library.pk)
    Device.objects.update(library_id=library.pk)
    FilterPreset.objects.update(library_id=library.pk)

    shared_platform_ids = []
    for name, group in sorted(BUILT_IN_PLATFORMS):
        shared_platform_ids.append(Platform.objects.get(name=name, group=group).pk)
    Platform.objects.exclude(pk__in=shared_platform_ids).update(library_id=library.pk)

    preferences = UserPreferences.objects.get()
    confirmed = manifest["operator_confirmed_settings"]
    UserLibraryPreferences.objects.create(
        library_id=library.pk,
        default_device_id=confirmed["effective_default_device_id"],
        updated_at=preferences.updated_at,
    )
    display_currency = confirmed["effective_display_currency"]
    PurchaseConversionState.objects.create(
        library_id=library.pk,
        requested_version=1,
        requested_currency=display_currency,
        published_version=1,
        published_currency=display_currency,
        status="complete",
        retry_at=None,
        last_error="",
    )


def reconcile_cutover(apps, manifest, library):
    validate_legacy_shape(apps, manifest)
    expected_counts = manifest["expected_legacy_state"]["row_counts"]
    Game = apps.get_model("games", "Game")
    Platform = apps.get_model("games", "Platform")
    Purchase = apps.get_model("games", "Purchase")
    Session = apps.get_model("games", "Session")
    Device = apps.get_model("games", "Device")
    PlayEvent = apps.get_model("games", "PlayEvent")
    GameStatusChange = apps.get_model("games", "GameStatusChange")
    FilterPreset = apps.get_model("games", "FilterPreset")
    UserLibraryPreferences = apps.get_model("games", "UserLibraryPreferences")
    PurchaseConversionState = apps.get_model("games", "PurchaseConversionState")

    require_match(
        "reconciliation.library.created_at", library.created_at, FIRST_COMMIT_AT
    )
    for label, model, count_key in (
        ("Game", Game, "games"),
        ("Purchase", Purchase, "purchases"),
        ("Device", Device, "devices"),
        ("FilterPreset", FilterPreset, "filter_presets"),
    ):
        require_match(
            f"reconciliation.{label}.owned_count",
            model.objects.filter(library_id=library.pk).count(),
            expected_counts[count_key],
        )
        require_match(
            f"reconciliation.{label}.unowned_count",
            model.objects.filter(library_id=None).count(),
            0,
        )

    shared_pairs = set(
        Platform.objects.filter(library_id=None).values_list("name", "group")
    )
    require_match(
        "reconciliation.Platform.shared_pairs", shared_pairs, BUILT_IN_PLATFORMS
    )
    require_match(
        "reconciliation.Platform.private_count",
        Platform.objects.filter(library_id=library.pk).count(),
        expected_counts["platforms"] - len(BUILT_IN_PLATFORMS),
    )

    game_keys = list(
        Game.objects.values_list("library_id", "name", "platform_id", "year_released")
    )
    require_match(
        "reconciliation.Game.unique_library_identity_count",
        len(set(game_keys)),
        len(game_keys),
    )

    for purchase in Purchase.objects.all():
        if purchase.library_id != library.pk:
            raise RuntimeError("OWN cutover reconciliation.Purchase owner mismatch")
        if purchase.related_game_id is not None:
            related_library_id = Game.objects.values_list("library_id", flat=True).get(
                pk=purchase.related_game_id
            )
            if related_library_id != library.pk:
                raise RuntimeError(
                    "OWN cutover reconciliation.Purchase related Game mismatch"
                )
        if purchase.platform_id is not None:
            platform_library_id = Platform.objects.values_list(
                "library_id", flat=True
            ).get(pk=purchase.platform_id)
            if platform_library_id not in (None, library.pk):
                raise RuntimeError(
                    "OWN cutover reconciliation.Purchase Platform mismatch"
                )
        if purchase.games.exclude(library_id=library.pk).exists():
            raise RuntimeError(
                "OWN cutover reconciliation.Purchase Game relationship mismatch"
            )

    for session in Session.objects.select_related("game", "device"):
        if session.game_id is None or session.game.library_id != library.pk:
            raise RuntimeError("OWN cutover reconciliation.Session Game mismatch")
        if session.device_id is not None and session.device.library_id != library.pk:
            raise RuntimeError("OWN cutover reconciliation.Session Device mismatch")
    if PlayEvent.objects.exclude(game__library_id=library.pk).exists():
        raise RuntimeError("OWN cutover reconciliation.PlayEvent owner mismatch")
    if GameStatusChange.objects.exclude(game__library_id=library.pk).exists():
        raise RuntimeError("OWN cutover reconciliation.GameStatusChange owner mismatch")

    confirmed = manifest["operator_confirmed_settings"]
    preference = UserLibraryPreferences.objects.get(library_id=library.pk)
    require_match(
        "reconciliation.UserLibraryPreferences.default_device_id",
        preference.default_device_id,
        confirmed["effective_default_device_id"],
    )
    state = PurchaseConversionState.objects.get(library_id=library.pk)
    expected_state = (
        1,
        confirmed["effective_display_currency"],
        1,
        confirmed["effective_display_currency"],
        "complete",
        None,
        "",
    )
    actual_state = (
        state.requested_version,
        state.requested_currency,
        state.published_version,
        state.published_currency,
        state.status,
        state.retry_at,
        state.last_error,
    )
    require_match(
        "reconciliation.PurchaseConversionState", actual_state, expected_state
    )

    source = manifest["source"]
    print(
        "OWN cutover reconciled "
        f"deployment={source['deployment_version']} "
        f"dump_sha256={source['dump_sha256']} "
        f"library={library.pk}"
    )


def run_cutover(apps, schema_editor):
    del schema_editor
    manifest = select_cutover_input(apps)
    if manifest is None:
        return
    validate_legacy_shape(apps, manifest)
    library = backfill_known_library(apps, manifest)
    backfill_ownership_and_state(apps, manifest, library)
    reconcile_cutover(apps, manifest, library)


class Migration(migrations.Migration):
    dependencies = [("games", "0003_userlibrary")]
    operations = [
        migrations.AddField(
            model_name="game",
            name="library",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="games",
                to="games.userlibrary",
            ),
        ),
        migrations.AddField(
            model_name="purchase",
            name="library",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="purchases",
                to="games.userlibrary",
            ),
        ),
        migrations.AddField(
            model_name="device",
            name="library",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="devices",
                to="games.userlibrary",
            ),
        ),
        migrations.AddField(
            model_name="filterpreset",
            name="library",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="filter_presets",
                to="games.userlibrary",
            ),
        ),
        migrations.AddField(
            model_name="platform",
            name="library",
            field=models.ForeignKey(
                blank=True,
                default=None,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="platforms",
                to="games.userlibrary",
            ),
        ),
        migrations.CreateModel(
            name="UserLibraryPreferences",
            fields=[
                (
                    "library",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        primary_key=True,
                        related_name="preferences",
                        serialize=False,
                        to="games.userlibrary",
                    ),
                ),
                (
                    "default_device",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to="games.device",
                    ),
                ),
                ("updated_at", models.DateTimeField(default=timezone.now)),
            ],
        ),
        migrations.CreateModel(
            name="PurchaseConversionState",
            fields=[
                (
                    "library",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        primary_key=True,
                        related_name="purchase_conversion_state",
                        serialize=False,
                        to="games.userlibrary",
                    ),
                ),
                (
                    "requested_version",
                    models.PositiveBigIntegerField(default=0),
                ),
                (
                    "requested_currency",
                    models.CharField(blank=True, default="", max_length=3),
                ),
                (
                    "published_version",
                    models.PositiveBigIntegerField(default=0),
                ),
                (
                    "published_currency",
                    models.CharField(blank=True, default="", max_length=3),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("running", "Running"),
                            ("failed", "Failed"),
                            ("complete", "Complete"),
                        ],
                        default="complete",
                        max_length=10,
                    ),
                ),
                (
                    "retry_at",
                    models.DateTimeField(blank=True, default=None, null=True),
                ),
                ("last_error", models.TextField(blank=True, default="")),
            ],
        ),
        migrations.RunPython(run_cutover, migrations.RunPython.noop),
        migrations.RunSQL(
            sql="SET CONSTRAINTS ALL IMMEDIATE",
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.AlterField(
            model_name="game",
            name="library",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="games",
                to="games.userlibrary",
            ),
        ),
        migrations.AlterField(
            model_name="purchase",
            name="library",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="purchases",
                to="games.userlibrary",
            ),
        ),
        migrations.AlterField(
            model_name="device",
            name="library",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="devices",
                to="games.userlibrary",
            ),
        ),
        migrations.AlterField(
            model_name="filterpreset",
            name="library",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="filter_presets",
                to="games.userlibrary",
            ),
        ),
        migrations.AlterField(
            model_name="session",
            name="game",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="sessions",
                to="games.game",
            ),
        ),
        migrations.RemoveConstraint(
            model_name="game",
            name="unique_platformless_game_name_year",
        ),
        migrations.AlterUniqueTogether(
            name="game",
            unique_together={("library", "name", "platform", "year_released")},
        ),
        migrations.AddConstraint(
            model_name="game",
            constraint=models.UniqueConstraint(
                condition=Q(platform__isnull=True),
                fields=("library", "name", "year_released"),
                name="unique_library_platformless_game_name_year",
            ),
        ),
        migrations.RemoveConstraint(
            model_name="filterpreset",
            name="unique_user_mode_name_preset",
        ),
        migrations.RemoveField(
            model_name="filterpreset",
            name="user",
        ),
        migrations.AddConstraint(
            model_name="filterpreset",
            constraint=models.UniqueConstraint(
                fields=("library", "mode", "name"),
                name="unique_library_mode_name_preset",
            ),
        ),
        migrations.AddConstraint(
            model_name="platform",
            constraint=models.UniqueConstraint(
                Lower(Trim("name")),
                Lower(Trim("group")),
                condition=Q(library__isnull=True),
                name="unique_shared_platform_normalized_name_group",
            ),
        ),
        migrations.AddConstraint(
            model_name="platform",
            constraint=models.UniqueConstraint(
                F("library"),
                Lower(Trim("name")),
                Lower(Trim("group")),
                condition=Q(library__isnull=False),
                name="unique_private_platform_normalized_name_group",
            ),
        ),
    ]
