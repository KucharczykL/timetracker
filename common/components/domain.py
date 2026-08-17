"""Domain components for games / purchases / sessions."""

from typing import TYPE_CHECKING, NamedTuple

from django.template.defaultfilters import floatformat
from django.urls import reverse

from common.components.core import Children, Fragment, Node, as_children
from common.components.primitives import (
    ICON_BUTTON_SIZE_CLASS,
    NAME_MAX_WIDTH_CLASS,
    Icon,
    Input,
    Li,
    Link,
    Popover,
    Span,
    TooltipDefinition,
    TooltipDefinitionList,
    TruncatedText,
    Ul,
)
from games.models import Game, Purchase, Session

if TYPE_CHECKING:
    from common.duration_presentation import DurationPresentation
    from common.returns import OriginUrl


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
        Link(href=link, class_="font-condensed")[*display],
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
    games_list: Node | None = None
    game_count = purchase.games.count()
    if game_count == 1:
        first_game = purchase.games.first()
        if first_game is not None:
            first_game_name = first_game.name
            if purchase.name:
                link_content = f"{first_game_name} - {purchase.get_type_display()} ({purchase.name})"
            else:
                link_content = first_game.name
    if game_count > 1:
        games_list = Ul(class_="list-disc list-inside")[
            *[Li()[game.name] for game in purchase.games.all()]
        ]
        if purchase.name:
            link_content = purchase.name
        else:
            link_content = f"{game_count} games"
    icon = (
        (purchase.platform.icon if purchase.platform else "unspecified")
        if game_count == 1
        else "unspecified"
    )
    if link_content == "":
        raise ValueError("link_content is empty!!")
    return TruncatedText(
        link_content,
        link=link,
        leading=Icon(icon, [("title", "Multiple"), ("class", "shrink-0")]),
        reveal="always" if game_count > 1 else "auto",
        tooltip_content=games_list,
        instance_key=f"purchase-list:{purchase.pk}" if games_list else None,
        reveal_label="Show purchase details",
    )


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
    include_sort_name: bool = False,
    max_width: str = NAME_MAX_WIDTH_CLASS,
) -> Node:
    resolved = _resolve_name_with_icon(name, game, session, linkify)

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

    sort_name = (
        game.sort_name
        if include_sort_name
        and game is not None
        and game.sort_name
        and game.sort_name != resolved.name
        else None
    )
    tooltip_content: Node | None = None
    tooltip_instance_key: str | None = None
    if sort_name is not None:
        assert game is not None
        tooltip_content = TooltipDefinitionList(
            [
                TooltipDefinition(
                    "Name",
                    resolved.name,
                    [
                        ("data-truncated-detail", "name"),
                        ("aria-hidden", "true"),
                        ("class", "hidden group-data-[overflowing]:block"),
                    ],
                ),
                TooltipDefinition(
                    "Sort name",
                    sort_name,
                    [("data-truncated-detail", "sort-name")],
                ),
            ]
        )
        tooltip_instance_key = f"game-list-sort-name:{game.pk}"

    return TruncatedText(
        resolved.name,
        leading=icons,
        link=resolved.link,
        tap=tap,
        reveal="always" if sort_name is not None else "auto",
        tooltip_content=tooltip_content,
        instance_key=tooltip_instance_key,
        max_width=max_width,
        reveal_label=(
            "Show full name and sort name"
            if sort_name is not None
            else "Show full name"
        ),
    )


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
        # Without this, Popover derives its id from its own content, so any two
        # purchases sharing both the original and the converted price collide —
        # a DEBUG-only 500 on every list that renders more than one purchase.
        id=f"purchase-price-{purchase.pk}",
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


def DurationText(
    duration,
    presentation: DurationPresentation,
    *,
    manual: bool = False,
) -> Node:
    """The value itself: visible text plus its ``sr-only`` spoken form.

    Split out of :func:`Duration` so a surface that already owns a popover can
    show a duration without nesting one popover inside another.
    """
    visible = presentation.format(duration)
    return Fragment(
        Span(aria_hidden="true")[f"{visible}*" if manual else visible],
        Span(class_="sr-only")[presentation.spoken(duration, manual=manual)],
    )


