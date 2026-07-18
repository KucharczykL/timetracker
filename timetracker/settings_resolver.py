"""Layered setting resolution: env/.env/ini (locked) > SiteSetting (DB) > default.

Non-obvious points:

- Lazy by design: no DB or ``settings`` access at import (the ``SiteSetting``
  model is imported inside functions), so ``settings.py`` can import this safely.
- Only the DB layer is cached (one snapshot, TTL); env/default recompute each
  call so ``override_settings`` and dynamic defaults stay live. Cross-process
  (web worker + qcluster) convergence is the TTL; a raw ``QuerySet.update()``
  skips signal invalidation and is stale until it lapses.
- Every layer runs through the registry cast+validator, so a DB ``"eur"`` and an
  env ``EUR`` resolve identically.
- Sync only: cold-cache ``resolve`` issues an ORM query; async callers need
  ``sync_to_async``.
"""

import logging
import threading
import time
from typing import cast

from django.core.exceptions import ValidationError
from django.db.utils import OperationalError, ProgrammingError

from timetracker.config import (
    LOCKED_SOURCES,
    RawConfigValue,
    ResolvedSetting,
    SettingSource,
    cast_value,
    resolve_raw_with_source,
)
from timetracker.settings_registry import (
    SettingDefinition,
    SettingKey,
    SettingScope,
    get_definition,
)

logger = logging.getLogger("games")

#: How long a SiteSetting snapshot is trusted before the next read refreshes it.
#: Also the cross-process convergence window (web worker ↔ qcluster).
SITE_SETTINGS_TTL_SECONDS = 5.0

_cache_lock = threading.Lock()
_snapshot: dict[str, object] | None = None
_snapshot_at: float = 0.0

#: Per-user preference snapshot, mirroring the site snapshot: the *whole*
#: UserPreferences table keyed by user id, loaded outside the lock and swapped
#: atomically under one timestamp. Never lazy-filled per user — a partial fill
#: racing clear_cache could resurrect a stale entry (the site snapshot is safe
#: only because each load replaces the dict wholesale).
type UserId = int  # e.g. 42
_user_snapshot: dict[UserId, dict[str, object]] | None = None
_user_snapshot_at: float = 0.0


def normalize_setting_value(value: object, definition: SettingDefinition) -> object:
    """Cast (strings only) + validate a value. Shared by the resolver read path,
    ``set_site_setting``, and the admin form so every write/read normalizes alike."""
    if isinstance(value, str):
        value = cast_value(value, definition.cast)
    if definition.validator is not None:
        value = definition.validator(value)
    return value


def _load_snapshot() -> dict[str, object]:
    from games.models import SiteSetting

    return dict(SiteSetting.objects.values_list("key", "value"))


def _site_settings() -> dict[str, object]:
    """Cached SiteSetting snapshot; the DB read runs outside the lock (which only
    guards the swap) so a slow/locked DB can't serialize every worker thread."""
    global _snapshot, _snapshot_at
    now = time.monotonic()
    snapshot = _snapshot
    if snapshot is not None and (now - _snapshot_at) < SITE_SETTINGS_TTL_SECONDS:
        return snapshot
    try:
        fresh = _load_snapshot()
    except (OperationalError, ProgrammingError) as error:
        # Any read failure (missing table on a fresh/mid-migration DB, but also a
        # transient lock/IO fault) degrades to "no overrides". Not cached, so it
        # self-heals on the next read instead of crashing every resolve.
        logger.warning(
            "[settings_resolver]: SiteSetting unreadable, using defaults: %s", error
        )
        return {}
    with _cache_lock:
        _snapshot = fresh
        _snapshot_at = time.monotonic()
    return fresh


