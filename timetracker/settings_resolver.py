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


def clear_cache() -> None:
    """Drop the cached SiteSetting snapshot (next resolve re-reads the DB)."""
    global _snapshot, _snapshot_at
    with _cache_lock:
        _snapshot = None
        _snapshot_at = 0.0


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

    if definition.scope is SettingScope.SITE:
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


def set_site_setting(key: SettingKey, value: object) -> None:
    """Upsert a site-scoped setting's DB value (validated + normalized).

    Raises for an unregistered key, a non-``SITE`` key, or a value the
    definition's validator rejects — nothing is written in those cases.
    """
    definition = get_definition(key)
    if definition.scope is not SettingScope.SITE:
        raise ValueError(f"{key} is not a site-scoped setting; cannot store in DB.")
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
    "resolve_str",
    "resolve_with_origin",
    "set_site_setting",
]
