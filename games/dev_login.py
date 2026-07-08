"""Dev/staging-only login-form prefill (issue: dev login friction).

Parses the ``DEV_LOGIN_PREFILL`` setting ("username:password") into credentials
the login page pre-fills. Empty or malformed => disabled (fails safe), so the
login form renders normally in production.
"""

import logging
from functools import lru_cache

from django.conf import settings

logger = logging.getLogger(__name__)


@lru_cache(maxsize=None)
def _parse(raw: str) -> tuple[str, str] | None:
    """Parse the raw DEV_LOGIN_PREFILL value once per distinct value (so the
    malformed-warning logs once at startup in production, where the value is
    constant)."""
    if not raw:
        return None
    username, separator, password = raw.partition(":")
    if not separator or not username or not password:
        logger.warning(
            "DEV_LOGIN_PREFILL is malformed (%r); expected 'username:password'. "
            "Prefill disabled.",
            raw,
        )
        return None
    return username, password


def prefill_credentials() -> tuple[str, str] | None:
    """Return the ``(username, password)`` to prefill on the login page, or
    ``None`` when ``DEV_LOGIN_PREFILL`` is unset or malformed. Splits on the first
    ``:`` only; the parse is cached per raw value (parsed/logged once at startup)."""
    return _parse(settings.DEV_LOGIN_PREFILL)
