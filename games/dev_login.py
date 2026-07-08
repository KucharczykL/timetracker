"""Dev/staging-only login-form prefill (issue: dev login friction).

Parses the ``DEV_LOGIN_PREFILL`` setting ("username:password") into credentials
the login page pre-fills. Empty or malformed => disabled (fails safe), so the
login form renders normally in production.
"""

import logging

from django.conf import settings

logger = logging.getLogger(__name__)


def prefill_credentials() -> tuple[str, str] | None:
    """Return the ``(username, password)`` to prefill, or ``None`` when the
    ``DEV_LOGIN_PREFILL`` setting is unset or malformed. Splits on the first
    ``:`` only, so a colon in the password is preserved."""
    raw = settings.DEV_LOGIN_PREFILL
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
