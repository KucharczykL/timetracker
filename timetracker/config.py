"""
Centralized configuration reading for timetracker.

Every configurable Django setting is resolved through :func:`config`, which
consults several sources in a fixed priority order (highest first):

1. ``NAME__FILE``    — path to a file whose *stripped* contents are the value.
                       Only consulted when the setting opts in with
                       ``allow_file=True``. Intended for Docker/Kubernetes
                       secrets, which are mounted as files rather than env vars.
2. ``NAME``          — a real process environment variable.
3. ``.env`` file     — ``KEY=value`` lines (see the supported syntax below).
4. ``settings.ini``  — the ``[timetracker]`` section, parsed with
                       :mod:`configparser`.
5. ``default``       — the in-code fallback passed to :func:`config`.

If no source supplies a value and no ``default`` is given, an
:class:`~django.core.exceptions.ImproperlyConfigured` error is raised.

``.env`` syntax supported:

- ``KEY=value`` and ``export KEY=value``
- blank lines and ``#`` full-line comments
- single- or double-quoted values (the surrounding quotes are stripped); a
  ``#`` inside quotes is treated literally
- an inline ``# comment`` after an *unquoted* value

Deliberately NOT supported (documented limits, not bugs):

- variable interpolation (``${OTHER}``)
- multiline values

File locations default to ``.env`` and ``settings.ini`` next to the project
root and can be overridden with the ``ENV_FILE`` / ``INI_FILE`` environment
variables. Missing files are silently ignored so env-only deployments are
unaffected.
"""

import os
from configparser import ConfigParser
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent

# Sentinel distinguishing "no default supplied" from an explicit ``None``.
NOT_SET: Any = object()

INI_SECTION = "timetracker"

_env_file_cache: dict[str, str] | None = None
_ini_file_cache: dict[str, str] | None = None


def _unquote(value: str) -> str:
    """Strip surrounding quotes, or an inline comment from an unquoted value."""
    if not value:
        return value
    quote = value[0]
    if quote in "\"'":
        closing = value.find(quote, 1)
        if closing != -1:
            return value[1:closing]
        # Opening quote with no match: drop it and keep the rest verbatim.
        return value[1:]
    comment_index = value.find("#")
    if comment_index != -1:
        value = value[:comment_index]
    return value.strip()


def _parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        if "=" not in line:
            continue
        name, _, value = line.partition("=")
        name = name.strip()
        if not name:
            continue
        values[name] = _unquote(value.strip())
    return values


def _load_env_file() -> dict[str, str]:
    global _env_file_cache
    if _env_file_cache is None:
        path = Path(os.environ.get("ENV_FILE", BASE_DIR / ".env"))
        _env_file_cache = _parse_env_file(path) if path.is_file() else {}
    return _env_file_cache


def _load_ini_file() -> dict[str, str]:
    global _ini_file_cache
    if _ini_file_cache is None:
        path = Path(os.environ.get("INI_FILE", BASE_DIR / "settings.ini"))
        if path.is_file():
            parser = ConfigParser()
            # Preserve key case; ConfigParser lowercases option names by default.
            parser.optionxform = str  # type: ignore[assignment, method-assign]
            parser.read(path)
            _ini_file_cache = (
                dict(parser[INI_SECTION]) if parser.has_section(INI_SECTION) else {}
            )
        else:
            _ini_file_cache = {}
    return _ini_file_cache


def derive_hosts_and_origins(
    app_url: str,
) -> tuple[list[str], list[str]]:
    """Derive ALLOWED_HOSTS and CSRF_TRUSTED_ORIGINS from an APP_URL value.

    ``app_url`` may be a single full URL or a comma-separated list of full URLs.
    Returns ``(allowed_hosts, csrf_trusted_origins)``.
    """
    parsed_urls = [urlparse(raw_url.strip()) for raw_url in app_url.split(",")]
    allowed_hosts = [parsed_url.hostname for parsed_url in parsed_urls]
    csrf_trusted_origins = [
        f"{parsed_url.scheme}://{parsed_url.netloc}" for parsed_url in parsed_urls
    ]
    return allowed_hosts, csrf_trusted_origins


def reset_caches() -> None:
    """Clear parsed-file caches. Intended for use in tests."""
    global _env_file_cache, _ini_file_cache
    _env_file_cache = None
    _ini_file_cache = None


def _cast_value(value: str, cast: Callable[[str], Any] | None) -> Any:
    if cast is None:
        return value
    if cast is bool:
        return value.strip().lower() in {"true", "1", "yes", "on"}
    if cast is list:
        return [item.strip() for item in value.split(",") if item.strip()]
    return cast(value)


def _resolve_raw(name: str, allow_file: bool) -> str | None:
    """Return the first raw string from the source chain, or ``None``."""
    if allow_file:
        file_pointer = os.environ.get(f"{name}__FILE")
        if file_pointer:
            return Path(file_pointer).read_text().strip()
    if name in os.environ:
        return os.environ[name]
    env_file = _load_env_file()
    if name in env_file:
        return env_file[name]
    ini_file = _load_ini_file()
    if name in ini_file:
        return ini_file[name]
    return None


def _debug_enabled() -> bool:
    """Whether the app runs in DEBUG mode, mirroring ``settings.DEBUG``.

    Defaults to on for local development; turned off by ``DEBUG=false`` or the
    deprecated ``PROD`` env var. Used to decide whether ``required_in_prod``
    settings may fall back to a development default.
    """
    raw = _resolve_raw("DEBUG", allow_file=False)
    if raw is not None:
        return _cast_value(raw, bool)
    return not bool(os.environ.get("PROD"))


def config(
    name: str,
    *,
    default: Any = NOT_SET,
    cast: Callable[[str], Any] | None = None,
    allow_file: bool = False,
    required_in_prod: bool = False,
) -> Any:
    """Resolve a configuration value from the source chain.

    Args:
        name: The setting / environment variable name.
        default: Fallback when no source provides a value. If omitted, a
            missing value raises ``ImproperlyConfigured``.
        cast: Coercion applied to string values — ``bool``, ``list``, ``int``,
            ``Path``, or any callable taking a string. Defaults are returned
            untouched.
        allow_file: Whether to honor a ``NAME__FILE`` secret pointer.
        required_in_prod: When ``True``, a missing value raises in production
            (DEBUG off) even if a ``default`` is given, so insecure development
            defaults never leak into a deployment.
    """
    raw = _resolve_raw(name, allow_file=allow_file)
    if raw is None:
        if required_in_prod and not _debug_enabled():
            raise ImproperlyConfigured(
                f"{name} must be set in production (DEBUG is off)."
            )
        if default is NOT_SET:
            raise ImproperlyConfigured(f"Required setting {name} is not configured.")
        return default
    return _cast_value(raw, cast)
