"""Validated mutation boundary for runtime-editable site settings."""

import logging
import uuid
from enum import StrEnum
from typing import TYPE_CHECKING, Any, NamedTuple, cast
from zoneinfo import ZoneInfo

if TYPE_CHECKING:
    from django.contrib.auth.models import User

    from games.models import Device, UserLibrary
    from games.reads.calendar import CalendarDelta, ZoneName

from games.events.retry import retried_transaction
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

logger = logging.getLogger("games")

#: The one setting whose change is also a command.
CALENDAR_SETTING_KEY: SettingKey = "DISPLAY_TIME_ZONE"


class SettingOperation(StrEnum):
    SET = "set"
    CLEAR = "clear"


class SettingNamespace(StrEnum):
    """Which mutation surface emitted a settings-committed event: personal,
    site-admin, or library preferences. Distinct from SettingScope (a *key's*
    registry classification) and from SettingSource (where a resolved *value*
    came from) — namespace is never derivable from either."""

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
    #: What a display-zone change moved; None for every other key.
    calendar: CalendarDelta | None = None


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


def change_site_setting(
    key: SettingKey, value: object | None, *, actor: User | None = None
) -> SettingMutation:
    """Set or clear a validated site default; return an operation-aware envelope.

    Lock guards SET only — a CLEAR removes the DB row even when a locked source
    (env/file/dotenv/ini) shadows the key, so an operator can drop a stale row
    before dropping the env var. No-op writes touch nothing (no signal, no cache
    invalidation). Effective-after-write is computed without a resolver read-back of
    the just-written layer.

    The display zone is also every inheriting library's calendar, so its
    change appends one command per such library as `actor`, in the same
    transaction as the row."""
    definition = get_definition(key)
    if definition.scope is SettingScope.INFRA:
        raise ValueError(f"{key} is infra-scoped (boot-only); cannot store in DB.")

    if key == CALENDAR_SETTING_KEY:
        if actor is None:
            raise ValueError(
                "A calendar change records who changed it; name the actor."
            )
        libraries = list(_inheriting_libraries())
        #: Minted outside the retried call, so every attempt reuses them.
        idempotency_keys = {library.pk: uuid.uuid4() for library in libraries}
        return _change_site_display_zone(
            value, actor=actor, libraries=libraries, idempotency_keys=idempotency_keys
        )

    from django.db import transaction

    with transaction.atomic():
        return _write_site_setting(key, value)


def _write_site_setting(key: SettingKey, value: object | None) -> SettingMutation:
    """The database half of `change_site_setting`, inside a caller's transaction."""
    definition = get_definition(key)
    operation = SettingOperation.CLEAR if value is None else SettingOperation.SET

    from games.models import SiteSetting

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
    reported ``locked=False``, matching the read endpoint's contract.

    The display zone is also the library's calendar, so its change appends
    the calendar command in the same transaction as the preference row."""
    definition = get_definition(key)
    if definition.scope is not SettingScope.USER:
        raise ValueError(f"{key} is not a user-scoped setting; cannot store per user.")

    if key == CALENDAR_SETTING_KEY:
        from games.events.dispatch import authorize

        owner = cast("User", user)
        authorize(owner, owner.library)
        return _change_user_display_zone(owner, value, idempotency_key=uuid.uuid4())

    from django.db import transaction

    with transaction.atomic():
        return _write_user_setting(user, key, value)


def _write_user_setting(
    user: object, key: SettingKey, value: object | None
) -> SettingMutation:
    """The database half of `change_user_setting`, inside a caller's transaction."""
    definition = get_definition(key)
    operation = SettingOperation.CLEAR if value is None else SettingOperation.SET

    from games.models import USER_PREFERENCE_FIELD_BY_KEY, UserPreferences

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
    effective = resolve_fallthrough_uncached(key, skip_db=False)._replace(locked=False)
    mutation = SettingMutation(effective, operation, changed, None, False)
    _request_display_currency_if_changed(
        key=key,
        changed=changed,
        old_effective=old_effective,
        new_effective=mutation.effective.value,
        user=user,
    )
    return mutation


def _inheriting_libraries():
    """Libraries whose owner states no display zone of their own."""
    from django.db.models import Q

    from games.models import UserLibrary

    return UserLibrary.objects.filter(
        Q(user__preferences__display_time_zone__isnull=True)
        | Q(user__preferences__isnull=True)
    ).order_by("pk")


def _restate_calendar(
    library: UserLibrary,
    *,
    before: ZoneName,
    after: ZoneName,
    actor: User,
    idempotency_key: uuid.UUID,
) -> CalendarDelta | None:
    """Append the calendar command when the effective zone moved.

    The delta is read first: it compares the new zone's day with the
    stored one, which the projector rewrites.
    """
    from games.commands.calendar import SetCalendarDayZone
    from games.events.dispatch import append_command
    from games.reads.calendar import calendar_delta

    if before == after:
        return None
    delta = calendar_delta(library, after)
    append_command(
        SetCalendarDayZone(day_zone=after),
        actor=actor,
        library=library,
        idempotency_key=f"calendar:set_day_zone:{idempotency_key}",
    )
    return delta


def _zone_name(value: object) -> ZoneName:
    return ZoneInfo(str(value)).key


@retried_transaction
def _change_user_display_zone(
    user: User, value: object | None, *, idempotency_key: uuid.UUID
) -> SettingMutation:
    from games.reads.calendar import calendar_day_zone

    library = user.library
    before = calendar_day_zone(library).key
    mutation = _write_user_setting(user, CALENDAR_SETTING_KEY, value)
    delta = _restate_calendar(
        library,
        before=before,
        after=_zone_name(mutation.effective.value),
        actor=user,
        idempotency_key=idempotency_key,
    )
    return mutation._replace(calendar=delta)


@retried_transaction
def _change_site_display_zone(
    value: object | None,
    *,
    actor: User,
    libraries: list[UserLibrary],
    idempotency_keys: dict[uuid.UUID, uuid.UUID],
) -> SettingMutation:
    from games.reads.calendar import calendar_day_zone

    before = {library.pk: calendar_day_zone(library).key for library in libraries}
    mutation = _write_site_setting(CALENDAR_SETTING_KEY, value)
    after = _zone_name(mutation.effective.value)
    total: CalendarDelta | None = None
    for library in libraries:
        delta = _restate_calendar(
            library,
            before=before[library.pk],
            after=after,
            actor=actor,
            idempotency_key=idempotency_keys[library.pk],
        )
        if delta is None:
            continue
        logger.info(
            "Library %s now counts days in %s: %d sessions, %d moved a day, "
            "%d a month, %d a year.",
            library.pk,
            after,
            delta.sessions,
            delta.day_moved,
            delta.month_moved,
            delta.year_moved,
        )
        total = delta if total is None else total + delta
    return mutation._replace(calendar=total)


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
