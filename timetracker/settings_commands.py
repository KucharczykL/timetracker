"""Validated mutation boundary for runtime-editable site settings."""

from enum import StrEnum
from typing import TYPE_CHECKING, Any, NamedTuple

if TYPE_CHECKING:
    from games.models import Device, UserLibrary

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


class SettingNamespace(StrEnum):
    """Which mutation surface emitted a settings-committed event: the personal
    settings page or the site-admin settings page. Distinct from SettingScope
    (a *key's* registry classification) and from SettingSource (where a
    resolved *value* came from) — namespace is never derivable from either."""

    USER = "user"
    SITE = "site"
    LIBRARY = "library"


SETTING_NAMESPACE_CHOICES: tuple[tuple[str, str], ...] = (
    ("user", "User"),
    ("site", "Site"),
    ("library", "Library"),
)


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


def _request_display_currency_if_changed(
    *,
    key: SettingKey,
    changed: bool,
    old_effective: object,
    new_effective: object,
    user: Any | None = None,
) -> None:
    if (
        not changed
        or key != "DEFAULT_DISPLAY_CURRENCY"
        or old_effective == new_effective
    ):
        return
    if user is None:
        from games.conversion import request_inheriting_library_conversions

        request_inheriting_library_conversions(str(new_effective))
    else:
        from games.conversion import request_conversion

        request_conversion(user.library, str(new_effective))


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
        old_effective = resolve_fallthrough_uncached(key, skip_db=False).value
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
            mutation = SettingMutation(
                ResolvedSetting(normalized, SettingSource.DATABASE, False),
                operation,
                changed,
                normalized,
                True,
            )
            _request_display_currency_if_changed(
                key=key,
                changed=changed,
                old_effective=old_effective,
                new_effective=mutation.effective.value,
            )
            return mutation

        # CLEAR — never lock-checked.
        changed = stored_present
        if changed:
            SiteSetting.objects.filter(key=key).delete()
        effective = resolve_fallthrough_uncached(key, skip_db=True)
        mutation = SettingMutation(effective, operation, changed, None, False)
        _request_display_currency_if_changed(
            key=key,
            changed=changed,
            old_effective=old_effective,
            new_effective=mutation.effective.value,
        )
        return mutation


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
        row = UserPreferences.objects.filter(user=user).first()  # type: ignore[misc]  # non-creating read
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
        old_effective = (
            stored_raw
            if stored_present
            else resolve_fallthrough_uncached(key, skip_db=False).value
        )

        if operation is SettingOperation.SET:
            normalized = normalize_setting_value(value, definition)
            if definition.write_validator is not None:
                definition.write_validator(normalized)
            changed = (not stored_present) or normalized != stored_raw
            if changed:
                UserPreferences.get_for_user(user).set_preference_value(key, normalized)
            mutation = SettingMutation(
                ResolvedSetting(normalized, SettingSource.USER, False),
                operation,
                changed,
                normalized,
                True,
            )
            _request_display_currency_if_changed(
                key=key,
                changed=changed,
                old_effective=old_effective,
                new_effective=mutation.effective.value,
                user=user,
            )
            return mutation

        # CLEAR
        changed = stored_present
        if changed and row is not None:
            row.set_preference_value(key, None)
        effective = resolve_fallthrough_uncached(key, skip_db=False)._replace(
            locked=False
        )
        mutation = SettingMutation(effective, operation, changed, None, False)
        _request_display_currency_if_changed(
            key=key,
            changed=changed,
            old_effective=old_effective,
            new_effective=mutation.effective.value,
            user=user,
        )
        return mutation


def change_library_default_device(library: UserLibrary, device: Device | None) -> bool:
    """Set a library's optional default Device after enforcing ownership."""
    if device is not None and getattr(device, "library_id", None) != getattr(
        library, "pk", None
    ):
        from django.core.exceptions import ValidationError

        raise ValidationError("Default device must belong to the same library.")

    from games.models import UserLibraryPreferences

    preferences = UserLibraryPreferences.objects.get(library=library)
    return preferences.set_default_device(device)


__all__ = [
    "SETTING_NAMESPACE_CHOICES",
    "SettingLockedError",
    "SettingMutation",
    "SettingNamespace",
    "SettingOperation",
    "change_library_default_device",
    "change_site_setting",
    "change_user_setting",
]
