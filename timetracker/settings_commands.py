"""Validated mutation boundary for runtime-editable site settings."""

from enum import StrEnum
from typing import NamedTuple

from timetracker.config import (
    LOCKED_SOURCES,
    ResolvedSetting,
    SettingSource,
    resolve_raw_with_source,
)
from timetracker.settings_registry import (
    SettingKey,
    SettingScope,
    get_definition,
)
from timetracker.settings_resolver import (
    normalize_setting_value,
    resolve_fallthrough_uncached,
)


class SettingOperation(StrEnum):
    SET = "set"
    CLEAR = "clear"


class SettingMutation(NamedTuple):
    effective: ResolvedSetting
    operation: SettingOperation
    changed: bool
    stored: object | None
    stored_present: bool


class SettingLockedError(Exception):
    """Raised when boot configuration owns a requested site setting."""

    key: SettingKey
    source: SettingSource

    def __init__(self, key: SettingKey, source: SettingSource) -> None:
        self.key = key
        self.source = source
        super().__init__(f"{key} is locked by {source.value}.")


def change_site_setting(key: SettingKey, value: object | None) -> SettingMutation:
    """Set or clear a validated site default; return an operation-aware envelope.

    Lock guards SET only — a CLEAR removes the DB row even when a locked source
    (env/file/dotenv/ini) shadows the key, so an operator can drop a stale row
    before dropping the env var. No-op writes touch nothing (no signal, no cache
    invalidation). Effective-after-write is computed without a resolver read-back of
    the just-written layer."""
    definition = get_definition(key)
    if definition.scope is SettingScope.INFRA:
        raise ValueError(f"{key} is infra-scoped (boot-only); cannot store in DB.")

    operation = SettingOperation.CLEAR if value is None else SettingOperation.SET

    from django.db import transaction

    from games.models import SiteSetting

    with transaction.atomic():
        row = SiteSetting.objects.filter(key=key).first()
        stored_present = row is not None
        stored_raw = row.value if row is not None else None

        if operation is SettingOperation.SET:
            raw = resolve_raw_with_source(
                definition.env_name or definition.key,
                allow_file=definition.allow_file,
            )
            if raw is not None and raw.source in LOCKED_SOURCES:
                raise SettingLockedError(key, raw.source)

            normalized = normalize_setting_value(value, definition)
            if definition.write_validator is not None:
                definition.write_validator(normalized)

            changed = (not stored_present) or normalized != stored_raw
            if changed:
                SiteSetting.objects.update_or_create(
                    key=key, defaults={"value": normalized}
                )
            return SettingMutation(
                ResolvedSetting(normalized, SettingSource.DATABASE, False),
                operation,
                changed,
                normalized,
                True,
            )

        # CLEAR — never lock-checked.
        changed = stored_present
        if changed:
            SiteSetting.objects.filter(key=key).delete()
        effective = resolve_fallthrough_uncached(key, skip_db=True)
        return SettingMutation(effective, operation, changed, None, False)


def change_user_setting(
    user: object, key: SettingKey, value: object | None
) -> SettingMutation:
    """Set or clear a user-scoped preference; return an operation-aware envelope.

    Personal overrides are never locked (a user may always override, even over env),
    so there is no lock branch. No-op writes touch nothing. User effective is always
    reported ``locked=False``, matching the read endpoint's contract."""
    definition = get_definition(key)
    if definition.scope is not SettingScope.USER:
        raise ValueError(f"{key} is not a user-scoped setting; cannot store per user.")

    operation = SettingOperation.CLEAR if value is None else SettingOperation.SET

    from django.db import transaction

    from games.models import USER_PREFERENCE_FIELD_BY_KEY, UserPreferences

    with transaction.atomic():
        row = UserPreferences.objects.filter(user=user).first()  # non-creating read
        field = USER_PREFERENCE_FIELD_BY_KEY.get(key)
        if row is None:
            stored_present, stored_raw = False, None
        elif field is not None:
            stored_raw = getattr(row, field)
            stored_present = stored_raw is not None
        else:
            bag = row.extra_preferences or {}
            stored_present = key in bag
            stored_raw = bag.get(key)

        if operation is SettingOperation.SET:
            normalized = normalize_setting_value(value, definition)
            if definition.write_validator is not None:
                definition.write_validator(normalized)
            changed = (not stored_present) or normalized != stored_raw
            if changed:
                UserPreferences.get_for_user(user).set_preference_value(key, normalized)
            return SettingMutation(
                ResolvedSetting(normalized, SettingSource.USER, False),
                operation,
                changed,
                normalized,
                True,
            )

        # CLEAR
        changed = stored_present
        if changed and row is not None:
            row.set_preference_value(key, None)
        effective = resolve_fallthrough_uncached(key, skip_db=False)._replace(
            locked=False
        )
        return SettingMutation(effective, operation, changed, None, False)


__all__ = [
    "SettingLockedError",
    "SettingMutation",
    "SettingOperation",
    "change_site_setting",
    "change_user_setting",
]
