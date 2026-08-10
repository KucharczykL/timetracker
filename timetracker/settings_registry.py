"""Declarative registry — single source of truth for the resolver, introspection,
and the settings-page widgets.

``settings`` is read only inside ``default_factory`` callables, never at import,
so ``settings.py`` can import this module safely.

Registers the 9 settings read via ``config()`` plus the per-user preference keys,
which are *not* read via ``config()`` — no Django setting consumes them at boot;
they resolve through the runtime chain (personal → env → site DB → default).
Excluded on purpose:
``ENV_FILE``/``INI_FILE`` (they *locate* the sources, read via bare ``os.environ``
before the chain exists) and the deprecated ``PROD`` alias.
"""

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Final, cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

from django.conf import settings
from django.core.exceptions import ValidationError

if TYPE_CHECKING:
    from django.db.models import QuerySet

type SettingKey = str  # e.g. "DEFAULT_CURRENCY"
type Cast = Callable[[str], object]  # coercion applied to raw string sources
type DefaultFactory = Callable[[], object]  # lazy default, read at resolve time
type SettingValidator = Callable[[object], object]  # returns normalized or raises
type SettingWriteValidator = Callable[
    [object], None
]  # write-time referential check; raises on failure
type SettingOption = tuple[Any, str]  # e.g. ("cs", "Čeština"), (25, "25")
type QuerysetFactory = Callable[[], "QuerySet[Any]"]  # lazy; imports models when called

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
PAGE_SIZE_OPTIONS: Final[tuple[SettingOption, ...]] = tuple(
    (size, str(size)) for size in PAGE_SIZE_CHOICES
)
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
DURATION_FORMAT_CHOICES: Final[tuple[tuple[str, str], ...]] = (
    ("decimal_hours", "Decimal hours (1.2 h)"),
    ("hours_minutes", "Hours and minutes (1 h 12 m)"),
    ("whole_hours", "Whole hours (1 hour)"),
    ("adaptive", "Adaptive units (3 d 11 h)"),
)
_DURATION_FORMAT_VALUES: Final[frozenset[str]] = frozenset(
    value for value, _label in DURATION_FORMAT_CHOICES
)
DISPLAY_TIME_ZONE_CHOICES: Final[tuple[tuple[str, str], ...]] = tuple(
    (time_zone, time_zone) for time_zone in sorted(available_timezones())
)
SESSION_TIME_ZONE_DISPLAY_CHOICES: Final[tuple[tuple[str, str], ...]] = (
    ("account", "My current time zone"),
    ("own", "The session's own time zone"),
)
_SESSION_TIME_ZONE_DISPLAY_VALUES: Final[frozenset[str]] = frozenset(
    value for value, _label in SESSION_TIME_ZONE_DISPLAY_CHOICES
)


class SettingScope(StrEnum):
    USER = "user"  # per-user override (UserPreferences) above the site default
    SITE = "site"  # runtime-editable via a global SiteSetting DB row
    INFRA = "infra"  # boot-only; never read from the DB


class SettingWidget(StrEnum):
    """Control kind a settings page builds for a user-scoped setting."""

    TEXT = "text"
    SELECT = "select"
    MODEL = "model"


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
    widget: SettingWidget | None = None
    choices: tuple[SettingOption, ...] | None = None
    model_queryset: QuerysetFactory | None = None
    empty_display: str = ""  # label for a MODEL widget's unset/dangling value
    reload_after_save: bool = False
    user_help_text: str = ""
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
        if self.scope is SettingScope.USER and self.widget is None:
            raise ValueError(f"{self.key}: user-scoped settings must declare a widget.")
        if (self.widget is SettingWidget.SELECT) != (self.choices is not None):
            raise ValueError(
                f"{self.key}: a SELECT widget needs choices, and choices need a "
                "SELECT widget."
            )
        if (self.widget is SettingWidget.MODEL) != (self.model_queryset is not None):
            raise ValueError(
                f"{self.key}: a MODEL widget needs model_queryset, and "
                "model_queryset needs a MODEL widget."
            )
        if self.widget is SettingWidget.MODEL and not self.empty_display:
            raise ValueError(f"{self.key}: a MODEL widget needs empty_display.")
        # A restart-only value cannot be fixed by reloading the page.
        if self.reload_after_save and self.apply_timing is not ApplyTiming.LIVE:
            raise ValueError(
                f"{self.key}: reload_after_save requires apply_timing=LIVE."
            )


