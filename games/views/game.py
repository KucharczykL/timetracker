from datetime import timedelta
from typing import Any

from django.contrib.auth.decorators import login_required
from django.db.models import F, OuterRef, Q, QuerySet, Subquery, Sum
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.middleware.csrf import get_token
from django.shortcuts import get_object_or_404, redirect
from django.template.defaultfilters import date as date_filter
from django.urls import reverse

from common.components import (
    PageHeading,
    A,
    AddForm,
    ButtonGroup,
    Column,
    ContentContainer,
    CsrfInput,
    Div,
    Form,
    Fragment,
    GameStatus,
    GameStatusSelector,
    ICON_BUTTON_SIZE_CLASS,
    Icon,
    LinkedPurchase,
    Modal,
    ModuleScript,
    NameWithIcon,
    Node,
    Popover,
    PopoverTruncated,
    PurchasePrice,
    QuickFilterBar,
    parse_filter_dict,
    Safe,
    ControlButton,
    StyledTable,
    TableData,
    Ul,
    make_row,
    paginated_table_content,
)
from common.components.primitives import Li, P, Span, Strong
from common.layout import render_page
from common.time import (
    dateformat,
    format_duration,
    local_strftime,
)
from common.utils import paginate, safe_division
from games.filters import (
    PlayEventFilter,
    PurchaseFilter,
    SessionFilter,
    filter_url,
    parse_game_filter,
)
from games.formatting import session_time_range
from games.forms import GameForm
from games.models import Game, GameStatusChange, Session
from games.sorting import GAME_DEFAULT_SORT, GAME_SORTS, apply_sort, parse_find_filter
from games.views.filtering import (
    apply_structured_filter,
    builder_url_for,
    warn_unknown_sort,
)
from games.views.general import use_custom_redirect
from games.views.playevent import create_playevent_tabledata


@login_required
def list_games(request: HttpRequest) -> HttpResponse:
    games = Game.objects.select_related("platform")

    # Playtime column sums only the sessions matching the active session
    # sub-filter; an empty Q matches every session, so with no session filter the
    # column shows total playtime.
    session_q = Q()

    # ── Structured filter (Stash-style JSON; free-text search lives here too) ──
    filter_json = request.GET.get("filter", "")
    if filter_json:
        game_filter = apply_structured_filter(request, parse_game_filter, filter_json)
        if game_filter is not None:
            games = games.filter(game_filter.to_q())
            if game_filter.session_filter is not None:
                session_q = game_filter.session_filter.to_q()

    # Per-game playtime restricted to the session sub-filter, summed in the DB.
    # session_q stays in Session's own field namespace via the correlated
    # subquery, so no `sessions__` path-prefixing is needed.
    windowed_playtime = (
        Session.objects.filter(session_q, game=OuterRef("pk"))
        .values("game")
        .annotate(total=Sum(F("duration_calculated") + F("duration_manual")))
        .values("total")
    )
    games = games.annotate(filtered_playtime=Subquery(windowed_playtime))

    find = parse_find_filter(request)
    sort = apply_sort(games, find, GAME_SORTS, GAME_DEFAULT_SORT)
    games = sort.queryset
    warn_unknown_sort(request, sort.unknown, entity="game")

    games, page_obj, elided_page_range = paginate(games, find)

    data: TableData = {
        "columns": [
            Column("Name", "name"),
            Column("Sort Name", "sort_name"),
            Column("Year", "year"),
            Column("Playtime", "filtered_playtime"),
            Column("Status", "status"),
            Column("Wikidata", "wikidata"),
            Column("Created", "created"),
            Column("Actions", align="right"),
        ],
        "sort_terms": sort.terms,
        "rows": [
            make_row(
                NameWithIcon(game=game),
                PopoverTruncated(
                    game.sort_name
                    if game.sort_name is not None and game.name != game.sort_name
                    else "(identical)"
                ),
                str(game.year_released),
                format_duration(game.filtered_playtime or timedelta(0), "%2.1H"),
                GameStatusSelector(game, Game.Status.choices, get_token(request)),
                game.wikidata,
                local_strftime(game.created_at, dateformat),
                ButtonGroup(
                    [
                        {
                            "href": reverse("games:edit_game", args=[game.pk]),
                            "slot": Icon("edit", size=ICON_BUTTON_SIZE_CLASS),
                            "color": "gray",
                        },
                        {
                            "href": reverse("games:delete_game", args=[game.pk]),
                            "slot": Icon("delete", size=ICON_BUTTON_SIZE_CLASS),
                            "color": "red",
                        },
                    ]
                ),
            )
            for game in games
        ],
    }
    content = paginated_table_content(
        data,
        page_obj=page_obj,
        elided_page_range=elided_page_range,
        request=request,
        page_size=find.per_page,
    )
    # The quick bar is the page's only filter tier: dropdown facets,
    # preset picker, and the builder entry point in the action group.
    builder_url = builder_url_for("games", filter_json, find.sort, find.per_page)
    parsed_filter = parse_filter_dict(filter_json)
    quick_bar = QuickFilterBar(
        mode="games",
        existing=parsed_filter,
        builder_url=builder_url,
        preset_api_url=reverse("api-1.0.0:list_presets"),
    )
    content = ContentContainer()[quick_bar, content]
    return render_page(
        request,
        content,
        title="Manage games",
    )


