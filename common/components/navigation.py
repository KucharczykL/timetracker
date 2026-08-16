"""Pure reusable navigation compositions."""

from common.components.core import Child, Node
from common.components.custom_elements import (
    Dropdown,
    DropdownDivider,
    DropdownLinkItem,
    DropdownMenuPanel,
    DropdownPostItem,
)
from common.components.primitives import Button, Div, Li, PlainH4, Span
from common.components.theme import ThemeToggle


def _account_value(label: str, value: Child) -> Node:
    return Li(role="presentation")[
        Div(class_="flex items-center justify-between gap-4 px-4 py-2")[
            Span(class_="text-type-micro-caps uppercase text-body")[label],
            Div(class_="min-w-0 text-right text-type-body text-heading")[value],
        ]
    ]


def AccountMenu(
    *,
    username: str,
    initials: str,
    today_played: Child,
    last_7_played: Child,
    stats_url: str,
    settings_url: str,
    admin_settings_url: str | None,
    theme_disabled: bool,
    logout_url: str,
    csrf_token: str,
    id: str = "account-menu",
) -> Node:
    if not initials.strip():
        raise ValueError("AccountMenu initials must not be empty.")
    trigger_content = Span(aria_hidden="true", class_="text-type-body font-semibold")[
        initials
    ]
    trigger = Button(
        [
            ("type", "button"),
            ("aria-haspopup", "menu"),
            ("aria-label", f"Open account menu for {username}"),
            ("data-account-menu-trigger", ""),
            (
                "class",
                (
                    "inline-flex h-10 w-10 shrink-0 items-center justify-center "
                    "rounded-full border border-default-medium bg-neutral-secondary-medium "
                    "text-heading hover:bg-neutral-tertiary-medium focus:outline-hidden "
                    "focus:ring-2 focus:ring-fg-brand"
                ),
            ),
        ]
    )[trigger_content]
    items: list[Node] = [
        Li(role="presentation", class_="px-4 py-3")[
            PlainH4(class_="text-type-body font-semibold text-heading break-words")[
                username
            ]
        ],
        _account_value("Today", today_played),
        _account_value("Last 7 days", last_7_played),
        DropdownDivider(),
        DropdownLinkItem(stats_url, "Stats"),
        DropdownLinkItem(settings_url, "Settings"),
    ]
    if admin_settings_url is not None:
        items.append(DropdownLinkItem(admin_settings_url, "Admin settings"))
    items.extend(
        [
            DropdownDivider(),
            Li(role="presentation", class_="px-2 py-1")[
                ThemeToggle(instance_key=f"{id}-theme", disabled=theme_disabled)
            ],
            DropdownDivider(),
            DropdownPostItem(logout_url, "Log out", csrf_token=csrf_token),
        ]
    )
    return Dropdown(
        trigger_element=trigger,
        target_element=DropdownMenuPanel(
            items=items,
            aria_label=f"{username} account menu",
            menu_width="w-72 max-w-[calc(100vw-2rem)]",
        ),
        id=id,
        placement="bottom-end",
    )


__all__ = ["AccountMenu"]
