"""Shared server contract for the account theme cookie mirror."""

from django.conf import settings
from django.http import HttpResponse

from timetracker.settings_resolver import resolve_str_for_user

THEME_COOKIE_NAME = "color-theme"
THEME_MIGRATION_COOKIE_NAME = "color-theme-migrate"
THEME_COOKIE_MAX_AGE = 365 * 24 * 60 * 60


def _cookie_options() -> dict[str, object]:
    return {
        "max_age": THEME_COOKIE_MAX_AGE,
        "path": "/",
        "secure": settings.SESSION_COOKIE_SECURE,
        "httponly": False,
        "samesite": "Lax",
    }


def write_theme_cookies(
    response: HttpResponse,
    theme: str,
    *,
    needs_migration: bool,
) -> None:
    """Mirror ``theme`` and maintain the one-time localStorage migration marker."""
    response.set_cookie(THEME_COOKIE_NAME, theme, **_cookie_options())
    if needs_migration:
        response.set_cookie(THEME_MIGRATION_COOKIE_NAME, "1", **_cookie_options())
    else:
        response.delete_cookie(
            THEME_MIGRATION_COOKIE_NAME,
            path="/",
            samesite="Lax",
        )


def write_login_theme_cookies(response: HttpResponse, user: object) -> None:
    """Write the resolved login theme and mark accounts with no typed value yet."""
    from games.models import UserPreferences

    stored_theme = (
        UserPreferences.objects.filter(user=user)
        .values_list("theme", flat=True)
        .first()
    )
    write_theme_cookies(
        response,
        resolve_str_for_user(user, "THEME"),
        needs_migration=stored_theme is None,
    )


__all__ = [
    "THEME_COOKIE_MAX_AGE",
    "THEME_COOKIE_NAME",
    "THEME_MIGRATION_COOKIE_NAME",
    "write_login_theme_cookies",
    "write_theme_cookies",
]