@login_required
def add_game(request: HttpRequest) -> HttpResponse:
    form = GameForm(request.POST or None)
    if form.is_valid():
        game = form.save()
        if "submit_and_redirect" in request.POST:
            return HttpResponseRedirect(
                reverse("games:add_purchase_for_game", kwargs={"game_id": game.id})
            )
        elif "submit_and_create_session" in request.POST:
            return HttpResponseRedirect(
                reverse("games:add_session_for_game", kwargs={"game_id": game.id})
            )
        else:
            return redirect("games:list_games")

    return render_page(
        request,
        AddForm(
            form,
            request=request,
            additional_row=Fragment(
                ControlButton(
                    color="gray",
                    type="submit",
                    name="submit_and_redirect",
                )["Submit & Create Purchase"],
                ControlButton(
                    color="gray",
                    type="submit",
                    name="submit_and_create_session",
                )["Submit & Create Session"],
            ),
        ),
        title="Add New Game",
        scripts=Fragment(
            ModuleScript("dist/elements/search-select.js"),
            ModuleScript("dist/add_game.js"),
        ),
    )


def _delete_game_confirmation_modal(
    game: Game,
    session_count: int,
    purchase_count: int,
    playevent_count: int,
    request: HttpRequest,
) -> Node:
    data_items = []
    if session_count:
        data_items.append(Li()[f"{session_count} session(s)"])
    if purchase_count:
        data_items.append(Li()[f"{purchase_count} purchase(s)"])
    if playevent_count:
        data_items.append(Li()[f"{playevent_count} play event(s)"])
    if not (session_count or purchase_count or playevent_count):
        data_items.append(Li()["No associated data"])

    form = Form(
        hx_post=reverse("games:delete_game", args=[game.id]),
        hx_replace_url="true",
        hx_target="#main-container",
        hx_select="#main-container",
        hx_swap="outerHTML",
    )[
        CsrfInput(request),
        P(
            class_="dark:text-white text-center mt-3 text-sm text-gray-600 "
            "dark:text-gray-400",
        )["This will permanently delete this game and all associated data:"],
        Ul(
            class_="dark:text-white text-center mt-1 text-sm text-gray-600 "
            "dark:text-gray-400 list-disc list-inside",
        )[*data_items],
        P(
            class_="dark:text-white text-center mt-3 text-sm font-medium "
            "text-red-600 dark:text-red-400",
        )["This action cannot be undone."],
        Div(class_="flex flex-col gap-2 mt-5")[
            ControlButton(
                color="red",
                type="submit",
            )["Delete"],
            ControlButton(
                color="gray",
                data_modal_dismiss="",
            )["Cancel"],
        ],
    ]
    return Modal("delete-game-confirmation-modal")[
        P(
            class_="text-2xl leading-6 font-medium dark:text-white text-center",
        )["Delete Game"],
        P(
            class_="dark:text-white text-center mt-5",
        )[
            "Are you sure you want to delete ",
            Strong()[game.name],
            "?",
        ],
        form,
    ]


