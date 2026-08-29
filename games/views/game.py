from collections.abc import Sequence
from datetime import timedelta
from functools import partial
from typing import Any, NoReturn, cast
from uuid import UUID

from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db.models import F, OuterRef, Q, QuerySet, Subquery, Sum
from django.http import Http404, HttpRequest, HttpResponse
from django.middleware.csrf import get_token
from django.shortcuts import redirect
from django.urls import reverse

from common.components import (
    ICON_BUTTON_SIZE_CLASS,
    AddForm,
    ButtonGroup,
    Column,
    ContentContainer,
    ControlButton,
    Div,
    Duration,
    DurationAlternates,
    DurationText,
    Fragment,
    GameStatus,
    GameStatusSelector,
    Icon,
    Link,
    LinkedPurchase,
    ModuleScript,
    NameWithIcon,
    Node,
    PageHeading,
    Popover,
    PurchasePrice,
    QuickFilterBar,
    Safe,
    StyledTable,
    TableData,
    Ul,
    make_row,
    paginated_table_content,
    parse_filter_dict,
)
from common.components.primitives import Li, Span
from common.date_time_presentation import (
    DateTimePresentation,
    date_time_presentation_for_request,
)
from common.duration_presentation import (
    DurationPresentation,
    duration_presentation_for_request,
)
from common.filter_execution import execute_filter, regex_timeout_view
from common.layout import render_page
from common.returns import OriginUrl, action_url
from common.utils import paginate, safe_division
from games.catalog_compat import save_legacy_game_form
from games.external_references import external_reference_url
from games.filters import (
    PlayEventFilter,
    PurchaseFilter,
    SessionFilter,
    filter_query_context_for_library,
    filter_url,
    parse_game_filter,
)
from games.formatting import session_time_range
from games.forms import GameForm
from games.models import (
    Game,
    PlayerGameStatus,
    PlayEvent,
    Purchase,
    Session,
    SessionQuerySet,
    UserLibrary,
)
from games.ownership import owned_or_404
from games.reads.playergame_history import StatusEntry, status_history
from games.sorting import GAME_DEFAULT_SORT, GAME_SORTS, apply_sort, parse_find_filter
from games.views.filtering import (
    apply_structured_filter,
    builder_url_for,
    warn_unknown_sort,
)
from games.views.playergame_writes import (
    record_facts_for_request,
    remove_game_for_request,
    track_game_for_request,
)
from games.views.playevent import create_playevent_tabledata
from games.views.removal import confirm_and_remove
from games.views.returns import origin_from, return_url
from games.writes.playergame import new_correlation_id

WIKIDATA_CONFLICT_MESSAGE = "This Wikidata entity ID already belongs to another game."


def _save_game_form_or_add_wikidata_error(form: GameForm) -> Game | None:
    try:
        return save_legacy_game_form(form)
    except ValidationError as error:
        if not hasattr(error, "message_dict") or set(error.message_dict) != {
            "provider_key"
        }:
            raise
        form.add_error("wikidata", WIKIDATA_CONFLICT_MESSAGE)
        return None


