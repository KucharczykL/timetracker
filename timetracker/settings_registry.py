"""Declarative registry — single source of truth for the resolver, introspection,
and future settings widgets.

``settings`` is read only inside ``default_factory`` callables, never at import,
so ``settings.py`` can import this module safely.

Registers the 9 settings read via ``config()`` plus the per-user preference keys,
which are *not* read via ``config()`` — no Django setting consumes them at boot;
they resolve through the runtime chain (personal → env → site DB → default).
Excluded on purpose:
``ENV_FILE``/``INI_FILE`` (they *locate* the sources, read via bare ``os.environ``
before the chain exists) and the deprecated ``PROD`` alias.
"""

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Callable, Final
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

from django.conf import settings
from django.core.exceptions import ValidationError

type SettingKey = str  # e.g. "DEFAULT_CURRENCY"
type Cast = Callable[[str], object]  # coercion applied to raw string sources
type DefaultFactory = Callable[[], object]  # lazy default, read at resolve time
type SettingValidator = Callable[[object], object]  # returns normalized or raises
type SettingWriteValidator = Callable[[object], None]  # write-time referential check; raises on failure

LANDING_PAGE_CHOICES: Final[tuple[tuple[str, str], ...]] = (
    ("games:list_sessions", "Sessions"),
    ("games:list_games", "Games"),
    ("games:list_purchases", "Purchases"),
    ("games:stats_by_year", "Statistics (this year)"),
)
_LANDING_PAGE_URL_NAMES: Final[frozenset[str]] = frozenset(
    url_name for url_name, _label in LANDING_PAGE_CHOICES
)

DEFAULT_PAGE_SIZE: Final[int] = 25
PAGE_SIZE_CHOICES: Final[tuple[int, ...]] = (10, 25, 50, 100, 500, 1000)
THEME_CHOICES: Final[tuple[tuple[str, str], ...]] = (
    ("system", "System"),
    ("light", "Light"),
    ("dark", "Dark"),
)
_THEME_VALUES: Final[frozenset[str]] = frozenset(value for value, _ in THEME_CHOICES)
FORMAT_LOCALE_CHOICES: Final[tuple[tuple[str, str], ...]] = (
    ("en-us", "English (United States)"),
    ("cs", "Čeština"),
)
_FORMAT_LOCALE_VALUES: Final[frozenset[str]] = frozenset(
    value for value, _ in FORMAT_LOCALE_CHOICES
)
DATETIME_FORMAT_CHOICES: Final[tuple[tuple[str, str], ...]] = (
    ("iso_8601", "ISO 8601"),
    ("dmy_24h", "DD/MM/YYYY, 24-hour"),
    ("mdy_12h", "MM/DD/YYYY, 12-hour"),
)
_DATETIME_FORMAT_VALUES: Final[frozenset[str]] = frozenset(
    value for value, _label in DATETIME_FORMAT_CHOICES
)
DISPLAY_TIME_ZONE_CHOICES: Final[tuple[tuple[str, str], ...]] = tuple(
    (time_zone, time_zone) for time_zone in sorted(available_timezones())
)


class SettingScope(StrEnum):
    USER = "user"  # per-user override (UserPreferences) above the site default
    SITE = "site"  # runtime-editable via a global SiteSetting DB row
    INFRA = "infra"  # boot-only; never read from the DB


class ApplyTiming(StrEnum):
    """When a changed value takes effect."""

    LIVE = "live"  # picked up on the next resolve, no restart
    RESTART = "restart"  # frozen at boot; needs a process restart


class UnregisteredSettingError(KeyError):
    """Raised when a key is not in :data:`SETTINGS_REGISTRY`."""


@dataclass(frozen=True, slots=True)
class SettingDefinition:
    """One registered setting. Frozen: the registry is a shared global every resolve
    reads. ``default_factory`` is lazy; ``env_name`` defaults to ``key``."""

    key: SettingKey
    scope: SettingScope
    apply_timing: ApplyTiming
    label: str
    default_factory: DefaultFactory
    help_text: str = ""
    cast: Cast | None = None
    env_name: str | None = None
    allow_file: bool = False
    validator: SettingValidator | None = None
    widget: str | None = None
    superuser_only: bool = False
    secret: bool = False
    note: str = ""
    write_validator: SettingWriteValidator | None = None

    def __post_init__(self) -> None:
        if self.env_name is None:
            object.__setattr__(self, "env_name", self.key)
        # An INFRA setting is boot-only, so "live" would be a contradiction.
        if (
            self.scope is SettingScope.INFRA
            and self.apply_timing is not ApplyTiming.RESTART
        ):
            raise ValueError(
                f"{self.key}: INFRA settings must be apply_timing=RESTART."
            )