@login_required
def delete_game_confirmation(request: HttpRequest, game_id: int) -> HttpResponse:
    game = get_object_or_404(Game, id=game_id)
    return HttpResponse(
        str(
            _delete_game_confirmation_modal(
                game,
                game.sessions.count(),
                game.purchases.count(),
                game.playevents.count(),
                request,
            )
        )
    )


@login_required
def delete_game(request: HttpRequest, game_id: int) -> HttpResponse:
    game = get_object_or_404(Game, id=game_id)
    game.delete()
    return redirect("games:list_sessions")


@login_required
@use_custom_redirect
def edit_game(request: HttpRequest, game_id: int) -> HttpResponse:
    purchase = get_object_or_404(Game, id=game_id)
    form = GameForm(request.POST or None, instance=purchase)
    if form.is_valid():
        form.save()
        return redirect("games:list_sessions")
    return render_page(
        request,
        AddForm(form, request=request),
        title="Edit Game",
        scripts=ModuleScript("dist/elements/search-select.js"),
    )


# --- view_game content builders -------------------------------------------

_STAT_SVGS = {
    "hours": '<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="size-6"><path stroke-linecap="round" stroke-linejoin="round" d="M12 6v6h4.5m4.5 0a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z" /></svg>',
    "sessions": '<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="size-6"><path stroke-linecap="round" stroke-linejoin="round" d="M5.25 8.25h15m-16.5 7.5h15m-1.8-13.5-3.9 19.5m-2.1-19.5-3.9 19.5" /></svg>',
    "average": '<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="size-6"><path stroke-linecap="round" stroke-linejoin="round" d="M7.5 14.25v2.25m3-4.5v4.5m3-6.75v6.75m3-9v9M6 20.25h12A2.25 2.25 0 0 0 20.25 18V6A2.25 2.25 0 0 0 18 3.75H6A2.25 2.25 0 0 0 3.75 6v12A2.25 2.25 0 0 0 6 20.25Z" /></svg>',
    "playrange": '<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="size-6"><path stroke-linecap="round" stroke-linejoin="round" d="M6.75 3v2.25M17.25 3v2.25M3 18.75V7.5a2.25 2.25 0 0 1 2.25-2.25h13.5A2.25 2.25 0 0 1 21 7.5v11.25m-18 0A2.25 2.25 0 0 0 5.25 21h13.5A2.25 2.25 0 0 0 21 18.75m-18 0v-7.5A2.25 2.25 0 0 1 5.25 9h13.5A2.25 2.25 0 0 1 21 11.25v7.5m-9-6h.008v.008H12v-.008ZM12 15h.008v.008H12V15Zm0 2.25h.008v.008H12v-.008ZM9.75 15h.008v.008H9.75V15Zm0 2.25h.008v.008H9.75v-.008ZM7.5 15h.008v.008H7.5V15Zm0 2.25h.008v.008H7.5v-.008Zm6.75-4.5h.008v.008h-.008v-.008Zm0 2.25h.008v.008h-.008V15Zm0 2.25h.008v.008h-.008v-.008Zm2.25-4.5h.008v.008H16.5v-.008Zm0 2.25h.008v.008H16.5V15Z" /></svg>',
}


