"""Domain components for games / purchases / sessions."""

from typing import Any

from django.template.defaultfilters import floatformat
from django.urls import reverse
from django.utils.safestring import SafeText, mark_safe

from common.components.core import Component, HTMLTag
from common.components.primitives import (
    A,
    Div,
    Icon,
    Popover,
    PopoverTruncated,
    Span,
)
from games.models import Game, Purchase, Session


def GameLink(
    game_id: int,
    name: str = "",
    children: list[HTMLTag] | HTMLTag | None = None,
) -> SafeText:
    """Link to a game's detail page. Uses children (slot) if provided, otherwise name."""
    from django.urls import reverse

    children = children or []
    display = children if children else [name]
    link = reverse("games:view_game", args=[game_id])

    return Span(
        attributes=[("class", "truncate-container")],
        children=[
            Component(
                tag_name="a",
                attributes=[
                    ("href", link),
                    ("class", "underline decoration-slate-500 sm:decoration-2"),
                ],
                children=display if isinstance(display, list) else [display],
            ),
        ],
    )


_STATUS_COLORS = {
    "u": "bg-gray-500",
    "p": "bg-orange-400",
    "f": "bg-green-500",
    "a": "bg-red-500",
    "r": "bg-purple-500",
}


def GameStatus(
    children: list[HTMLTag] | HTMLTag | None = None,
    status: str = "u",
    display: str = "",
    class_: str = "",
) -> SafeText:
    """Colored status dot with label. Status codes: u/p/f/a/r."""
    children = children or []
    outer_class = (
        f"{'flex' if display == 'flex' else 'inline-flex'} "
        "gap-2 items-center align-middle"
    )
    if class_:
        outer_class += f" {class_}"
    dot_color = _STATUS_COLORS.get(status, _STATUS_COLORS["u"])

    dot = Span(
        attributes=[("class", f"rounded-xl w-3 h-3 {dot_color}")],
        children=["\xa0"],
    )

    return Span(
        attributes=[("class", outer_class)],
        children=[dot] + (children if isinstance(children, list) else [children]),
    )


def PriceConverted(
    children: list[HTMLTag] | HTMLTag | None = None,
) -> SafeText:
    """Wrap content in a span that indicates the price was converted."""
    children = children or []
    return Span(
        attributes=[
            ("title", "Price is a result of conversion and rounding."),
            ("class", "decoration-dotted underline"),
        ],
        children=children if isinstance(children, list) else [children],
    )


def LinkedPurchase(purchase: Purchase) -> SafeText:
    link = reverse("games:view_purchase", args=[int(purchase.id)])
    link_content = ""
    popover_content = ""
    game_count = purchase.games.count()
    popover_if_not_truncated = False
    if game_count == 1:
        link_content += purchase.games.first().name
        popover_content = link_content
    if game_count > 1:
        if purchase.name:
            link_content += f"{purchase.name}"
            popover_content += f"<h1>{purchase.name}</h1><br>"
        else:
            link_content += f"{game_count} games"
            popover_if_not_truncated = True
        popover_content += f"""
        <ul class="list-disc list-inside">
            {"".join(f"<li>{game.name}</li>" for game in purchase.games.all())}
        </ul>
        """
    icon = (
        (purchase.platform.icon if purchase.platform else "unspecified")
        if game_count == 1
        else "unspecified"
    )
    if link_content == "":
        raise ValueError("link_content is empty!!")
    a_content = Div(
        [("class", "inline-flex gap-2 items-center")],
        [
            Icon(
                icon,
                [("title", "Multiple")],
            ),
            PopoverTruncated(
                input_string=link_content,
                popover_content=mark_safe(popover_content),
                popover_if_not_truncated=popover_if_not_truncated,
            ),
        ],
    )
    return A(href=link, children=[a_content])


def NameWithIcon(
    name: str = "",
    game: Game | None = None,
    session: Session | None = None,
    linkify: bool = True,
    emulated: bool = False,
) -> SafeText:
    _name, platform, final_emulated, create_link, link = _resolve_name_with_icon(
        name, game, session, linkify
    )

    content = Div(
        [("class", "inline-flex gap-2 items-center")],
        [
            Icon(
                platform.icon,
                [("title", platform.name)],
            )
            if platform
            else "",
            Icon("emulated", [("title", "Emulated")]) if final_emulated else "",
            PopoverTruncated(_name),
        ],
    )

    return (
        A(
            href=link,
            children=[content],
        )
        if create_link
        else content
    )


def _resolve_name_with_icon(
    name: str,
    game: Game | None,
    session: Session | None,
    linkify: bool,
) -> tuple[str, Any, bool, bool, str]:
    create_link = False
    link = ""
    platform = None
    final_emulated = False

    if session is not None:
        game = session.game
        platform = game.platform
        final_emulated = session.emulated
        if linkify:
            create_link = True
            link = reverse("games:view_game", args=[int(game.pk)])
    elif game is not None:
        platform = game.platform
        if linkify:
            create_link = True
            link = reverse("games:view_game", args=[int(game.pk)])

    _name = name or (game.name if game else "")

    return _name, platform, final_emulated, create_link, link


def PurchasePrice(purchase) -> SafeText:
    return Popover(
        popover_content=f"{floatformat(purchase.price)} {purchase.price_currency}",
        wrapped_content=f"{floatformat(purchase.converted_price)} {purchase.converted_currency}",
        wrapped_classes="underline decoration-dotted",
    )