def _validate_currency(value: object) -> str:
    """Normalize a currency code to a 3-letter uppercase ISO-ish string."""
    text = str(value).strip().upper()
    if len(text) != 3 or not text.isalpha() or not text.isascii():
        raise ValidationError(f"Currency must be three ASCII letters (got {value!r}).")
    return text


def _validate_optional_device_id(value: object) -> int | None:
    """Type-only check for the personal default-device pref. ``None`` means unset;
    existence of the device id is enforced at write time (``set_user_preference``),
    not here, so a stale registry read never crashes."""
    if value is None:
        return None
    # bool is an int subclass; reject it so a stray ``True`` isn't stored as 1.
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationError(f"Device must be an integer id (got {value!r}).")
    return value


def _require_existing_device(value: object) -> None:
    """Write-time referential check for DEFAULT_DEVICE: the id must name a live
    Device. Read paths never call this (a dangling stored id degrades to the
    default instead of raising — see #492)."""
    if value is None:
        return
    from games.models import Device

    if not Device.objects.filter(pk=value).exists():
        raise ValidationError(f"No device with id {value!r}.")


def _validate_optional_landing_page(value: object) -> str | None:
    """Accept only stable, argument-free destinations plus current-year stats."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValidationError(f"Landing page must be a string (got {value!r}).")
    if value not in _LANDING_PAGE_URL_NAMES:
        raise ValidationError(f"Unsupported landing page {value!r}.")
    return value


def _validate_page_size(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationError(f"Page size must be an integer (got {value!r}).")
    if value not in PAGE_SIZE_CHOICES:
        choices = ", ".join(str(choice) for choice in PAGE_SIZE_CHOICES)
        raise ValidationError(f"Page size must be one of {choices} (got {value!r}).")
    return value


def _validate_theme(value: object) -> str:
    if not isinstance(value, str) or value not in _THEME_VALUES:
        raise ValidationError(
            f"Theme must be one of system, light, dark (got {value!r})."
        )
    return value


def _validate_display_time_zone(value: object) -> str:
    if not isinstance(value, str):
        raise ValidationError(f"Time zone must be an IANA name (got {value!r}).")
    try:
        return ZoneInfo(value.strip()).key
    except ZoneInfoNotFoundError as error:
        raise ValidationError(f"Unsupported time zone {value!r}.") from error


def _validate_date_format_locale(value: object) -> str:
    normalized = value.strip().lower() if isinstance(value, str) else value
    if not isinstance(normalized, str) or normalized not in _FORMAT_LOCALE_VALUES:
        choices = ", ".join(_FORMAT_LOCALE_VALUES)
        raise ValidationError(
            f"Formatting locale must be one of {choices} (got {value!r})."
        )
    return normalized


def _validate_datetime_format(value: object) -> str:
    normalized = value.strip().lower() if isinstance(value, str) else value
    if not isinstance(normalized, str) or normalized not in _DATETIME_FORMAT_VALUES:
        choices = ", ".join(sorted(_DATETIME_FORMAT_VALUES))
        raise ValidationError(
            f"Date/time format must be one of {choices} (got {value!r})."
        )
    return normalized


def _build_registry() -> dict[SettingKey, SettingDefinition]:
    definitions = [
        SettingDefinition(
            "DEFAULT_CURRENCY",
            scope=SettingScope.USER,
            apply_timing=ApplyTiming.LIVE,
            label="Default currency",
            help_text=(
                "Used for purchase entry by users without a personal value, "
                "purchases saved without user context, and the FX/reporting target."
            ),
            default_factory=lambda: settings.DEFAULT_CURRENCY,
            validator=_validate_currency,
            widget="text",
        ),
        SettingDefinition(
            "DEFAULT_DEVICE",
            scope=SettingScope.USER,
            apply_timing=ApplyTiming.LIVE,
            label="Default device",
            help_text="Device pre-selected when logging a new session.",
            cast=int,
            default_factory=lambda: None,
            validator=_validate_optional_device_id,
            widget="device",
            write_validator=_require_existing_device,
        ),
        SettingDefinition(
            "DEFAULT_LANDING_PAGE",
            scope=SettingScope.USER,
            apply_timing=ApplyTiming.LIVE,
            label="Default landing page",
            help_text="Page shown right after logging in.",
            default_factory=lambda: None,
            validator=_validate_optional_landing_page,
            widget="text",
        ),
        SettingDefinition(
            "DEFAULT_PAGE_SIZE",
            scope=SettingScope.USER,
            apply_timing=ApplyTiming.LIVE,
            label="Default rows per page",
            help_text="Rows shown on list pages when no page size is selected.",
            cast=int,
            default_factory=lambda: DEFAULT_PAGE_SIZE,
            validator=_validate_page_size,
            widget="select",
        ),
        SettingDefinition(
            "THEME",
            scope=SettingScope.USER,
            apply_timing=ApplyTiming.LIVE,
            label="Theme",
            help_text=(
                "Color theme used across browsers signed in to this account. "
                "System follows the operating-system theme."
            ),
            default_factory=lambda: "system",
            validator=_validate_theme,
            widget="select",
        ),
        SettingDefinition(
            "DISPLAY_TIME_ZONE",
            scope=SettingScope.USER,
            apply_timing=ApplyTiming.LIVE,
            label="Time zone",
            help_text=(
                "Time zone used for wall-clock display and datetime form "
                "interpretation."
            ),
            default_factory=lambda: "UTC",
            validator=_validate_display_time_zone,
            widget="select",
        ),
        SettingDefinition(
            "DATE_FORMAT_LOCALE",
            scope=SettingScope.USER,
            apply_timing=ApplyTiming.LIVE,
            label="Formatting locale",
            help_text="Locale used for date and calendar names, not application copy.",
            default_factory=lambda: settings.LANGUAGE_CODE,
            validator=_validate_date_format_locale,
            widget="select",
        ),
        SettingDefinition(
            "DATETIME_FORMAT",
            scope=SettingScope.USER,
            apply_timing=ApplyTiming.LIVE,
            label="Date/time format",
            help_text=(
                "Numeric date order, separators, and 12- or 24-hour clock used "
                "for displayed dates and times."
            ),
            default_factory=lambda: "iso_8601",
            validator=_validate_datetime_format,
            widget="select",
        ),
        SettingDefinition(
            "TZ",
            scope=SettingScope.INFRA,
            apply_timing=ApplyTiming.RESTART,
            label="Time zone",
            help_text="Server time zone (IANA name).",
            default_factory=lambda: settings.TIME_ZONE,
            note=(
                "Display-only. TIME_ZONE is frozen at boot (settings.py reads "
                "config('TZ') during import), so a DB value could never apply. "
                "Change via env/settings.ini + restart."
            ),
        ),
        SettingDefinition(
            "DEBUG",
            scope=SettingScope.INFRA,
            apply_timing=ApplyTiming.RESTART,
            label="Debug mode",
            cast=bool,
            default_factory=lambda: settings.DEBUG,
        ),
        SettingDefinition(
            "SECRET_KEY",
            scope=SettingScope.INFRA,
            apply_timing=ApplyTiming.RESTART,
            label="Secret key",
            allow_file=True,
            secret=True,
            default_factory=lambda: settings.SECRET_KEY,
            note=(
                "required_in_prod is enforced in settings.py, not modeled here; "
                "the resolver may report a DEFAULT origin for a value a prod boot "
                "would actually refuse."
            ),
        ),
        SettingDefinition(
            "APP_URL",
            scope=SettingScope.INFRA,
            apply_timing=ApplyTiming.RESTART,
            label="Application URL",
            default_factory=lambda: settings.APP_URL,
        ),
        SettingDefinition(
            "DEV_LOGIN_PREFILL",
            scope=SettingScope.INFRA,
            apply_timing=ApplyTiming.RESTART,
            label="Dev login prefill",
            default_factory=lambda: settings.DEV_LOGIN_PREFILL,
            note=(
                "Must stay RESTART: read from the boot-frozen settings object and "
                "parsed through a value-keyed @lru_cache in games/dev_login.py, so "
                "going live would only re-log warnings and grow the cache."
            ),
        ),
        SettingDefinition(
            "ALLOWED_HOSTS",
            scope=SettingScope.INFRA,
            apply_timing=ApplyTiming.RESTART,
            label="Allowed hosts",
            cast=list,
            default_factory=lambda: settings.ALLOWED_HOSTS,
            note=(
                "settings.py falls back to hosts derived from APP_URL when the "
                "env value is empty, so the effective value can differ from the "
                "resolver's reported env origin on an empty list."
            ),
        ),
        SettingDefinition(
            "DATA_DIR",
            scope=SettingScope.INFRA,
            apply_timing=ApplyTiming.RESTART,
            label="Data directory",
            cast=Path,
            # DATA_DIR is not a settings attribute; reconstruct it from the DB path.
            default_factory=lambda: Path(settings.DATABASES["default"]["NAME"]).parent,
        ),
        SettingDefinition(
            "HASHED_STATIC",
            scope=SettingScope.INFRA,
            apply_timing=ApplyTiming.RESTART,
            label="Hashed static assets",
            cast=bool,
            default_factory=lambda: settings.HASHED_STATIC,
        ),
    ]
    return {definition.key: definition for definition in definitions}


SETTINGS_REGISTRY: Final[dict[SettingKey, SettingDefinition]] = _build_registry()


def get_definition(key: SettingKey) -> SettingDefinition:
    """Return the :class:`SettingDefinition` for ``key`` or raise."""
    try:
        return SETTINGS_REGISTRY[key]
    except KeyError:
        raise UnregisteredSettingError(key) from None