@login_required
@regex_timeout_view
def list_games(request: HttpRequest) -> HttpResponse:
    library = cast(User, request.user).library
    presentation = date_time_presentation_for_request(request)
    durations = duration_presentation_for_request(request)
    origin = request.get_full_path()
    games = Game.objects.tracked_by(library).select_related("platform")

    # Playtime column sums only the sessions matching the active session
    # sub-filter; an empty Q matches every session, so with no session filter the
    # column shows total playtime.
    session_q = Q()

    # ── Structured filter (Stash-style JSON; free-text search lives here too) ──
    filter_json = request.GET.get("filter", "")
    if filter_json:
        game_filter = apply_structured_filter(request, parse_game_filter, filter_json)
        if game_filter is not None:
            context = filter_query_context_for_library(library)
            games = execute_filter(game_filter, games, context)
            if game_filter.session_filter is not None:
                session_q = game_filter.session_filter.to_q(context)

    # Per-game playtime restricted to the session sub-filter, summed in the DB.
    # session_q stays in Session's own field namespace via the correlated
    # subquery, so no `sessions__` path-prefixing is needed.
    windowed_playtime = (
        Session.objects.for_library(library)
        .filter(session_q, game=OuterRef("pk"))
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
        "caption": "Games",
        "columns": [
            Column("Name", "name", shrinkable=True),
            Column("Year", "year", priority=2),
            Column("Playtime", "filtered_playtime", priority=2),
            Column("Status", "status", priority=3),
            Column("Wikidata", "wikidata"),
            Column("Created", "created"),
            Column("Actions", align="right", priority=4),
        ],
        "sort_terms": sort.terms,
        "rows": [
            make_row(
                NameWithIcon(game=game, include_sort_name=True),
                str(game.year_released),
                Duration(
                    game.filtered_playtime or timedelta(0),
                    durations,
                    id_scope=f"game-{game.pk}-playtime",
                ),
                GameStatusSelector(
                    game,
                    PlayerGameStatus.choices,
                    get_token(request),
                    current=game.tracked_status,
                ),
                Link(
                    href=external_reference_url(
                        provider="wikidata",
                        entity_kind="game",
                        provider_key=game.wikidata,
                    )
                )[game.wikidata]
                if game.wikidata
                else "",
                presentation.format(game.created_at, "date"),
                ButtonGroup(
                    [
                        {
                            "href": action_url(
                                "games:edit_game", game.pk, origin=origin
                            ),
                            "slot": Icon("edit", size=ICON_BUTTON_SIZE_CLASS),
                            "color": "gray",
                        },
                        {
                            "href": action_url(
                                "games:remove_game", game.pk, origin=origin
                            ),
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
    builder_url = builder_url_for(
        "games", filter_json, find.sort, find.per_page_override
    )
    parsed_filter = parse_filter_dict(filter_json)
    quick_bar = QuickFilterBar(
        presentation=presentation,
        mode="games",
        existing=parsed_filter,
        builder_url=builder_url,
        preset_api_url=reverse("api-1.0.0:list_presets"),
        per_page_override=find.per_page_override,
    )
    content = ContentContainer()[quick_bar, content]
    return render_page(
        request,
        content,
        title="Manage games",
    )


@login_required
def add_game(request: HttpRequest) -> HttpResponse:
    library = cast(User, request.user).library
    form = GameForm(request.POST or None, library=library)
    if form.is_valid():
        game = _save_game_form_or_add_wikidata_error(form)
        if game is not None:
            correlation_id = new_correlation_id()
            if not track_game_for_request(request, game, correlation_id=correlation_id):
                #: Nothing tracks it, so no read reaches it: the list
                #: joins the projection and the detail page answers
                #: 404, while the name goes on holding the unique
                #: constraint against a second attempt. Undo the
                #: insert rather than leave a row only the database
                #: can see. No event names it, so this really deletes.
                game.delete()
                return redirect(return_url(request, fallback="games:list_games"))
            recorded = record_facts_for_request(
                request,
                game,
                status=form.cleaned_data["status"],
                mastered=form.cleaned_data["mastered"],
                correlation_id=correlation_id,
            )
            if not recorded:
                #: Re-rendering would invite a second game.
                return redirect(return_url(request, fallback="games:list_games"))
            origin = origin_from(request)
            if "submit_and_redirect" in request.POST:
                return redirect(
                    action_url(
                        "games:add_purchase_for_game", game_id=game.id, origin=origin
                    )
                )
            elif "submit_and_create_session" in request.POST:
                return redirect(
                    action_url(
                        "games:add_session_for_game", game_id=game.id, origin=origin
                    )
                )
            return redirect(return_url(request, fallback="games:list_games"))

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


@login_required
def remove_game(request: HttpRequest, game_id: UUID) -> HttpResponse:
    library = cast(User, request.user).library
    game = owned_or_404(Game.objects.for_library(library), library, id=game_id)
    return confirm_and_remove(
        request,
        game,
        title="Remove game",
        message=f"Remove {game.name} from your library?",
        details=_removed_with_game(game),
        fallback="games:list_games",
        detail_url=game.get_absolute_url(),
        action=partial(remove_game_for_request, request, game),
    )


def _removed_with_game(game: Game) -> Node:
    counts = [
        (game.sessions.alive().count(), "session"),
        (game.purchases.alive().count(), "purchase"),
        (game.playevents.alive().count(), "play event"),
    ]
    present = [Li()[f"{count} {label}(s)"] for count, label in counts if count]
    return Ul()[*(present or [Li()["No associated data"]])]


@login_required
def edit_game(request: HttpRequest, game_id: UUID) -> HttpResponse:
    library = cast(User, request.user).library
    game = owned_or_404(Game.objects.for_library(library), library, id=game_id)
    form = GameForm(request.POST or None, instance=game, library=library)
    if (
        form.is_valid()
        and _save_game_form_or_add_wikidata_error(form) is not None
        and record_facts_for_request(
            request,
            game,
            status=form.cleaned_data["status"],
            mastered=form.cleaned_data["mastered"],
            correlation_id=new_correlation_id(),
        )
    ):
        return redirect(return_url(request, fallback="games:list_games"))
    #: A failed command lands here too: redirecting would read as
    #: a save. An edit resubmits onto the same row, so re-rendering
    #: invites no duplicate.
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


def _played_row(game: Game, request: HttpRequest, origin: OriginUrl | None) -> Node:
    """'Played N times' split button: a generic outlined Dropdown wrapped in
    <play-event-row>, which owns only the 'Played +1' action."""
    from common.components import (
        ControlButton,
        DropdownActionItem,
        DropdownLinkItem,
        SplitButtonDropdown,
    )
    from common.components.custom_elements import _PlayEventRow

    played = game.playevents.alive().count()

    count_button = ControlButton(
        [("class", "rounded-s-lg")],
        variant="outline",
        href=action_url("games:add_playevent", origin=origin),
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
                action_url("games:add_playevent_for_game", game.id, origin=origin),
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


def _stat_popover(
    popover_id: str,
    tooltip: str,
    svg_key: str,
    value: Node | str,
    details: Node | None = None,
) -> Node:
    """One header stat. ``details`` adds rows beneath the tooltip line — the
    playtime stat puts its alternate formats there rather than nesting a second
    popover inside this one."""
    content: Node | str = (
        tooltip
        if details is None
        else Div(class_="flex flex-col gap-1")[tooltip, details]
    )
    return Popover(
        popover_content=content,
        wrapped_classes="flex gap-2 items-center",
        id=popover_id,
        children=[Safe(_STAT_SVGS[svg_key]), value],
    )


def _meta_row(label: str, value: Node | str, extra: Node | str = "") -> Node:
    children: list[Node | str] = [
        Span(class_="uppercase")[label],
        value,
    ]
    if extra:
        children.append(extra)
    return Div(class_="flex gap-2 items-center")[*children]


def _game_action_buttons(game: Game, origin: OriginUrl | None) -> Node:
    # A segmented button group, same component as the table Actions cells. The
    # group owns position-based rounding and hover styling; margin is ours.
    return Div(class_="mb-3")[
        ButtonGroup(
            [
                {
                    "href": action_url(
                        "games:add_session_for_game", game_id=game.id, origin=origin
                    ),
                    "slot": Span(class_="inline-flex items-center gap-1")[
                        Icon("play", size=ICON_BUTTON_SIZE_CLASS), "Log this game"
                    ],
                    "color": "green",
                },
                {
                    "href": action_url("games:edit_game", game.id, origin=origin),
                    "slot": "Edit",
                    "color": "gray",
                },
                {
                    "href": action_url("games:remove_game", game.id, origin=origin),
                    "slot": "Delete",
                    "color": "red",
                },
            ],
        )
    ]


def _game_history(
    entries: Sequence[StatusEntry], presentation: DateTimePresentation
) -> Node:
    items = []
    for entry in entries:
        if entry.recorded_at:
            prefix = f"{presentation.format(entry.recorded_at, 'datetime')}: Changed"
        else:
            prefix = "At some point changed"
        items.append(
            Li(class_="text-slate-500")[
                f"{prefix} status from",
                GameStatus(status=entry.previous, children=[entry.previous.label]),
                "to",
                GameStatus(status=entry.current, children=[entry.current.label]),
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
        # No margin: the section wrapper's gap owns the distance to the table, so
        # a section with a "View all" button spaces exactly like one without.
        header = Div(class_="flex items-center justify-between")[
            PageHeading(children=[title], badge=str(count) if count else ""),
            view_all_link,
        ]
    else:
        header = PageHeading(children=[title], badge=str(count) if count else "")
    return Div(class_="mb-6 flex flex-col gap-4")[
        header,
        table if count else empty_message,
    ]


def _game_overview_metrics(sessions: SessionQuerySet) -> dict[str, Any]:
    """Request-free header metrics: total session count, play range, and the
    per-session average (excluding manually-logged sessions)."""
    session_count = sessions.count()
    session_count_without_manual = sessions.without_manual().count()

    playrange_start = sessions.earliest().timestamp_start if sessions.exists() else None
    playrange_end = sessions.latest().timestamp_start if sessions.exists() else None

    calculated_total = sessions.calculated_duration_unformatted() or timedelta(0)
    total_hours_without_manual = calculated_total.total_seconds() / 3600
    session_average_without_manual = round(
        safe_division(total_hours_without_manual, int(session_count_without_manual)), 1
    )
    return {
        "session_count": session_count,
        "playrange_start": playrange_start,
        "playrange_end": playrange_end,
        "session_average_without_manual": session_average_without_manual,
    }


def _game_header(
    game: Game,
    request: HttpRequest,
    metrics: dict[str, Any],
    presentation: DateTimePresentation,
    durations: DurationPresentation,
    origin: OriginUrl | None,
) -> Node:
    playrange_start = metrics["playrange_start"]
    playrange_end = metrics["playrange_end"]
    if playrange_start and playrange_end:
        start = presentation.format(playrange_start, "month_year")
        end = presentation.format(playrange_end, "month_year")
        playrange = start if start == end else f"{start} — {end}"
    else:
        playrange = "N/A"
    grey_value_class = "text-black dark:text-slate-300"
    title_span = Span(class_="text-balance max-w-120")[
        *(
            [
                Span(class_="text-type-title font-serif")[game.name],
            ]
            + (
                [
                    Safe("&nbsp;"),
                    Popover(
                        popover_content="Original release year",
                        wrapped_classes="text-type-subheading text-slate-500",
                        id="popover-year",
                        children=[str(game.year_released)],
                    ),
                ]
                if game.year_released
                else []
            )
        )
    ]
    stats_row = Div(class_="flex gap-4 text-type-body dark:text-slate-400 mb-3")[
        _stat_popover(
            "popover-hours",
            "Total hours played",
            "hours",
            DurationText(game.playtime, durations),
            DurationAlternates(game.playtime, durations),
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
            playrange,
        ),
    ]
    metadata = Div(
        class_="flex flex-col mb-6 text-gray-600 dark:text-slate-400 gap-y-4 text-type-body",
    )[
        _meta_row(
            "Original year",
            Span(class_=grey_value_class)[str(game.original_year_released)],
        ),
        _meta_row(
            "Status",
            Span()[
                GameStatusSelector(
                    game,
                    PlayerGameStatus.choices,
                    get_token(request),
                    current=game.tracked_status,
                )
            ],
            "👑" if game.tracked_mastered else "",
        ),
        _played_row(game, request, origin),
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
        _game_action_buttons(game, origin),
    ]


def _purchases_section(
    game: Game,
    purchases: QuerySet[Purchase],
    presentation: DateTimePresentation,
    origin: OriginUrl | None,
) -> Node:
    purchases = purchases.order_by("date_purchased")
    rows = [
        make_row(
            LinkedPurchase(purchase),
            purchase.get_type_display(),
            presentation.format(purchase.date_purchased, "date"),
            PurchasePrice(purchase),
            ButtonGroup(
                [
                    {
                        "href": action_url(
                            "games:edit_purchase", purchase.pk, origin=origin
                        ),
                        "slot": Icon("edit", size=ICON_BUTTON_SIZE_CLASS),
                        "color": "gray",
                    },
                    {
                        "href": action_url(
                            "games:remove_purchase", purchase.pk, origin=origin
                        ),
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
            Column("Name", shrinkable=True),
            Column("Type"),
            Column("Date", priority=2),
            Column("Price", priority=2),
            Column("Actions", align="right", priority=3),
        ],
        rows=rows,
        data_table=True,
        caption="Purchases of this game",
    )
    return _game_section(
        "Purchases",
        purchases.count(),
        table,
        "No purchases yet.",
        view_all_url=filter_url(PurchaseFilter.where(games=[game.id])),
    )


def _sessions_section(
    game: Game,
    sessions: SessionQuerySet,
    presentation: DateTimePresentation,
    durations: DurationPresentation,
) -> Node:
    sessions = sessions.select_related("device").order_by("-timestamp_start")
    session_count = sessions.count()
    rows = [
        make_row(
            session_time_range(session, presentation),
            Duration(
                session.duration_total,
                durations,
                id_scope=f"game-session-{session.pk}",
                manual=session.is_manual(),
            ),
            session.device.name if session.device else "No device",
        )
        for session in sessions[:5]
    ]
    table = StyledTable(
        columns=[
            Column("Date"),
            Column("Duration", priority=2),
            Column("Device"),
        ],
        rows=rows,
        data_table=True,
        caption="Recent sessions of this game",
    )
    return _game_section(
        "Sessions",
        session_count,
        table,
        "No sessions yet.",
        view_all_url=filter_url(SessionFilter.where(game=[game.id])),
    )


def _playevents_section(
    game: Game,
    playevents: QuerySet[PlayEvent],
    presentation: DateTimePresentation,
    origin: OriginUrl | None,
) -> Node:
    data = create_playevent_tabledata(
        playevents, presentation, exclude_columns=["Game"], origin=origin
    )
    # This embedded mini-table isn't a sortable list view (no ?sort= handling on
    # the detail page), so render plain headers like the sibling sections do —
    # drop the sort keys the shared list-view builder now sets (#343).
    plain_columns = [column._replace(sort_key=None) for column in data["columns"]]
    table = StyledTable(
        columns=plain_columns,
        rows=data["rows"],
        data_table=True,
        caption="Play events of this game",
    )
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


def _history_section(
    game: Game, library: UserLibrary, presentation: DateTimePresentation
) -> Node:
    #: A stream belongs to one library.
    entries = status_history(library, game)
    count = len(entries)
    return Div(
        class_="mb-6 flex flex-col gap-4",
        id="history-container",
        hx_get="",
        hx_trigger="status-changed from:body",
        hx_select="#history-container",
        hx_swap="outerHTML",
    )[
        PageHeading(children=["History"], badge=str(count) if count else ""),
        _game_history(entries, presentation),
    ]


@login_required
def view_game(request: HttpRequest, game_id: UUID, slug: str) -> HttpResponse:
    library = cast(User, request.user).library
    game = owned_or_404(Game.objects.tracked_by(library), library, id=game_id)
    if slug != game.url_slug:
        return _canonical_game_redirect(request, game)
    presentation = date_time_presentation_for_request(request)
    durations = duration_presentation_for_request(request)
    origin = request.get_full_path()
    #: Scoped, not `game.sessions` and friends: tracked_by() admits a
    #: shared catalog game, and a shared game's reverse accessors reach
    #: every library that ever wrote against it.
    sessions = cast(
        SessionQuerySet, Session.objects.for_library(library).filter(game=game)
    )
    purchases = Purchase.objects.for_library(library).filter(games=game)
    playevents = PlayEvent.objects.for_library(library).filter(game=game)
    content = ContentContainer(class_="dark:text-white")[
        _game_header(
            game,
            request,
            _game_overview_metrics(sessions),
            presentation,
            durations,
            origin,
        ),
        _purchases_section(game, purchases, presentation, origin),
        _sessions_section(game, sessions, presentation, durations),
        _playevents_section(game, playevents, presentation, origin),
        _history_section(game, library, presentation),
    ]
    return render_page(
        request,
        content,
        title=f"Game Overview - {game.name}",
        mastered=game.tracked_mastered,
    )


def _canonical_game_redirect(request: HttpRequest, game: Game) -> HttpResponse:
    target = game.get_absolute_url()
    query = request.GET.urlencode()
    if query:
        target = f"{target}?{query}"
    return redirect(target, permanent=True)


def retired_game_view(request: HttpRequest, game_id: UUID) -> NoReturn:
    raise Http404
