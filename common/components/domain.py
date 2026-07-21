"""Domain components for games / purchases / sessions."""

from typing import NamedTuple

from django.template.defaultfilters import floatformat
from django.urls import reverse

from common.components.core import Children, Fragment, Node, as_children
from common.components.primitives import (
    H1,
    ICON_BUTTON_SIZE_CLASS,
    A,
    Br,
    Div,
    Icon,
    Li,
    Popover,
    PopoverTruncated,
    Span,
    Ul,
)
from common.utils import truncate_info
from games.models import Game, Purchase, Session

# A quiet reveal affordance rendered beside a link when its text is truncated (or
# a bundle needs its games list): a real <button> sibling of the link hosting the
# popover, so touch users can tap to reveal without the tap navigating — the link
# itself stays a link. The truncated name is rendered WITHOUT its trailing
# ellipsis and this ellipsis-icon button stands in for it — so the "…" both marks
# the cut and is the tap target, instead of a redundant "…" + separate glyph. An
# SVG icon (not a unicode "⋯", whose ink sits high in its line box) so it
# optically centres against the adjacent name.
# A 24px-square button (WCAG 2.5.8 touch-target minimum) centring the smaller
# icon. `-my-1` lets the 24px box overflow the ~20px text line vertically so a
# truncated-name row stays the same height as its neighbours instead of growing.
_REVEAL_GLYPH_CLASS = (
    "inline-flex items-center justify-center size-6 -my-1 text-subtle "
    "hover:text-heading hover:cursor-pointer rounded-base shrink-0"
)


def _reveal_popover(popover_content: Node | str, preface: Node, label: str) -> Node:
    """A truncation/bundle reveal: an ellipsis-icon <button> beside ``preface``
    (the link), hosting ``popover_content``. The whole host still opens on hover;
    only the button is tappable, keeping the trigger out of the link."""
    return Popover(
        popover_content=popover_content,
        children=[Icon("ellipsis", [("class", "size-[1.1em] shrink-0")])],
        wrapped_classes=_REVEAL_GLYPH_CLASS,
        trigger_label=label,
        preface=preface,
    )


def GameLink(
    game_id: int,
    name: str = "",
    children: Children = None,
) -> Node:
    """Link to a game's detail page. Uses children (slot) if provided, otherwise name."""
    from django.urls import reverse

    display = as_children(children) or [name]
    link = reverse("games:view_game", args=[game_id])

    return Span(class_="truncate-container")[
        A(
            href=link,
            class_="font-condensed underline decoration-slate-500 sm:decoration-2",
        )[*display],
    ]


_STATUS_COLORS = {
    "u": "bg-gray-500",
    "p": "bg-orange-400",
    "f": "bg-green-500",
    "a": "bg-red-500",
    "r": "bg-purple-500",
}


def GameStatus(
    children: Children = None,
    status: str = "u",
    display: str = "",
    class_: str = "",
) -> Node:
    """Colored status dot with label. Status codes: u/p/f/a/r.

    The dot is sized in the `cap` unit (`w-[1cap]`), so it is exactly one
    cap-height tall in whatever font renders it — the browser computes the
    cap-height, no per-font tuning needed — and it scales with the text. Color
    comes from a background utility so any CSS color works.

    Flex mode (`display="flex"`, e.g. the status selector) lays dot + label out
    as a flex row and lets `items-center` handle vertical centering.

    Inline mode (default, e.g. the game-detail history line) keeps the label in
    normal inline flow so it sits on the surrounding text baseline (issue #97),
    and centers the dot on the text: the dot is an *empty* inline-block, whose
    baseline is its bottom edge, so the default `vertical-align: baseline` seats
    its bottom on the text baseline; being `1cap` tall it then spans exactly
    baseline→cap-top and is centered on the capital letters in any font. (A
    `&nbsp;` filler would give the dot its own inner text baseline and lift it
    visibly above the line.) Spacing is component-owned and em-based: the inner
    gap (`mr-[0.28em]`, dot↔label) is deliberately smaller than the outer gap
    (`mx-[0.45em]`, group↔neighbors) so dot + label read as one group by
    proximity at any font size — independent of surrounding word-spaces.
    `whitespace-nowrap` keeps the dot and its label on the same line.
    """
    children = children or []
    dot_color = _STATUS_COLORS.get(status, _STATUS_COLORS["u"])
    dot_base = f"inline-block rounded-full w-[1cap] h-[1cap] {dot_color}"

    if display == "flex":
        outer_class = "flex gap-2 items-center"
        if class_:
            outer_class += f" {class_}"
        dot = Span(class_=dot_base)
        return Span(class_=outer_class)[dot, *as_children(children)]

    dot = Span(class_=f"mr-[0.28em] {dot_base}")
    outer_class = "mx-[0.45em] whitespace-nowrap"
    if class_:
        outer_class += f" {class_}"
    return Span(class_=outer_class)[dot, *as_children(children)]


