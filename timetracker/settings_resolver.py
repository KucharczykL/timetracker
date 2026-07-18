"""Layered, origin-aware resolution of registered settings.

Precedence (highest first)::

    env / .env / settings.ini   → locked (config source chain, boot-frozen)
    SiteSetting (DB)            → runtime-editable, site-scoped only
    registry default_factory    → the in-code / boot-frozen fallback

``resolve_with_origin(key)`` returns ``(value, source, locked)``. Every layer is
coerced through the registry's ``cast`` and ``validator`` so the three
``DEFAULT_CURRENCY`` consumption sites (and any future typed SITE key) see one
canonical value — a DB-stored ``"eur"`` resolves identically to an env ``EUR``.

**Laziness:** nothing here runs at ``settings.py`` import time. The database is
touched only inside ``resolve``/write helpers, and the ``SiteSetting`` model is
imported lazily inside them, so importing this module never triggers the app
registry or a query.

**Caching:** only the ``SiteSetting`` table is cached — one query snapshots every
key, held for :data:`SITE_SETTINGS_TTL_SECONDS`. The env and default layers are
recomputed each call (cheap, and this keeps ``override_settings`` and dynamic
defaults live). The SQLite read happens *outside* the lock, so a slow/locked DB
never serializes every worker thread for the connection timeout.

**Invalidation:** ``games.signals`` clears the cache on ``SiteSetting`` commit
via ``transaction.on_commit``. Across processes (the gunicorn web worker and the
separate django-q qcluster) values converge within the TTL. A raw
``QuerySet.update()`` bypasses signals and is invisible until the TTL lapses;
write through :func:`set_site_setting` or an instance ``.save()`` for immediate
same-process invalidation.

**Sync only:** ``resolve`` issues a synchronous ORM query on a cold cache. All
current callers are sync; an async caller must wrap it in ``sync_to_async``.
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
    """Coerce ``value`` through the definition's cast + validator.

    ``cast`` only runs on strings (raw sources); a DB JSON value that is already
    the target type passes through cast untouched but is still validated. Shared
    by the resolver and the admin form so both write/read paths normalize alike.
    """
    if isinstance(value, str):
        value = cast_value(value, definition.cast)
    if definition.validator is not None:
        value = definition.validator(value)
    return value


def _load_snapshot() -> dict[str, object]:
    """Query all SiteSetting rows into a {key: value} map.

    Raises on any DB error; the caller (``_site_settings``) decides how to treat
    a missing table.
    """
    from games.models import SiteSetting

    return dict(SiteSetting.objects.values_list("key", "value"))


def _site_settings() -> dict[str, object]:
    """Return the cached SiteSetting snapshot, refreshing past the TTL.

    The DB read runs outside the lock; the lock only guards the swap.
    """
    global _snapshot, _snapshot_at
    now = time.monotonic()
    snapshot = _snapshot
    if snapshot is not None and (now - _snapshot_at) < SITE_SETTINGS_TTL_SECONDS:
        return snapshot
    try:
        fresh = _load_snapshot()
    except (OperationalError, ProgrammingError) as error:
        # Degrade to "no site overrides" on any DB read failure — a missing table
        # (fresh/mid-migration DB) but also a transient lock / I/O fault. The
        # failure is NOT cached, so a working read repopulates immediately and a
        # momentary lock self-heals rather than crashing every resolve.
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
    """Resolved value of ``key`` as a ``str`` (narrowing helper for call sites).

    Raises ``TypeError`` for a non-string setting rather than silently coercing a
    bool/list/Path into a misleading string (``"True"``, ``"['a']"``).
    """
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