def DurationAlternates(duration, presentation: DurationPresentation) -> Node:
    """The same value under the other profiles.

    Rendered with the shared informative-tooltip treatment rather than a local
    one: profile name and value are a term/description pair, which is what a
    definition list is for, and the colors come from the design system instead
    of being chosen here.
    """
    return TooltipDefinitionList(
        [
            TooltipDefinition(label, rendering, [("class", "tabular-nums")])
            for label, rendering in presentation.alternates(duration)
        ]
    )


def Duration(
    duration,
    presentation: DurationPresentation,
    *,
    id_scope: str,
    manual: bool = False,
    link: str | None = None,
) -> Node:
    """One elapsed duration, with the same value under the other profiles on hover.

    ``id_scope`` is required and must be unique on the page. ``Popover`` derives
    its DOM id by hashing its own content, so two rows showing the same duration
    would collide — and ``Game.playtime`` defaults to zero, which makes that the
    common case on a game list rather than an edge case.

    The visible text is ``aria-hidden`` and a sibling ``sr-only`` span carries
    the value in words: screen readers read "1.2 h" as "one point two h". For
    the same reason the panel drops ``aria-describedby`` — it restates what the
    ``sr-only`` text already said.

    ``manual`` appends the "*" mark that flags a hand-entered session. It sits
    inside the trigger with the value and is spoken as ", manual"; it qualifies
    the value, not its formatting, so it never appears among the alternates.

    ``link`` makes the value a link to ``link``. The popover's reveal glyph
    then sits beside the link rather than wrapping it — a popover trigger is a
    ``<button>``, which may not nest inside an ``<a>``.
    """
    from common.components.primitives import Popover

    text = DurationText(duration, presentation, manual=manual)
    if link is None:
        return Popover(
            popover_content=DurationAlternates(duration, presentation),
            children=[text],
            wrapped_classes="tabular-nums",
            id=f"duration-{id_scope}",
            describedby=False,
        )
    return Popover(
        popover_content=DurationAlternates(duration, presentation),
        preface=Link(href=link, class_="tabular-nums")[text],
        trigger_label="Other duration formats",
        id=f"duration-{id_scope}",
        describedby=False,
    )


BROWSER_TIME_ZONE_FIELD = "browser_time_zone"


def BrowserTimeZoneInput(field_name: str = BROWSER_TIME_ZONE_FIELD) -> Node:
    """A hidden input `<browser-time-zone>` fills with the browser's IANA zone.

    Submitted by forms that record *when and where* something happened without
    a datetime field to hang a picker on — finishing and resetting a session.
    Empty without JavaScript, which the server treats as "unlabelled endpoint"
    rather than an error.
    """
    from common.components.custom_elements import _BrowserTimeZone

    return _BrowserTimeZone(field_name=field_name)[
        Input(type="hidden", name=field_name, value="")
    ]


def SessionActions(session, csrf_token: str, origin: OriginUrl | None) -> Node:
    """Row actions for a session: Finish + Reset (only while the session is open),
    Edit, Delete. Finish posts and the page reloads; both finish and reset
    confirm on their own page first when accessed via GET. Edit and Delete
    stay plain navigation links, so the whole group works without JavaScript
    beyond the browser-zone stamp the finish form carries."""
    from common.components.primitives import ButtonGroup
    from common.returns import action_url

    is_open = session.timestamp_end is None

    actions = ButtonGroup(
        [
            {
                "slot": Icon("end", size=ICON_BUTTON_SIZE_CLASS),
                "title": "Finish session now",
                "color": "green",
                "method": "post",
                "action": action_url("games:finish_session", session.pk, origin=origin),
                "csrf_token": csrf_token,
                "hidden_fields": BrowserTimeZoneInput(),
            }
            if is_open
            else {},
            {
                "href": action_url("games:reset_session", session.pk, origin=origin),
                "slot": Icon("reset", size=ICON_BUTTON_SIZE_CLASS),
                "title": "Reset start to now",
                "color": "gray",
            }
            if is_open
            else {},
            {
                "href": action_url("games:edit_session", session.pk, origin=origin),
                "slot": Icon("edit", size=ICON_BUTTON_SIZE_CLASS),
                "title": "Edit",
            },
            {
                "href": action_url("games:delete_session", session.pk, origin=origin),
                "slot": Icon("delete", size=ICON_BUTTON_SIZE_CLASS),
                "title": "Delete",
                "color": "red",
            },
        ]
    )

    return actions
