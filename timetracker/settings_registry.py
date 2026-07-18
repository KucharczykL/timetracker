"""Declarative registry of every runtime-inspectable setting.

This is the single source of truth for the layered resolver
(:mod:`timetracker.settings_resolver`), the future introspection API, and the
future settings-panel widgets. Each :class:`SettingDefinition` names a setting's
scope, how a change takes effect (``apply_timing``), its coercion/validation, and
display metadata.

**No database access and no ``django.conf.settings`` *attribute* access happens
at import time** — the boot-frozen ``settings`` object is read only lazily inside
each ``default_factory`` callable, so importing this module during
``settings.py`` evaluation is safe.

Only the **9 settings currently read via** :func:`timetracker.config.config` are
registered. The meta-knobs ``ENV_FILE`` / ``INI_FILE`` are intentionally absent:
they *locate* the config sources (``config.py`` reads them via bare
``os.environ`` before the source chain exists), so they have no place *in* the
chain and their origin is definitionally env-only. The deprecated ``PROD`` alias
(a stand-in for ``DEBUG=false``, slated for removal) is likewise excluded so the
panel never legitimizes it.
"""

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
    """Who owns a setting and where its DB layer (if any) lives.

    ``USER`` is declared now for the per-user-preferences stage; no user-scoped
    settings exist yet. ``SITE`` settings gain a global ``SiteSetting`` DB layer
    (runtime-editable). ``INFRA`` settings are boot-only and never read from the
    DB — the panel shows them read-only.
    """

    USER = "user"
    SITE = "site"
    INFRA = "infra"


class ApplyTiming(StrEnum):
    """When a changed value takes effect."""

    LIVE = "live"  # picked up on the next resolve, no restart
    RESTART = "restart"  # frozen at boot; needs a process restart


class UnregisteredSettingError(KeyError):
    """Raised when a key is not in :data:`SETTINGS_REGISTRY`."""


class SettingDefinition:
    """One registered setting. Immutable; construct only in the registry below."""

    __slots__ = (
        "key",
        "scope",
        "apply_timing",
        "label",
        "help_text",
        "cast",
        "default_factory",
        "env_name",
        "allow_file",
        "validator",
        "widget",
        "superuser_only",
        "secret",
        "note",
    )

    def __init__(
        self,
        key: SettingKey,
        *,
        scope: SettingScope,
        apply_timing: ApplyTiming,
        label: str,
        help_text: str = "",
        cast: Cast | None = None,
        default_factory: DefaultFactory,
        env_name: str | None = None,
        allow_file: bool = False,
        validator: SettingValidator | None = None,
        widget: str | None = None,
        superuser_only: bool = False,
        secret: bool = False,
        note: str = "",
    ) -> None:
        self.key = key
        self.scope = scope
        self.apply_timing = apply_timing
        self.label = label
        self.help_text = help_text
        self.cast = cast
        # Lazy so no settings attribute is read at import; evaluated per resolve.
        self.default_factory = default_factory
        self.env_name = env_name or key
        self.allow_file = allow_file
        self.validator = validator
        self.widget = widget
        self.superuser_only = superuser_only
        self.secret = secret
        self.note = note


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
