"""Server-rendered host and icons for the account-aware theme controller."""

from common.components.core import Media, Node, Safe
from common.components.primitives import Button, custom_element_builder

_ThemeToggle = custom_element_builder("theme-toggle")

_THEME_ICONS = """
<svg data-theme-icon="auto" class="h-5 w-5" viewBox="0 0 24 24" fill="none"
     stroke="currentColor" stroke-width="2" aria-hidden="true">
  <rect x="3" y="4" width="18" height="13" rx="2"/>
  <path d="M8 21h8M12 17v4"/>
</svg>
<svg data-theme-icon="light" class="h-5 w-5" viewBox="0 0 24 24" fill="none"
     stroke="currentColor" stroke-width="2" aria-hidden="true" hidden>
  <circle cx="12" cy="12" r="4"/>
  <path d="M12 2v2M12 20v2M4.93 4.93l1.42 1.42M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.42-1.42M17.66 6.34l1.41-1.41"/>
</svg>
<svg data-theme-icon="dark" class="h-5 w-5" viewBox="0 0 24 24" fill="none"
     stroke="currentColor" stroke-width="2" aria-hidden="true" hidden>
  <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79Z"/>
</svg>
"""


def ThemeToggle(*, api_url: str, csrf: str, cookie_secure: bool) -> Node:
    label = "Theme: Auto — switch to Light"
    return _ThemeToggle(
        api_url=api_url,
        csrf=csrf,
        cookie_secure=cookie_secure,
        class_="block",
    )[
        Button(
            type="button",
            data_theme_toggle="",
            title=label,
            aria_label=label,
            class_="p-2 text-body-subtle hover:bg-neutral-tertiary-medium "
            "focus:outline-hidden focus:ring-4 focus:ring-neutral-tertiary-medium "
            "rounded-base text-type-body hover:cursor-pointer",
        )[Safe(_THEME_ICONS)]
    ].with_media(Media(js=("dist/elements/theme-toggle.js",)))


__all__ = ["ThemeToggle"]
