"""Declarative registry — single source of truth for the resolver, introspection,
and future settings widgets.

``settings`` is read only inside ``default_factory`` callables, never at import,
so ``settings.py`` can import this module safely.

Registers exactly the 9 settings read via ``config()``. Excluded on purpose:
``ENV_FILE``/``INI_FILE`` (they *locate* the sources, read via bare ``os.environ``
before the chain exists) and the deprecated ``PROD`` alias.
"""

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Callable, Final

from django.conf import settings
from django.core.exceptions import ValidationError

type SettingKey = str  # e.g. "DEFAULT_CURRENCY"
type Cast = Callable[[str], object]  # coercion applied to raw string sources
type DefaultFactory = Callable[[], object]  # lazy default, read at resolve time
type SettingValidator = Callable[[object], object]  # returns normalized or raises


class SettingScope(StrEnum):
    USER = "user"  # no resolver branch yet; wired up in the per-user prefs stage
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


def _build_registry() -> dict[SettingKey, SettingDefinition]:
    definitions = [
        SettingDefinition(
            "DEFAULT_CURRENCY",
            scope=SettingScope.SITE,
            apply_timing=ApplyTiming.LIVE,
            label="Default currency",
            help_text=(
                "Currency assigned to purchases saved without one, and the "
                "target the price-conversion task converts into."
            ),
            default_factory=lambda: settings.DEFAULT_CURRENCY,
            validator=_validate_currency,
            widget="text",
            superuser_only=True,
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
