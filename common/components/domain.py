"""Domain components for games / purchases / sessions."""

import logging
from collections import Counter
from collections.abc import Sequence
from typing import TYPE_CHECKING, Literal, NamedTuple

from django.template.defaultfilters import floatformat
from django.urls import reverse

from common.components.core import Children, Fragment, Node, as_children
from common.components.primitives import (
    NAME_MAX_WIDTH_CLASS,
    Icon,
    Input,
    Li,
    Link,
    PageTab,
    PageTabs,
    Popover,
    Span,
    TooltipDefinition,
    TooltipDefinitionList,
    TruncatedText,
    Ul,
)
from common.date_time_presentation import DateTimePresentation
from common.temporal_presentation import present_temporal_value
from games.end_ways import END_WAY_LABELS, EndWay
from games.endpoints import ENTRY_ACCESS_END
from games.models import (
    EntryAccess,
    EntryFormat,
    ExternalReference,
    Game,
    LibraryEntry,
    PlayerGameStatus,
    PlayerSession,
    Purchase,
)
from games.reads.endpoints import stated, way_of
from games.reads.entries import AccessSummary
from games.reads.sums import PlaytimeBreakdown

if TYPE_CHECKING:
    from common.duration_presentation import DurationPresentation

logger = logging.getLogger("games")


type PlaytimeTab = Literal["sessions", "historical"]
type GamesTab = Literal["games", "library"]


def PlaytimeTabs(current: PlaytimeTab) -> Node:
    """The Playtime page's two lists."""
    return PageTabs(
        "Playtime",
        [
            PageTab(
                "Sessions",
                reverse("games:list_sessions"),
                current=current == "sessions",
            ),
            PageTab(
                "Historical",
                reverse("games:list_historical_playtime"),
                current=current == "historical",
            ),
        ],
    )


def GamesTabs(current: GamesTab, *, trailing: Node | None = None) -> Node:
    """The Games page's two lists."""
    return PageTabs(
        "Games",
        [
            PageTab("Games", reverse("games:list_games"), current=current == "games"),
            PageTab(
                "Library",
                reverse("games:list_library"),
                current=current == "library",
            ),
        ],
        trailing=trailing,
    )


#: A copy's format, and the glyph that draws it, in badge order.
_FORMAT_GLYPHS: tuple[tuple[EntryFormat, str], ...] = (
    (EntryFormat.DIGITAL, "cloud"),
    (EntryFormat.PHYSICAL, "physical"),
)
#: Drawn only where no held copy states a format.
_FORMAT_UNKNOWN_GLYPH = "dashed-ring"
_ACCESS_BADGE_CLASS = (
    "inline-flex items-center gap-1 px-1.5 py-0.5 rounded-base border "
    "text-type-body leading-none whitespace-nowrap"
)
_ACCESS_GLYPH_SIZE = "size-4"
_ACCESS_BADGE_FILL = {
    True: "solid-brand border-brand",
    False: "border-default-medium text-body",
}


#: Ends an access comes to by itself, so a line names the day alone.
_NATURAL_ENDS: dict[str, frozenset[EndWay]] = {
    EntryAccess.BORROWED: frozenset({EndWay.RETURNED, EndWay.EXPIRED}),
    EntryAccess.RENTED: frozenset({EndWay.RETURNED, EndWay.EXPIRED}),
    EntryAccess.SUBSCRIPTION: frozenset({EndWay.EXPIRED}),
    EntryAccess.TRIAL: frozenset({EndWay.EXPIRED, EndWay.REVOKED}),
    EntryAccess.DEMO: frozenset({EndWay.EXPIRED, EndWay.REVOKED}),
}


class AccessLine(NamedTuple):
    words: str
    ended: bool


def _copy_words(entry: LibraryEntry) -> str:
    """Owned and digital go unsaid; empty for an owned digital copy."""
    owned = entry.access == EntryAccess.OWNED
    words = "" if owned else EntryAccess(entry.access).label
    if entry.format == EntryFormat.PHYSICAL:
        return f"{words} physical" if words else "Physical"
    if entry.format == EntryFormat.UNKNOWN:
        return f"{words or 'Owned'}, format unknown"
    return words


def _ended_words(entry: LibraryEntry, presentation: DateTimePresentation) -> str:
    ended = stated(entry, ENTRY_ACCESS_END)
    if ended is None:
        raise ValueError("An ended copy states its end.")
    way = way_of(ended)
    day = (
        None if ended.when is None else present_temporal_value(ended.when, presentation)
    )
    words = _copy_words(entry)
    if way in _NATURAL_ENDS.get(entry.access, frozenset()):
        return f"{words or 'Owned'} until {day or '?'}"
    how = END_WAY_LABELS[way]
    words = f"{words}, {how.lower()}" if words else how
    return f"{words} {day}" if day else words


def _grouped(words: list[str], *, ended: bool) -> list[AccessLine]:
    counts = Counter(words)
    return [
        AccessLine(
            line if count == 1 else f"{count} × {line[0].lower()}{line[1:]}", ended
        )
        for line, count in counts.items()
    ]