def _played_row(game: Game, request: HttpRequest) -> Node:
    """'Played N times' split button: a generic outlined Dropdown wrapped in
    <play-event-row>, which owns only the 'Played +1' action."""
    from common.components import (
        ControlButton,
        DropdownActionItem,
        DropdownLinkItem,
        SplitButtonDropdown,
    )
    from common.components.custom_elements import _PlayEventRow

    played = game.playevents.count()

    count_button = ControlButton(
        [("class", "rounded-s-lg")],
        variant="outline",
        href=reverse("games:add_playevent"),
    )[
        # One prose phrase = one flex item: the button is inline-flex, and flex
        # layout drops whitespace-only text between items, so the space must
        # live inside a single inline context. The inner span is a write-only
        # display slot for play-event-row.ts.
        Span()[Span(data_count="")[str(played)], " times"]
    ]
    dropdown = SplitButtonDropdown(
        primary=count_button,
        id=f"played-{game.id}",
        aria_label="Playthrough actions",
        items=[
            DropdownLinkItem(
                reverse("games:add_playevent_for_game", args=[game.id]),
                "Add playthrough...",
            ),
            DropdownActionItem(data_add_play="")["Played times +1"],
        ],
    )
    return _PlayEventRow(
        game_id=game.id,
        count=played,
        csrf=get_token(request),
        api_create_url=reverse("api-1.0.0:create_playevent"),
    )[
        Div(class_="flex gap-2 items-center")[
            Span(class_="uppercase")["Played"], dropdown
        ]
    ]


def _stat_popover(popover_id: str, tooltip: str, svg_key: str, value: str) -> Node:
    return Popover(
        popover_content=tooltip,
        wrapped_classes="flex gap-2 items-center",
        id=popover_id,
        children=[Safe(_STAT_SVGS[svg_key]), str(value)],
    )


def _meta_row(label: str, value: Node | str, extra: Node | str = "") -> Node:
    children: list[Node | str] = [
        Span(class_="uppercase")[label],
        value,
    ]
    if extra:
        children.append(extra)
    return Div(class_="flex gap-2 items-center")[*children]


def _game_action_buttons(game: Game) -> Node:
    # A segmented button group, same component as the table Actions cells. The
    # group owns position-based rounding and hover styling; margin is ours.
    return Div(class_="mb-3")[
        ButtonGroup(
            [
                {
                    "href": reverse(
                        "games:add_session_for_game", kwargs={"game_id": game.id}
                    ),
                    "slot": Span(class_="inline-flex items-center gap-1")[
                        Icon("play", size=ICON_BUTTON_SIZE_CLASS), "Log this game"
                    ],
                    "color": "green",
                },
                {
                    "href": reverse("games:edit_game", args=[game.id]),
                    "slot": "Edit",
                    "color": "gray",
                },
                {
                    "href": "#",
                    "slot": "Delete",
                    "color": "red",
                    "hx_get": reverse("games:delete_game_confirmation", args=[game.id]),
                    "hx_target": "#global-modal-container",
                },
            ],
        )
    ]


def _game_history(statuschanges: QuerySet[GameStatusChange]) -> Node:
    items = []
    for change in statuschanges:
        if change.timestamp:
            prefix = f"{date_filter(change.timestamp, 'd/m/Y H:i')}: Changed"
        else:
            prefix = "At some point changed"
        old_status = GameStatus(
            status=change.old_status or "u",
            children=[change.get_old_status_display() if change.old_status else "-"],
        )
        new_status = GameStatus(
            status=change.new_status,
            children=[change.get_new_status_display()],
        )
        edit = A(href=reverse("games:edit_statuschange", args=[change.id]))["Edit"]
        delete = A(href=reverse("games:delete_statuschange", args=[change.id]))[
            "Delete"
        ]
        items.append(
            Li(class_="text-slate-500")[
                f"{prefix} status from",
                old_status,
                "to",
                new_status,
                "(",
                edit,
                ", ",
                delete,
                ")",
            ]
        )
    return Ul(class_="list-disc list-inside")[*items]