def _validate_currency(value: object) -> str:
    """Normalize a currency code to a 3-letter uppercase ISO-ish string."""
    text = str(value).strip().upper()
    if len(text) != 3 or not text.isalpha() or not text.isascii():
        raise ValidationError(f"Currency must be three ASCII letters (got {value!r}).")
    return text


def _validate_optional_device_id(value: object) -> int | None:
    """Type-only check for the personal default-device pref. ``None`` means unset;
    existence of the device id is enforced at write time (``change_user_setting``),
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
    default instead of raising)."""
    if value is None:
        return
    from games.models import Device

    if not Device.objects.filter(pk=cast(int, value)).exists():
        raise ValidationError(f"No device with id {value!r}.")


def _device_queryset() -> QuerySet[Any]:
    """Options for the default-device control. The models import happens on call,
    never at module import, so settings.py can import this module."""
    from games.models import Device

    return Device.objects.order_by("name")


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


def _validate_duration_format(value: object) -> str:
    normalized = value.strip().lower() if isinstance(value, str) else value
    if not isinstance(normalized, str) or normalized not in _DURATION_FORMAT_VALUES:
        choices = ", ".join(sorted(_DURATION_FORMAT_VALUES))
        raise ValidationError(
            f"Duration format must be one of {choices} (got {value!r})."
        )
    return normalized


def _validate_session_time_zone_display(value: object) -> str:
    normalized = value.strip().lower() if isinstance(value, str) else value
    if (
        not isinstance(normalized, str)
        or normalized not in _SESSION_TIME_ZONE_DISPLAY_VALUES
    ):
        raise ValidationError(
            f"Session time zone display must be one of account, own (got {value!r})."
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
            widget=SettingWidget.TEXT,
            user_help_text=(
                "A personal value affects only your purchase entry; purchases "
                "saved without user context and FX/reporting continue to use the "
                "site value."
            ),
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
            widget=SettingWidget.MODEL,
            model_queryset=_device_queryset,
            empty_display="No device",
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
            widget=SettingWidget.SELECT,
            choices=LANDING_PAGE_CHOICES,
            # index() redirects an unset landing page to games:list_sessions;
            # that destination is decided there, not by choice order, so it is
            # named explicitly rather than left to fall back to choices[0].
            empty_display="Sessions",
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
            widget=SettingWidget.SELECT,
            choices=PAGE_SIZE_OPTIONS,
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
            widget=SettingWidget.SELECT,
            choices=THEME_CHOICES,
            reload_after_save=True,
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
            widget=SettingWidget.SELECT,
            choices=DISPLAY_TIME_ZONE_CHOICES,
            reload_after_save=True,
        ),
        SettingDefinition(
            "SESSION_TIME_ZONE_DISPLAY",
            scope=SettingScope.USER,
            apply_timing=ApplyTiming.LIVE,
            label="Session time zone display",
            help_text=(
                "Show each session in your current time zone, or in the zone "
                "it was logged in (the zone is labelled when it differs)."
            ),
            default_factory=lambda: "own",
            validator=_validate_session_time_zone_display,
            widget=SettingWidget.SELECT,
            choices=SESSION_TIME_ZONE_DISPLAY_CHOICES,
            reload_after_save=True,
        ),
        SettingDefinition(
            "DATE_FORMAT_LOCALE",
            scope=SettingScope.USER,
            apply_timing=ApplyTiming.LIVE,
            label="Formatting locale",
            help_text="Locale used for date and calendar names, not application copy.",
            default_factory=lambda: settings.LANGUAGE_CODE,
            validator=_validate_date_format_locale,
            widget=SettingWidget.SELECT,
            choices=FORMAT_LOCALE_CHOICES,
            reload_after_save=True,
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
            widget=SettingWidget.SELECT,
            choices=DATETIME_FORMAT_CHOICES,
            reload_after_save=True,
        ),
        SettingDefinition(
            "DURATION_FORMAT",
            scope=SettingScope.USER,
            apply_timing=ApplyTiming.LIVE,
            label="Duration format",
            help_text=(
                "How elapsed playtime is displayed. Every duration also offers "
                "the other formats on hover."
            ),
            default_factory=lambda: "decimal_hours",
            validator=_validate_duration_format,
            widget=SettingWidget.SELECT,
            choices=DURATION_FORMAT_CHOICES,
            reload_after_save=True,
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
