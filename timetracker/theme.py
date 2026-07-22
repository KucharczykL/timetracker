"""Shared server contract for the account theme cookie mirror."""

from typing import Any

from django.conf import settings
from django.http import HttpResponse

from timetracker.settings_resolver import resolve_str_for_user

THEME_COOKIE_NAME = "color-theme"
THEME_MIGRATION_COOKIE_NAME = "color-theme-migrate"
THEME_COOKIE_MAX_AGE = 365 * 24 * 60 * 60


def theme_bootstrap_script() -> str:
    """Return the synchronous head script that applies theme before CSS loads."""
    return f"""
(() => {{
    const allowed = new Set(["auto", "light", "dark"]);
    const readCookie = (name) => {{
        const prefix = `${{name}}=`;
        const item = document.cookie.split("; ").find((part) => part.startsWith(prefix));
        return item ? decodeURIComponent(item.slice(prefix.length)) : null;
    }};
    const migration = readCookie("{THEME_MIGRATION_COOKIE_NAME}") === "1";
    const cookieTheme = readCookie("{THEME_COOKIE_NAME}");
    let storedTheme = null;
    try {{
        storedTheme = localStorage.getItem("{THEME_COOKIE_NAME}");
    }} catch (_error) {{
        // Storage can be disabled; cookies/system preference still work.
    }}
    const validCookie = allowed.has(cookieTheme) ? cookieTheme : null;
    const validStored = allowed.has(storedTheme) ? storedTheme : null;
    const preference = migration && validStored
        ? validStored
        : (validCookie ?? validStored ?? "auto");
    const root = document.documentElement;
    root.dataset.themePreference = preference;
    if (migration) root.dataset.themeMigration = "true";
    const systemDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
    root.classList.toggle("dark", preference === "dark" || (preference === "auto" && systemDark));
    if (validCookie && !migration) {{
        try {{ localStorage.setItem("{THEME_COOKIE_NAME}", validCookie); }} catch (_error) {{}}
    }}
}})();
"""


def _set_cookie(response: HttpResponse, name: str, value: str) -> None:
    response.set_cookie(
        name,
        value,
        max_age=THEME_COOKIE_MAX_AGE,
        path="/",
        secure=settings.SESSION_COOKIE_SECURE,
        httponly=False,
        samesite="Lax",
    )


def write_theme_cookies(
    response: HttpResponse,
    theme: str,
    *,
    needs_migration: bool,
) -> None:
    """Mirror ``theme`` and maintain the one-time localStorage migration marker."""
    _set_cookie(response, THEME_COOKIE_NAME, theme)
    if needs_migration:
        _set_cookie(response, THEME_MIGRATION_COOKIE_NAME, "1")
    else:
        response.delete_cookie(
            THEME_MIGRATION_COOKIE_NAME,
            path="/",
            samesite="Lax",
        )


def write_login_theme_cookies(response: HttpResponse, user: Any) -> None:
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
    "theme_bootstrap_script",
    "write_login_theme_cookies",
    "write_theme_cookies",
]
