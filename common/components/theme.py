"""Server-rendered theme presenters backed by the shared browser coordinator."""

from common.components.core import Node, randomid
from common.components.primitives import (
    DISABLED_CONTROL_CLASS,
    ICON_BUTTON_SIZE_CLASS,
    Icon,
    Popover,
    Span,
    custom_element_builder,
)

_ThemeToggle = custom_element_builder("theme-toggle")
_ThemeSetting = custom_element_builder("theme-setting")


#: The glyph each preference shows.
_THEME_GLYPHS = {"system": "sun-moon", "light": "sun", "dark": "moon"}


def _theme_icons() -> list[Node]:
    return [
        Icon(
            glyph,
            [
                ("data-theme-icon", preference),
                *([("hidden", "hidden")] if hidden else []),
            ],
            size=ICON_BUTTON_SIZE_CLASS,
            decorative=True,
        )
        for (preference, glyph), hidden in zip(
            _THEME_GLYPHS.items(), (False, True, True), strict=True
        )
    ]


def ThemeToggle(*, instance_key: str, disabled: bool = False) -> Node:
    label = (
        "Theme switching is unavailable on settings pages."
        if disabled
        else "Theme: System — switch to Light"
    )
    return _ThemeToggle(
        disabled="true" if disabled else "false",
        class_="block",
    )[
        Popover(
            popover_content=Span(data_theme_tooltip="")[label],
            children=_theme_icons(),
            id=randomid(seed="theme-tip-", content=instance_key, length=20),
            trigger_label=label,
            trigger_disabled=disabled,
            # The toggle's own icons are the affordance; a reveal glyph beside
            # them would advertise nothing.
            symbol_trigger=True,
            wrapped_classes="p-2 text-body-subtle "
            "hover:bg-neutral-tertiary-medium focus:outline-hidden focus:ring-4 "
            "focus:ring-neutral-tertiary-medium rounded-base text-type-body "
            f"hover:cursor-pointer {DISABLED_CONTROL_CLASS}",
        )
    ]


def ThemeSetting(control: Node) -> Node:
    """Decorate the canonical Django theme select with coordinator behavior."""
    return _ThemeSetting(class_="block w-full")[control]


__all__ = ["ThemeSetting", "ThemeToggle"]