def _game_section(
    title: str,
    count: int,
    table: Node,
    empty_message: str,
    view_all_url: str | None = None,
) -> Node:
    if view_all_url and count:
        view_all_link = ControlButton(
            href=view_all_url,
            color="gray",
            title=f"View all {title.lower()} for this game",
        )[
            Icon("arrowright", size=ICON_BUTTON_SIZE_CLASS),
            "View all",
        ]
        header = Div(class_="flex items-center justify-between mb-2")[
            PageHeading(children=[title], badge=str(count) if count else ""),
            view_all_link,
        ]
    else:
        header = PageHeading(children=[title], badge=str(count) if count else "")
    return Div(class_="mb-6")[
        header,
        table if count else empty_message,
    ]


def _game_overview_metrics(game: Game) -> dict[str, Any]:
    """Request-free header metrics: total session count, play range, and the
    per-session average (excluding manually-logged sessions)."""
    sessions = game.sessions
    session_count = sessions.count()
    session_count_without_manual = sessions.without_manual().count()

    if sessions.exists():
        start = local_strftime(sessions.earliest().timestamp_start, "%b %Y")
        end = local_strftime(sessions.latest().timestamp_start, "%b %Y")
        playrange = start if start == end else f"{start} — {end}"
    else:
        playrange = "N/A"

    total_hours_without_manual = float(
        format_duration(sessions.calculated_duration_unformatted(), "%2.1H")
    )
    session_average_without_manual = round(
        safe_division(total_hours_without_manual, int(session_count_without_manual)), 1
    )
    return {
        "session_count": session_count,
        "playrange": playrange,
        "session_average_without_manual": session_average_without_manual,
    }


def _game_header(game: Game, request: HttpRequest, metrics: dict[str, Any]) -> Node:
    grey_value_class = "text-black dark:text-slate-300"
    title_span = Span(class_="text-balance max-w-120 text-lg lg:text-4xl")[
        *(
            [
                Span(class_="font-bold font-serif")[game.name],
            ]
            + (
                [
                    Safe("&nbsp;"),
                    Popover(
                        popover_content="Original release year",
                        wrapped_classes="text-slate-500 text-base lg:text-2xl",
                        id="popover-year",
                        children=[str(game.year_released)],
                    ),
                ]
                if game.year_released
                else []
            )
        )
    ]
    stats_row = Div(class_="flex gap-4 text-xs lg:text-lg dark:text-slate-400 mb-3")[
        _stat_popover(
            "popover-hours",
            "Total hours played",
            "hours",
            game.playtime_formatted(),
        ),
        _stat_popover(
            "popover-sessions",
            "Number of sessions",
            "sessions",
            metrics["session_count"],
        ),
        _stat_popover(
            "popover-average",
            "Average playtime per session",
            "average",
            metrics["session_average_without_manual"],
        ),
        _stat_popover(
            "popover-playrange",
            "Earliest and latest dates played",
            "playrange",
            metrics["playrange"],
        ),
    ]
    metadata = Div(
        class_="flex flex-col mb-6 text-gray-600 dark:text-slate-400 gap-y-4 text-xs lg:text-base",
    )[
        _meta_row(
            "Original year",
            Span(class_=grey_value_class)[str(game.original_year_released)],
        ),
        _meta_row(
            "Status",
            Span(class_="text-xs")[
                GameStatusSelector(
                    game, Game.Status.choices, get_token(request), class_="text-xs"
                )
            ],
            "👑" if game.mastered else "",
        ),
        _played_row(game, request),
        _meta_row(
            "Platform",
            Span(class_=grey_value_class)[
                str(game.platform) if game.platform else "Unspecified"
            ],
        ),
    ]
    return Div(id_="game-info", class_="mb-10")[
        Div(class_="flex gap-5 mb-3")[title_span],
        stats_row,
        metadata,
        _game_action_buttons(game),
    ]