def PriceConverted(
    children: Children = None,
) -> Node:
    """Wrap content in a span that indicates the price was converted."""
    children = children or []
    return Span(
        title="Price is a result of conversion and rounding.",
        class_="decoration-dotted underline",
    )[*as_children(children)]


def LinkedPurchase(purchase: Purchase) -> Node:
    link = reverse("games:view_purchase", args=[int(purchase.id)])
    link_content = ""
    popover_content: Node | str = ""
    game_count = purchase.games.count()
    if game_count == 1:
        first_game = purchase.games.first()
        if first_game is not None:
            first_game_name = first_game.name
            if purchase.name:
                link_content = f"{first_game_name} - {purchase.get_type_display()} ({purchase.name})"
            else:
                link_content = first_game.name
            popover_content = link_content
    if game_count > 1:
        games_list = Ul(class_="list-disc list-inside")[
            *[Li()[game.name] for game in purchase.games.all()]
        ]
        if purchase.name:
            link_content = purchase.name
            popover_content = Fragment(H1()[purchase.name], Br(), games_list)
        else:
            link_content = f"{game_count} games"
            popover_content = games_list
    icon = (
        (purchase.platform.icon if purchase.platform else "unspecified")
        if game_count == 1
        else "unspecified"
    )
    if link_content == "":
        raise ValueError("link_content is empty!!")
    # No trailing ellipsis: the reveal button's ellipsis icon stands in for it.
    truncation = truncate_info(link_content, ellipsis="")
    link_node = A(href=link)[
        Div(class_="font-condensed inline-flex gap-2 items-center")[
            Icon(
                icon,
                [("title", "Multiple")],
            ),
            truncation.display,
        ]
    ]
    # Multi-game purchases always expose the games list; single-game purchases
    # only need the reveal when the name was cut off. The reveal trigger is a
    # <button> sibling of the link (see `preface`), never nested inside it, so a
    # tap toggles the popover while the link stays a navigable link.
    if not (truncation.was_truncated or game_count > 1):
        return link_node
    return _reveal_popover(popover_content, link_node, "Show purchase details")


class PlatformBadge(NamedTuple):
    """Icon slug + title for a game's platform badge (see ``_platform_badge``)."""

    icon: str
    title: str


class ResolvedNameWithIcon(NamedTuple):
    name: str
    badge: PlatformBadge | None
    emulated: bool
    link: str | None  # None = render unlinked


def NameWithIcon(
    name: str = "",
    game: Game | None = None,
    session: Session | None = None,
    linkify: bool = True,
    tap: bool = True,
) -> Node:
    resolved = _resolve_name_with_icon(name, game, session, linkify)
    # No trailing ellipsis on the linked name: the reveal button's ellipsis icon
    # stands in for it (the unlinked branch keeps PopoverTruncated's inline "…").
    truncation = truncate_info(resolved.name, ellipsis="")

    icons = Fragment(
        Icon(
            resolved.badge.icon,
            [("title", resolved.badge.title), ("class", "shrink-0")],
        )
        if resolved.badge
        else "",
        Icon("emulated", [("title", "Emulated"), ("class", "shrink-0")])
        if resolved.emulated
        else "",
    )

    if resolved.link is None:
        # Unlinked: a caller may wrap this in its own interactive element (the
        # navbar menu passes tap=False, so no <button> nests inside its <a>); a
        # standalone unlinked name keeps the tappable default.
        return Div(class_="font-condensed inline-flex gap-2 items-center")[
            icons,
            PopoverTruncated(resolved.name, tap=tap, selectable_text=True),
        ]

    link_node = A(href=resolved.link)[
        Div(class_="font-condensed inline-flex gap-2 items-center")[
            icons,
            truncation.display,
        ]
    ]
    if not truncation.was_truncated:
        return link_node
    return _reveal_popover(resolved.name, link_node, "Show full name")


def _platform_badge(game: Game) -> PlatformBadge:
    """Badge for a game's platform. A game without a platform still gets a
    badge (the "unspecified" fallback); only the no-game-context case (a
    name-only ``NameWithIcon``) gets no badge at all — that decision lives in
    ``_resolve_name_with_icon``, which returns ``badge=None`` there."""
    if game.platform:
        return PlatformBadge(icon=game.platform.icon, title=game.platform.name)
    return PlatformBadge(icon="unspecified", title="Unspecified")


def _resolve_name_with_icon(
    name: str,
    game: Game | None,
    session: Session | None,
    linkify: bool,
) -> ResolvedNameWithIcon:
    link: str | None = None
    badge = None
    emulated = False

    if session is not None:
        game = session.game
        emulated = session.emulated
    if game is not None:
        badge = _platform_badge(game)
        if linkify:
            link = reverse("games:view_game", args=[int(game.pk)])

    resolved_name = name or (game.name if game else "")

    return ResolvedNameWithIcon(
        name=resolved_name, badge=badge, emulated=emulated, link=link
    )