def _load_user_snapshot() -> dict[UserId, dict[str, object]]:
    from games.models import USER_PREFERENCE_FIELD_BY_KEY, UserPreferences

    columns = ["user_id", *USER_PREFERENCE_FIELD_BY_KEY.values(), "extra_preferences"]
    snapshot: dict[UserId, dict[str, object]] = {}
    for row in UserPreferences.objects.values(*columns):
        user_id = row["user_id"]
        stored: dict[str, object] = dict(row.get("extra_preferences") or {})
        # Typed columns win over the JSON bag and only enter the map when set,
        # so a NULL column reads as "unset" (absent key → falls through).
        for key, field in USER_PREFERENCE_FIELD_BY_KEY.items():
            value = row[field]
            if value is not None:
                stored[key] = value
        snapshot[user_id] = stored
    return snapshot


def _user_preferences() -> dict[UserId, dict[str, object]]:
    """Cached whole-table UserPreferences snapshot; the DB read runs outside the
    lock (which only guards the swap), mirroring :func:`_site_settings`."""
    global _user_snapshot, _user_snapshot_at
    now = time.monotonic()
    snapshot = _user_snapshot
    if snapshot is not None and (now - _user_snapshot_at) < SITE_SETTINGS_TTL_SECONDS:
        return snapshot
    try:
        fresh = _load_user_snapshot()
    except (OperationalError, ProgrammingError) as error:
        logger.warning(
            "[settings_resolver]: UserPreferences unreadable, using site layer: %s",
            error,
        )
        return {}
    with _cache_lock:
        _user_snapshot = fresh
        _user_snapshot_at = time.monotonic()
    return fresh


def clear_cache() -> None:
    """Drop both cached snapshots (next resolve re-reads the DB)."""
    global _snapshot, _snapshot_at, _user_snapshot, _user_snapshot_at
    with _cache_lock:
        _snapshot = None
        _snapshot_at = 0.0
        _user_snapshot = None
        _user_snapshot_at = 0.0


def resolve_with_origin(key: SettingKey) -> ResolvedSetting:
    """Resolve ``key`` to ``(value, source, locked)`` across all layers."""
    definition = get_definition(key)

    raw: RawConfigValue | None = resolve_raw_with_source(
        definition.env_name or definition.key, allow_file=definition.allow_file
    )
    if raw is not None:
        # Env/file/ini are operator-set boot config: a bad value fails loudly.
        value = normalize_setting_value(raw.raw, definition)
        return ResolvedSetting(value, raw.source, raw.source in LOCKED_SOURCES)

    # SITE and USER keys both read the SiteSetting DB layer here: for a USER key
    # this is the *site default* underneath any personal override (which a caller
    # applies earlier, via resolve_for_user_with_origin). INFRA short-circuits.
    if definition.scope in (SettingScope.SITE, SettingScope.USER):
        snapshot = _site_settings()
        if key in snapshot:
            try:
                value = normalize_setting_value(snapshot[key], definition)
            except (ValidationError, ValueError, TypeError) as error:
                # A poisoned DB row (raw SQL / update() / bad migration) must not
                # crash every resolve — log and fall through to the default.
                logger.error(
                    "[settings_resolver]: invalid stored %s=%r, using default: %s",
                    key,
                    snapshot[key],
                    error,
                )
            else:
                return ResolvedSetting(value, SettingSource.DATABASE, False)

    return ResolvedSetting(definition.default_factory(), SettingSource.DEFAULT, False)


def resolve(key: SettingKey) -> object:
    """Resolved value of ``key`` (drops the origin)."""
    return resolve_with_origin(key).value


def resolve_str(key: SettingKey) -> str:
    """Resolved value as ``str``. Raises ``TypeError`` for a non-str setting rather
    than coercing a bool/list/Path into a misleading ``"True"``/``"['a']"``."""
    value = resolve(key)
    if not isinstance(value, str):
        raise TypeError(f"{key} did not resolve to a str (got {type(value).__name__}).")
    return value


