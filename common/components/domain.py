"""Domain components for games / purchases / sessions."""

from typing import Any

from django.template.defaultfilters import floatformat
from django.urls import reverse

from common.components.core import Children, Node, Safe, as_children
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
    children: Children = None,
) -> Node:
    """Link to a game's detail page. Uses children (slot) if provided, otherwise name."""
    from django.urls import reverse

    display = as_children(children) or [name]
    link = reverse("games:view_game", args=[game_id])

    return Span(
        attributes=[("class", "truncate-container")],
        children=[
            A(
                href=link,
                attributes=[
                    ("class", "underline decoration-slate-500 sm:decoration-2"),
                ],
                children=display,
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
        dot = Span(attributes=[("class", dot_base)])
        return Span(class_=outer_class, children=[dot] + as_children(children))

    dot = Span(attributes=[("class", f"mr-[0.28em] {dot_base}")])
    outer_class = "mx-[0.45em] whitespace-nowrap"
    if class_:
        outer_class += f" {class_}"
    return Span(class_=outer_class, children=[dot] + as_children(children))


def PriceConverted(
    children: Children = None,
) -> Node:
    """Wrap content in a span that indicates the price was converted."""
    children = children or []
    return Span(
        attributes=[
            ("title", "Price is a result of conversion and rounding."),
            ("class", "decoration-dotted underline"),
        ],
        children=as_children(children),
    )


def LinkedPurchase(purchase: Purchase) -> Node:
    link = reverse("games:view_purchase", args=[int(purchase.id)])
    link_content = ""
    popover_content = ""
    game_count = purchase.games.count()
    popover_if_not_truncated = False
    if game_count == 1:
        first_game = purchase.games.first()
        if first_game is not None:
            link_content += first_game.name
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
                popover_content=Safe(popover_content),
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
) -> Node:
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
        final_emulated = session.emulated
        if game is not None:
            platform = game.platform
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


def PurchasePrice(purchase) -> Node:
    return Popover(
        popover_content=f"{floatformat(purchase.price)} {purchase.price_currency}",
        wrapped_content=f"{floatformat(purchase.converted_price)} {purchase.converted_currency}",
        wrapped_classes="underline decoration-dotted",
    )


def GameStatusSelector(game, game_statuses, csrf_token: str) -> Node:
    """Status value-selector: a listbox that PATCHes /api/games/<id>/status."""
    from common.components.custom_elements import SelectDropdown, SelectOption

    options: list[SelectOption] = [
        SelectOption(
            value,
            GameStatus(status=value, children=[label], display="flex"),
            value == game.status,
        )
        for value, label in game_statuses
    ]
    return SelectDropdown(
        current_label=GameStatus(
            status=game.status, children=[game.get_status_display()], display="flex"
        ),
        options=options,
        id=f"game-{game.id}-status",
        patch_url=f"/api/games/{game.id}/status",
        body_key="status",
        event="status-changed",
        csrf=csrf_token,
    )


def SessionDeviceSelector(session, session_devices, csrf_token: str) -> Node:
    """Device value-selector: a listbox that PATCHes /api/session/<id>/device."""
    from common.components.custom_elements import SelectDropdown, SelectOption

    current = session.device.id if session.device else None
    options: list[SelectOption] = [
        SelectOption(str(device.id), device.name, device.id == current)
        for device in session_devices
    ]
    return SelectDropdown(
        current_label=session.device.name if session.device else "Unknown",
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
    from common.components.primitives import ButtonGroup, Modal, StyledButton

    is_open = session.timestamp_end is None
    game_name = session.game.name if session.game else "this session"
    modal_id = f"session-{session.pk}-reset-modal"

    actions = ButtonGroup(
        [
            {
                "slot": Icon("end"),
                "title": "Finish session now",
                "color": "green",
                "button_attributes": [("data-finish", "")],
            }
            if is_open
            else {},
            {
                "slot": Icon("reset"),
                "title": "Reset start to now",
                "color": "gray",
                "button_attributes": [("data-reset", "")],
            }
            if is_open
            else {},
            {
                "href": reverse("games:edit_session", args=[session.pk]),
                "slot": Icon("edit"),
                "title": "Edit",
            },
            {
                "href": reverse("games:delete_session", args=[session.pk]),
                "slot": Icon("delete"),
                "title": "Delete",
                "color": "red",
            },
        ]
    )

    children: list[Node] = [actions]
    if is_open:
        children.append(
            Div(attributes=[("data-reset-modal", ""), ("hidden", "")])[
                Modal(
                    modal_id,
                    [
                        Div(class_="text-center dark:text-white")[
                            "Reset the start time of ",
                            Span(class_="font-medium")[game_name],
                            " to now?",
                        ],
                        Div(class_="flex gap-2 mt-6 justify-center")[
                            # Reset overwrites the original start time (only
                            # recoverable via Edit) -> red destructive confirm,
                            # gray secondary cancel.
                            StyledButton(
                                color="red",
                                attributes=[("data-reset-confirm", "")],
                            )["Reset to now"],
                            StyledButton(
                                color="gray",
                                attributes=[("data-reset-cancel", "")],
                            )["Cancel"],
                        ],
                    ],
                )
            ]
        )

    return _SessionActions(
        session_id=session.pk,
        api_url=f"/api/session/{session.pk}",
        csrf=csrf_token,
        game_name=game_name,
        is_open="true" if is_open else "false",
    )[children]