#: An engraved groove: a dark rule over a light one, panel-wide.
_HELD_ENDED_GROOVE = (
    "mt-1 pt-1 -mx-3 px-3 border-t border-black/15 dark:border-black/45 "
    "shadow-[inset_0_1px_0_rgb(255_255_255_/_0.8)] "
    "dark:shadow-[inset_0_1px_0_rgb(255_255_255_/_0.12)]"
)


def _line_class(lines: list[AccessLine], index: int) -> str:
    """Ended rows are muted; the first under held rows is grooved."""
    first_ended = index > 0 and not lines[index - 1].ended
    return f"text-body {_HELD_ENDED_GROOVE}" if first_ended else "text-body"


def access_lines(
    summary: AccessSummary, presentation: DateTimePresentation
) -> list[AccessLine]:
    """Held copies, then ended ones, latest end first."""
    held = [_copy_words(entry) or "Owned" for entry in summary.held]
    ended = [_ended_words(entry, presentation) for entry in summary.ended]
    return [*_grouped(held, ended=False), *_grouped(ended, ended=True)]


def AccessBadge(
    summary: AccessSummary, presentation: DateTimePresentation, *, id: str
) -> Node:
    """Fill: owned now. Glyph: format. Number: copies held."""
    shown = summary.held or ((summary.former,) if summary.former else ())
    formats = {entry.format for entry in shown}
    glyphs = [glyph for word, glyph in _FORMAT_GLYPHS if word in formats]
    lines = access_lines(summary, presentation)
    held = len(summary.held)
    return Popover(
        popover_content=Ul(class_="space-y-0.5")[
            *(
                Li([("class", _line_class(lines, index))] if line.ended else [])[
                    line.words
                ]
                for index, line in enumerate(lines)
            )
        ],
        wrapped_classes=(
            f"{_ACCESS_BADGE_CLASS} {_ACCESS_BADGE_FILL[summary.owned_now]}"
        ),
        children=[
            #: Whole pixels: a fractional glyph rounds apart from the border.
            *(
                Icon(glyph, size=_ACCESS_GLYPH_SIZE, decorative=True)
                for glyph in glyphs or [_FORMAT_UNKNOWN_GLYPH]
            ),
            *([Span(aria_hidden="true")[str(held)]] if held > 1 else []),
            #: The button's name; the panel repeats it for the eye alone.
            Span(class_="sr-only")["; ".join(line.words for line in lines)],
        ],
        id=id,
        symbol_trigger=True,
        describedby=False,
    )


def GameLink(
    game: Game,
    name: str = "",
    children: Children = None,
) -> Node:
    """Link to a game's detail page. Uses children (slot) if provided, otherwise name."""
    display = as_children(children) or [name]

    return Span(class_="truncate-container")[
        Link(href=game.get_absolute_url(), class_="font-condensed")[*display],
    ]


#: Keyed on str, not on the enum: the value reaching GameStatus() is a
#: plain word off a queryset annotation as often as it is a member.
_STATUS_COLORS: dict[str, str] = {
    PlayerGameStatus.UNPLAYED: "bg-gray-500",
    PlayerGameStatus.PLAYED: "bg-orange-400",
    PlayerGameStatus.COMPLETED: "bg-green-500",
    PlayerGameStatus.RETIRED: "bg-purple-500",
    PlayerGameStatus.SHELVED: "bg-sky-500",
    PlayerGameStatus.ABANDONED: "bg-red-500",
}