def resolve_for_user_with_origin(user: object, key: SettingKey) -> ResolvedSetting:
    """Resolve ``key`` for ``user``: a personal override (source ``USER``) wins,
    else fall through to the shared chain (env → site DB → default).

    For a non-USER key, or an anonymous/None user, this is exactly
    :func:`resolve_with_origin`, so callers can use one entry point. Never locked:
    env-locking per-user prefs is deferred, so a personal value overrides env.
    """
    definition = get_definition(key)
    user_id = getattr(user, "pk", None)
    if definition.scope is SettingScope.USER and user_id is not None:
        stored = _user_preferences().get(user_id, {})
        if key in stored:
            try:
                value = normalize_setting_value(stored[key], definition)
            except (ValidationError, ValueError, TypeError) as error:
                # A poisoned column (raw update() / bad data) must not crash every
                # resolve — log and fall through to the site/default layers.
                logger.error(
                    "[settings_resolver]: invalid stored %s=%r for user %s, "
                    "using site layer: %s",
                    key,
                    stored[key],
                    user_id,
                    error,
                )
            else:
                return ResolvedSetting(value, SettingSource.USER, False)
    return resolve_with_origin(key)


def resolve_for_user(user: object, key: SettingKey) -> object:
    """Resolved value of ``key`` for ``user`` (drops the origin)."""
    return resolve_for_user_with_origin(user, key).value


def resolve_str_for_user(user: object, key: SettingKey) -> str:
    """Resolved value of ``key`` for ``user`` as ``str`` (raises for non-str)."""
    value = resolve_for_user(user, key)
    if not isinstance(value, str):
        raise TypeError(f"{key} did not resolve to a str (got {type(value).__name__}).")
    return value


def set_user_preference(user: object, key: SettingKey, value: object) -> None:
    """Upsert a user-scoped preference (validated + normalized); ``None`` clears.

    Raises for an unregistered key, a non-``USER`` key, a value the definition's
    validator rejects, or a ``DEFAULT_DEVICE`` id with no matching Device —
    nothing is written in those cases (validation runs before the write).
    """
    definition = get_definition(key)
    if definition.scope is not SettingScope.USER:
        raise ValueError(f"{key} is not a user-scoped setting; cannot store per user.")
    normalized = None if value is None else normalize_setting_value(value, definition)

    from games.models import Device, UserPreferences

    if key == "DEFAULT_DEVICE" and normalized is not None:
        # normalized is an int here (validated by _validate_optional_device_id).
        device_id = cast(int, normalized)
        if not Device.objects.filter(pk=device_id).exists():
            raise ValidationError(f"No device with id {device_id!r}.")

    UserPreferences.get_for_user(user).set_preference_value(key, normalized)


def set_site_setting(key: SettingKey, value: object) -> None:
    """Upsert a site-editable setting's DB value (validated + normalized).

    This DB layer is the site default for SITE and USER keys alike (a USER key's
    row is the shared default under any personal override). Raises for an
    unregistered key, an ``INFRA`` key, or a value the validator rejects —
    nothing is written in those cases.
    """
    definition = get_definition(key)
    if definition.scope is SettingScope.INFRA:
        raise ValueError(f"{key} is infra-scoped (boot-only); cannot store in DB.")
    normalized = normalize_setting_value(value, definition)

    from games.models import SiteSetting

    SiteSetting.objects.update_or_create(key=key, defaults={"value": normalized})


def clear_site_setting(key: SettingKey) -> None:
    """Delete a site-scoped setting's DB row (falls back to env/default)."""
    from games.models import SiteSetting

    SiteSetting.objects.filter(key=key).delete()


__all__ = [
    "ResolvedSetting",
    "SITE_SETTINGS_TTL_SECONDS",
    "ValidationError",
    "clear_cache",
    "clear_site_setting",
    "normalize_setting_value",
    "resolve",
    "resolve_for_user",
    "resolve_for_user_with_origin",
    "resolve_str",
    "resolve_str_for_user",
    "resolve_with_origin",
    "set_site_setting",
    "set_user_preference",
]
