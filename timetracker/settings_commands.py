"""Validated mutation boundary for runtime-editable site settings."""

from enum import StrEnum
from typing import NamedTuple, cast

from django.core.exceptions import ValidationError

from timetracker.config import (
    LOCKED_SOURCES,
    ResolvedSetting,
    SettingSource,
)
from timetracker.settings_registry import (
    SettingKey,
    SettingScope,
    get_definition,
)
from timetracker.settings_resolver import (
    normalize_setting_value,
    resolve_with_origin,
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


def change_site_setting(
    key: SettingKey,
    value: object | None,
) -> ResolvedSetting:
    """Set or clear a validated site default and return its immediate result."""
    definition = get_definition(key)
    if definition.scope is SettingScope.INFRA:
        raise ValueError(f"{key} is infra-scoped (boot-only); cannot store in DB.")

    current = resolve_with_origin(key)
    if current.source in LOCKED_SOURCES:
        raise SettingLockedError(key, current.source)

    normalized = None if value is None else normalize_setting_value(value, definition)

    from games.models import Device, SiteSetting

    if key == "DEFAULT_DEVICE" and normalized is not None:
        device_id = cast(int, normalized)
        if not Device.objects.filter(pk=device_id).exists():
            raise ValidationError(f"No device with id {device_id!r}.")

    if normalized is None:
        SiteSetting.objects.filter(key=key).delete()
        return ResolvedSetting(
            definition.default_factory(),
            SettingSource.DEFAULT,
            False,
        )

    SiteSetting.objects.update_or_create(
        key=key,
        defaults={"value": normalized},
    )
    return ResolvedSetting(normalized, SettingSource.DATABASE, False)


__all__ = [
    "SettingLockedError",
    "SettingMutation",
    "SettingOperation",
    "change_site_setting",
]