def GameStatusSelector(game, game_statuses, csrf_token: str) -> SafeText:
    """Alpine.js dropdown to change a game's status."""
    options_html = "\n".join(
        f"<template x-if=\"status == '{value}'\">"
        f"{GameStatus(status=value, children=[label], display='flex')}"
        f"</template>"
        for value, label in game_statuses
    )
    list_items = "\n".join(
        f"<li><a href=\"#\" @click.prevent.stop=\"setStatus('{value}', '{label}'); open = false;\" "
        f'class="block px-4 py-2 dark:hover:text-white dark:hover:bg-gray-700 '
        f'dark:focus:ring-blue-500 dark:focus:text-white rounded-sm no-underline! border-0!" '
        f":class=\"{{'font-bold': status === '{value}'}}\">"
        f"{GameStatus(status=value, children=[label], display='flex', class_='text-slate-300')}"
        f"</a></li>"
        for value, label in game_statuses
    )

    return mark_safe(f"""
<div class="flex gap-2 items-center"
     x-data="{{
         status: '{game.status}',
         status_display: '{game.get_status_display()}',
         open: false,
         saving: false,
         setStatus(newStatus, newStatusDisplay) {{
             this.status = newStatus;
             this.status_display = newStatusDisplay;
             this.saving = true;
             fetchWithHtmxTriggers(`/api/games/{game.id}/status`, {{
                 method: 'PATCH',
                 headers: {{
                     'Content-Type': 'application/json',
                     'X-CSRFToken': '{csrf_token}'
                 }},
                 body: JSON.stringify({{ status: newStatus }})
             }})
             .then(() => {{
                 document.body.dispatchEvent(new CustomEvent('status-changed'));
             }})
             .catch(() => {{
                 console.error('Failed to update status');
             }})
             .finally(() => this.saving = false);
         }}
     }}">
    {_dropdown_button_html(options_html, list_items)}
</div>
""")


def SessionDeviceSelector(session, session_devices, csrf_token: str) -> SafeText:
    """Alpine.js dropdown to change a session's device."""
    device_id = session.device_id or "null"
    device_name = (session.device.name if session.device else "Unknown").replace(
        "'", "\\'"
    )

    list_items = "\n".join(
        f'<li><a href="#" @click.prevent.stop="setDevice({d.id}, \'{d.name.replace(chr(39), chr(92) + chr(39))}\'); open = false;" '
        f'class="block px-4 py-2 dark:hover:text-white dark:hover:bg-gray-700 '
        f'dark:focus:ring-blue-500 dark:focus:text-white rounded-sm no-underline! border-0!" '
        f":class=\"{{'font-bold': deviceId === {d.id}}}\">{d.name}</a></li>"
        for d in session_devices
    )

    return mark_safe(f"""
<div class="flex gap-2 items-center"
     x-data="{{
         originalDeviceId: {device_id},
         originalDeviceName: '{device_name}',
         deviceId: {device_id},
         deviceName: '{device_name}',
         open: false,
         saving: false,
         setDevice(newDeviceId, newDeviceName) {{
               this.deviceId = newDeviceId;
               this.deviceName = newDeviceName;
               this.saving = true;
                fetchWithHtmxTriggers(`/api/session/{session.id}/device`, {{
                    method: 'PATCH',
                    headers: {{
                        'Content-Type': 'application/json',
                        'X-CSRFToken': '{csrf_token}'
                    }},
                    body: JSON.stringify({{ device_id: newDeviceId }})
                }})
               .then((res) => {{
                   document.body.dispatchEvent(new CustomEvent('device-changed'));
               }})
               .catch(() => {{
                   this.deviceName = this.originalDeviceName;
                   this.deviceId = this.originalDeviceId;
                   console.error('Failed to update device');
               }})
               .finally(() => this.saving = false);
          }}
     }}">
    {
        _dropdown_button_html(
            '<span x-text="deviceName"></span>' + str(Icon("arrowdown")), list_items
        )
    }
</div>
""")


def _dropdown_button_html(button_content: str, list_items: str) -> str:
    """Shared dropdown button + list structure for Alpine.js selectors."""
    return (
        '<div class="inline-flex rounded-md shadow-2xs" role="group" @click.outside="open = false">'
        '<button type="button" @click="open = !open" '
        'class="relative px-4 py-2 text-sm font-medium bg-white border border-gray-200 '
        "rounded-lg hover:bg-gray-100 hover:text-blue-700 focus:z-10 focus:ring-2 "
        "focus:ring-blue-700 focus:text-blue-700 dark:bg-gray-800 dark:border-gray-700 "
        "dark:hover:text-white dark:hover:bg-gray-700 dark:focus:ring-blue-500 "
        'dark:focus:text-white align-middle hover:cursor-pointer">'
        f'<span class="flex flex-row gap-4 justify-between items-center">{button_content}</span>'
        '<div class="absolute top-[105%] left-0 w-full whitespace-nowrap z-10 text-sm '
        "font-medium bg-gray-800/20 backdrop-blur-lg rounded-md rounded-t-none border "
        'border-gray-200 dark:border-gray-700" x-show="open" style="display: none;">'
        '<ul class="[&_li:first-of-type_a]:rounded-none [&_li:last-of-type_a]:rounded-t-none">'
        f"{list_items}"
        "</ul>"
        "</div>"
        "</button>"
        "</div>"
    )