def GameStatus(
    children: Children = None,
    status: str = PlayerGameStatus.UNPLAYED,
    display: str = "",
    class_: str = "",
) -> Node:
    """Colored status dot with label. Status is a PlayerGameStatus value.

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
    dot_color = _STATUS_COLORS.get(status, _STATUS_COLORS[PlayerGameStatus.UNPLAYED])
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


def _reference_link(reference: ExternalReference) -> Node:
    """One link, or the words alone.

    A row that states no link is a defect in the data, and this
    component stands on Game detail and on the whole Platform list.
    A raise would take both pages down for everybody.
    """
    from games.external_references import (
        PROVIDER_POLICIES,
        external_reference_url_or_none,
    )

    policy = PROVIDER_POLICIES.get(reference.provider)
    url = external_reference_url_or_none(
        provider=reference.provider,
        entity_kind=reference.entity_kind,
        provider_key=reference.provider_key,
    )
    text = f"{policy.label if policy else reference.provider} {reference.provider_key}"
    if url is None:
        logger.error(
            "[references]: %s states no link for %s %r",
            reference.entity_kind,
            reference.provider,
            reference.provider_key,
        )
        return Span(class_="whitespace-nowrap")[text]
    return Link(
        href=url,
        class_="whitespace-nowrap",
        rel="noopener noreferrer",
        target="_blank",
    )[text]


def ExternalReferenceLinks(references: Sequence[ExternalReference]) -> Node:
    """One link per reference, escaped three ways."""
    if not references:
        return Fragment()
    return Span(class_="flex flex-wrap gap-2")[
        *(_reference_link(reference) for reference in references)
    ]


def _game_name(game: Game, purchase: Purchase) -> str:
    """The game's name, or words instead.

    `Game.name` is not blank, so an empty one is a row
    nothing here wrote. One cell degrades and says which
    row to look at; the whole list does not stop.
    """
    if game.name:
        return game.name
    logger.error(
        "[purchases]: game %s of purchase %s states no name", game.pk, purchase.pk
    )
    return "Untitled game"


def LinkedPurchase(purchase: Purchase) -> Node:
    link = reverse("games:view_purchase", args=[purchase.id])
    games_list: Node | None = None
    #: Read the relation once, not per row.
    #: `first()` orders, which the prefetch cache cannot
    #: answer, so the list pays a query per row.
    games = list(purchase.games.all())
    game_count = len(games)
    if game_count == 0:
        #: A purchase naming no game is live.
        link_content = purchase.name or "No games"
    elif game_count == 1:
        first_game_name = _game_name(games[0], purchase)
        if purchase.name:
            link_content = (
                f"{first_game_name} - {purchase.get_type_display()} ({purchase.name})"
            )
        else:
            link_content = first_game_name
    else:
        games_list = Ul(class_="list-disc list-inside")[
            *[Li()[_game_name(game, purchase)] for game in games]
        ]
        link_content = purchase.name or f"{game_count} games"
    icon = (
        (purchase.platform.icon if purchase.platform else "unspecified")
        if game_count == 1
        else "unspecified"
    )
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
    session: PlayerSession | None = None,
    linkify: bool = True,
    tap: bool = True,
    include_sort_name: bool = False,
    max_width: str = NAME_MAX_WIDTH_CLASS,
) -> Node:
    """A name with its platform badge."""
    resolved = _resolve_name_with_icon(name, game, session, linkify)
    if session is not None and game is None:
        game = session.playthrough.player_game.game

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

    truncated = TruncatedText(
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
    return truncated


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
    session: PlayerSession | None,
    linkify: bool,
) -> ResolvedNameWithIcon:
    link: str | None = None
    badge = None
    emulated = False

    if session is not None:
        #: Through the run: a session names no game of its own.
        game = session.playthrough.player_game.game
        emulated = session.emulated
    if game is not None:
        badge = _platform_badge(game)
        if linkify:
            link = game.get_absolute_url()

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


def GameStatusSelector(
    game,
    game_statuses,
    csrf_token: str,
    class_: str = "",
    *,
    current: str,
) -> Node:
    """Status value-selector: a listbox that PATCHes /api/games/<id>/status.

    ``current`` is the status the page shows, taken from the library's
    projection row. It is a parameter rather than a read off ``game``
    because it arrives as a queryset annotation, which is not an
    attribute of the model instance.
    """
    from common.components.custom_elements import SelectDropdown, SelectOption

    labels = dict(game_statuses)
    options: list[SelectOption] = [
        SelectOption(
            value,
            GameStatus([label], status=value, display="flex"),
            value == current,
        )
        for value, label in game_statuses
    ]
    return SelectDropdown(
        current_label=GameStatus(
            [labels.get(current, current)], status=current, display="flex"
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
        empty_is_null=True,
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
    would collide — and an unplayed game reads zero, which makes that the common
    case on a game list rather than an edge case.

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


def PlaytimeSplit(
    breakdown: PlaytimeBreakdown,
    presentation: DurationPresentation,
    *,
    id_scope: str,
    link: str | None = None,
) -> Node:
    """A total, and beneath it the two sources that made it.

    A zero historical half answers the bare ``Duration``, so a figure of
    sessions alone renders what it rendered before the split existed.

    The two lines are one element: a flex host would take siblings as two
    items and lay them side by side. A host that states its own rows, or one
    that owns the popover already, composes ``Duration`` or ``DurationText``
    with :func:`PlaytimeHalves` instead.
    """
    total = Duration(breakdown.total, presentation, id_scope=id_scope, link=link)
    if not breakdown.historical:
        return total
    return Span(class_="block")[
        Span(class_="block")[total],
        PlaytimeHalves(breakdown, presentation),
    ]


def PlaytimeHalves(
    breakdown: PlaytimeBreakdown, presentation: DurationPresentation
) -> Node:
    """The two sources of a total, on one line of smaller text.

    ``PlaytimeSplit`` puts it beneath the total; a host whose total sits inside
    a popover puts it beneath the popover instead.
    """
    #: Tighter than the token's leading: a caption under a figure reads as
    #: one block, and the line it hangs from grows by less.
    return Span(class_="block text-type-micro leading-3.5 text-body")[
        DurationText(breakdown.tracked, presentation),
        " tracked",
        Span(aria_hidden="true")[" · "],
        DurationText(breakdown.historical, presentation),
        " historical",
    ]


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