def PurchasePrice(purchase) -> Node:
    return Popover(
        popover_content=f"{floatformat(purchase.price)} {purchase.price_currency}",
        wrapped_content=f"{floatformat(purchase.converted_price)} {purchase.converted_currency}",
        wrapped_classes="underline decoration-dotted",
        selectable_text=True,
    )


def GameStatusSelector(game, game_statuses, csrf_token: str, class_: str = "") -> Node:
    """Status value-selector: a listbox that PATCHes /api/games/<id>/status."""
    from common.components.custom_elements import SelectDropdown, SelectOption

    options: list[SelectOption] = [
        SelectOption(
            value,
            GameStatus([label], status=value, display="flex"),
            value == game.status,
        )
        for value, label in game_statuses
    ]
    return SelectDropdown(
        current_label=GameStatus(
            [game.get_status_display()], status=game.status, display="flex"
        ),
        options=options,
        id=f"game-{game.id}-status",
        patch_url=f"/api/games/{game.id}/status",
        body_key="status",
        event="status-changed",
        csrf=csrf_token,
        class_=class_,
    )


def SessionDeviceSelector(session, session_devices, csrf_token: str) -> Node:
    """Device value-selector: a listbox that PATCHes /api/session/<id>/device."""
    from common.components.custom_elements import SelectDropdown, SelectOption

    current = session.device.id if session.device else None
    options: list[SelectOption] = [
        # Clear entry, always first: empty data-value PATCHes device_id=null.
        # Labeled "No device" so a real device named "Unknown" can't be
        # mistaken for it.
        SelectOption("", "No device", session.device is None),
        *(
            SelectOption(str(device.id), device.name, device.id == current)
            for device in session_devices
        ),
    ]
    return SelectDropdown(
        current_label=session.device.name if session.device else "No device",
        options=options,
        id=f"session-{session.id}-device",
        patch_url=f"/api/session/{session.id}/device",
        body_key="device_id",
        event="device-changed",
        csrf=csrf_token,
        numeric=True,
    )


def SessionActions(session, csrf_token: str) -> Node:
    """Row actions for a session: Finish + Reset (only while the session is open),
    Edit, Delete. The finish/reset buttons drive ``PATCH /api/session/<id>`` and
    swap the row client-side; reset opens an inline confirm modal. Edit/Delete stay
    plain navigation links. Behavior lives in ``ts/elements/session-actions.ts``;
    this server-renders the full light DOM so the row works on first paint."""
    from common.components.custom_elements import _SessionActions
    from common.components.primitives import ButtonGroup, ControlButton, Modal

    is_open = session.timestamp_end is None
    game_name = session.game.name if session.game else "this session"
    modal_id = f"session-{session.pk}-reset-modal"

    actions = ButtonGroup(
        [
            {
                "slot": Icon("end", size=ICON_BUTTON_SIZE_CLASS),
                "title": "Finish session now",
                "color": "green",
                "button_attributes": [("data-finish", "")],
            }
            if is_open
            else {},
            {
                "slot": Icon("reset", size=ICON_BUTTON_SIZE_CLASS),
                "title": "Reset start to now",
                "color": "gray",
                "button_attributes": [("data-reset", "")],
            }
            if is_open
            else {},
            {
                "href": reverse("games:edit_session", args=[session.pk]),
                "slot": Icon("edit", size=ICON_BUTTON_SIZE_CLASS),
                "title": "Edit",
            },
            {
                "href": reverse("games:delete_session", args=[session.pk]),
                "slot": Icon("delete", size=ICON_BUTTON_SIZE_CLASS),
                "title": "Delete",
                "color": "red",
            },
        ]
    )

    children: list[Node] = [actions]
    if is_open:
        children.append(
            Div(data_reset_modal="", hidden="")[
                # self_dismiss=False: <session-actions> owns this overlay's
                # open/close and its own bindPopupDismiss.
                Modal(modal_id, self_dismiss=False)[
                    Div(class_="text-center")[
                        "Reset the start time of ",
                        Span(class_="font-medium")[game_name],
                        " to now?",
                    ],
                    Div(class_="flex gap-2 mt-6 justify-center")[
                        # Reset overwrites the original start time (only
                        # recoverable via Edit) -> red destructive confirm,
                        # gray secondary cancel.
                        ControlButton(
                            color="red",
                            data_reset_confirm="",
                        )["Reset to now"],
                        ControlButton(
                            color="gray",
                            data_reset_cancel="",
                        )["Cancel"],
                    ],
                ]
            ]
        )

    return _SessionActions(
        session_id=session.pk,
        api_url=f"/api/session/{session.pk}",
        csrf=csrf_token,
        game_name=game_name,
        is_open="true" if is_open else "false",
    )[children]