def _purchases_section(game: Game) -> Node:
    purchases = game.purchases.order_by("date_purchased")
    rows = [
        make_row(
            LinkedPurchase(purchase),
            purchase.get_type_display(),
            purchase.date_purchased.strftime(dateformat),
            PurchasePrice(purchase),
            ButtonGroup(
                [
                    {
                        "href": reverse("games:edit_purchase", args=[purchase.pk]),
                        "slot": Icon("edit", size=ICON_BUTTON_SIZE_CLASS),
                        "color": "gray",
                    },
                    {
                        "href": reverse("games:delete_purchase", args=[purchase.pk]),
                        "slot": Icon("delete", size=ICON_BUTTON_SIZE_CLASS),
                        "color": "red",
                    },
                ]
            ),
        )
        for purchase in purchases
    ]
    table = StyledTable(
        columns=[
            Column("Name"),
            Column("Type"),
            Column("Date"),
            Column("Price"),
            Column("Actions", align="right"),
        ],
        rows=rows,
    )
    return _game_section(
        "Purchases",
        purchases.count(),
        table,
        "No purchases yet.",
        view_all_url=filter_url(PurchaseFilter.where(games=[game.id])),
    )


def _sessions_section(game: Game) -> Node:
    sessions = game.sessions.select_related("device").order_by("-timestamp_start")
    session_count = sessions.count()
    rows = [
        make_row(
            session_time_range(session),
            session.duration_formatted_with_mark(),
            session.device.name if session.device else "No device",
        )
        for session in sessions[:5]
    ]
    table = StyledTable(
        columns=[
            Column("Date"),
            Column("Duration"),
            Column("Device"),
        ],
        rows=rows,
    )
    return _game_section(
        "Sessions",
        session_count,
        table,
        "No sessions yet.",
        view_all_url=filter_url(SessionFilter.where(game=[game.id])),
    )


def _playevents_section(game: Game) -> Node:
    playevents = game.playevents.all()
    data = create_playevent_tabledata(playevents, exclude_columns=["Game"])
    # This embedded mini-table isn't a sortable list view (no ?sort= handling on
    # the detail page), so render plain headers like the sibling sections do —
    # drop the sort keys the shared list-view builder now sets (#343).
    plain_columns = [column._replace(sort_key=None) for column in data["columns"]]
    table = StyledTable(columns=plain_columns, rows=data["rows"])
    section = _game_section(
        "Play Events",
        playevents.count(),
        table,
        "No play events yet.",
        view_all_url=filter_url(PlayEventFilter.where(game=[game.id])),
    )
    # Re-fetch this section (table + count badge) when the played-row "+1"
    # control records a play, so it updates without a full reload. Mirrors the
    # history section's status-changed refresh.
    return Div(
        id_="playevents-container",
        hx_get="",
        hx_trigger="play-added from:body",
        hx_select="#playevents-container",
        hx_swap="outerHTML",
    )[section]


def _history_section(game: Game) -> Node:
    statuschanges: QuerySet[GameStatusChange] = game.status_changes.all()
    count = statuschanges.count()
    return Div(
        class_="mb-6",
        id="history-container",
        hx_get="",
        hx_trigger="status-changed from:body",
        hx_select="#history-container",
        hx_swap="outerHTML",
    )[
        PageHeading(children=["History"], badge=str(count) if count else ""),
        _game_history(statuschanges),
    ]


@login_required
def view_game(request: HttpRequest, game_id: int) -> HttpResponse:
    game = Game.objects.get(id=game_id)
    content = ContentContainer(class_="dark:text-white")[
        _game_header(game, request, _game_overview_metrics(game)),
        _purchases_section(game),
        _sessions_section(game),
        _playevents_section(game),
        _history_section(game),
    ]
    request.session["return_path"] = request.path
    return render_page(
        request,
        content,
        title=f"Game Overview - {game.name}",
        mastered=game.mastered,
    )
