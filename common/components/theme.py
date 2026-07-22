"""Server-rendered theme presenters backed by the shared browser coordinator."""

from common.components.core import Element, Node
from common.components.primitives import Popover, Span, custom_element_builder

_ThemeToggle = custom_element_builder("theme-toggle")
_ThemeSetting = custom_element_builder("theme-setting")


def _icon(
    preference: str,
    *children: Element,
    hidden: bool = False,
) -> Element:
    attributes = [
        ("data-theme-icon", preference),
        ("class", "h-5 w-5"),
        ("viewBox", "0 0 24 24"),
        ("fill", "none"),
        ("stroke", "currentColor"),
        ("stroke-width", "2"),
        ("aria-hidden", "true"),
    ]
    if hidden:
        attributes.append(("hidden", "hidden"))
    return Element("svg", attributes)[*children]


def _theme_icons() -> list[Element]:
    return [
        _icon(
            "system",
            Element("circle", [("cx", "12"), ("cy", "12"), ("r", "8")]),
            Element(
                "path",
                [
                    ("data-theme-system-half", ""),
                    ("d", "M12 4a8 8 0 0 0 0 16V4Z"),
                    ("fill", "currentColor"),
                    ("stroke", "none"),
                ],
            ),
        ),
        _icon(
            "light",
            Element("circle", [("cx", "12"), ("cy", "12"), ("r", "4")]),
            Element(
                "path",
                [
                    (
                        "d",
                        "M12 2v2M12 20v2M4.93 4.93l1.42 1.42M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.42-1.42M17.66 6.34l1.41-1.41",
                    )
                ],
            ),
            hidden=True,
        ),
        _icon(
            "dark",
            Element(
                "path",
                [("d", "M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79Z")],
            ),
            hidden=True,
        ),
    ]


def ThemeToggle() -> Node:
    label = "Theme: System — switch to Light"
    return _ThemeToggle(class_="block")[
        Popover(
            popover_content=Span(data_theme_tooltip="")[label],
            children=_theme_icons(),
            id="theme-toggle-tooltip",
            trigger_label=label,
            wrapped_classes="p-2 text-body-subtle "
            "hover:bg-neutral-tertiary-medium focus:outline-hidden focus:ring-4 "
            "focus:ring-neutral-tertiary-medium rounded-base text-type-body "
            "hover:cursor-pointer",
        )
    ]


def ThemeSetting(control: Node) -> Node:
    """Decorate the canonical Django theme select with coordinator behavior."""
    return _ThemeSetting(class_="block w-full")[control]


__all__ = ["ThemeSetting", "ThemeToggle"]
