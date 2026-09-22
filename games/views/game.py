from collections.abc import Sequence
from datetime import timedelta
from functools import partial
from typing import Any, NamedTuple, NoReturn, cast
from uuid import UUID

from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db.models import Count, F, Max, Min, QuerySet, Sum
from django.http import Http404, HttpRequest, HttpResponse
from django.middleware.csrf import get_token
from django.shortcuts import redirect
from django.urls import reverse
from django.views.decorators.http import require_POST

from common.components import (
    ICON_BUTTON_SIZE_CLASS,
    AddForm,
    ButtonGroup,
    Cell,
    Column,
    ContentContainer,
    ControlButton,
    Div,
    Duration,
    DurationAlternates,
    DurationText,
    ExternalReferenceLinks,
    FormFields,
    Fragment,
    GameStatus,
    GameStatusSelector,
    Icon,
    Link,
    LinkedPurchase,
    ModuleScript,
    NameWithIcon,
    Node,
    P,
    PageHeading,
    PlaytimeHalves,
    Popover,
    PurchasePrice,
    QuickFilterBar,
    Safe,
    SelectionDeclaration,
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
from common.temporal_presentation import (
    UNKNOWN_TEXT,
    TemporalText,
    present_temporal_value,
)
from common.utils import paginate, safe_division
from games.bulk_removal import REMOVE_RECORD, REMOVE_RUN
from games.bulk_tray import tray_actions
from games.catalog_form import CatalogGraphForm
from games.catalog_submit import submitted_game_or_form_error
from games.external_references import CatalogTarget, external_reference_url_or_none
from games.filters import (
    FindFilter,
    GameFilter,
    HistoricalPlaytimeFilter,
    NarrowingClauses,
    PlayerSessionFilter,
    PlaythroughFilter,
    PurchaseFilter,
    filter_query_context_for_library,
    filter_url,
    parse_game_filter,
)
from games.formatting import session_time_range
from games.forms import GameForm
from games.models import (
    ExternalReference,
    Game,
    PlayerGameStatus,
    PlayerSessionQuerySet,
    PlayerSessionTimingMode,
    Playthrough,
    Purchase,
    Release,
    UserLibrary,
)
from games.ownership import owned_or_404
from games.reads.catalog_hierarchy import EditionEntry, game_hierarchy
from games.reads.external_references import ReferenceMap, held_by, references_for
from games.reads.historical_playtime_page import (
    listed_records,
    run_labels_for,
)
from games.reads.historical_playtime_records import RECORD_ORDER
from games.reads.player_sessions import game_sessions
from games.reads.playergame_history import StatusEntry, status_history
from games.reads.playthrough_activity import ActivityClock, activity_clock
from games.reads.playthrough_completions import GAME_RUNS, reported_completion_day
from games.reads.playthrough_numbering import numbered_for
from games.reads.playthrough_runs import live_ordinary_runs, tracked_game
from games.reads.playtime import (
    game_playtime,
    playtime_matching_both,
    playtime_sort_key,
)
from games.reads.sums import PlaytimeBreakdown
from games.reference_form import ReferenceSetForm
from games.sorting import (
    GAME_DEFAULT_SORT,
    GAME_SORTS,
    SortResult,
    apply_sort,
    parse_find_filter,
)
from games.views.catalog_section import editions_area
from games.views.filtering import (
    apply_structured_filter,
    builder_url_for,
    warn_unknown_sort,
)
from games.views.historical_playtime import (
    historical_playtime_tabledata,
)
from games.views.playergame_writes import (
    record_facts_for_request,
    remove_game_for_request,
    restore_game_for_request,
    track_game_for_request,
)
from games.views.playthrough_rows import playthrough_tabledata
from games.views.reference_section import references_area
from games.views.removal import confirm_and_remove, restore_and_return
from games.views.returns import origin_from, return_url
from games.writes.playergame import new_correlation_id

#: The value half of a meta row.
META_VALUE_CLASS = "text-heading"
#: No Platform is a fact, not blank.
UNSPECIFIED_PLATFORM = "Unspecified"
#: Said on the page, because the shape is not final.
EDITIONS_UNDER_CONSTRUCTION = (
    "Under construction. These are catalog facts only. A session cannot name "
    "an edition yet, so no playtime is shown here and this layout will change. "
    "A platform beyond the first one does not reach the games list yet."
)


def _wikidata_cell(provider_key: str) -> Cell:
    """The mirror column, linked where it links."""
    if not provider_key:
        return ""
    url = external_reference_url_or_none(
        provider="wikidata", entity_kind="game", provider_key=provider_key
    )
    return Link(href=url)[provider_key] if url is not None else provider_key


type ColumnLabel = str  # e.g. "Playtime"


class GameList(NamedTuple):
    sort: SortResult
    #: Names what the Playtime column sums.
    playtime_label: ColumnLabel


def games_for_list(
    library: UserLibrary, *, game_filter: GameFilter | None, find: FindFilter
) -> GameList:
    """The list's queryset: filtered, annotated, sorted, unpaged.

    One function, so the benchmark times the plan the page serves.
    """
    games = Game.objects.tracked_by(library).select_related("platform")
    #: Narrows the Playtime column; none counts all.
    clauses = NarrowingClauses(None, None)
    if game_filter is not None:
        context = filter_query_context_for_library(library)
        games = execute_filter(game_filter, games, context)
        clauses = game_filter.narrowing()
    playtime_label = "Playtime"
    if clauses.sessions is None and clauses.records is None:
        #: The sort reuses the column's subqueries.
        games = games.annotate(filtered_playtime=playtime_sort_key(library)).alias(
            total_playtime=F("filtered_playtime")
        )
    else:
        playtime_label = (
            "Playtime (matching sessions)"
            if clauses.records is None
            else "Playtime (matching)"
        )
        #: An alias: only `?sort=playtime` reads it.
        games = games.alias(total_playtime=playtime_sort_key(library)).annotate(
            filtered_playtime=playtime_matching_both(
                library, clauses.sessions, clauses.records
            )
        )
    #: No column renders it; `?sort=finished` reads it.
    games = games.annotate(completed_day=reported_completion_day(library, GAME_RUNS))
    return GameList(
        apply_sort(games, find, GAME_SORTS, GAME_DEFAULT_SORT), playtime_label
    )


@login_required
@regex_timeout_view
def list_games(request: HttpRequest) -> HttpResponse:
    library = cast(User, request.user).library
    presentation = date_time_presentation_for_request(request)
    durations = duration_presentation_for_request(request)
    origin = request.get_full_path()

    # ── Structured filter (Stash-style JSON; free-text search lives here too) ──
    filter_json = request.GET.get("filter", "")
    game_filter: GameFilter | None = None
    if filter_json:
        game_filter = apply_structured_filter(request, parse_game_filter, filter_json)

    find = parse_find_filter(request)
    listed = games_for_list(library, game_filter=game_filter, find=find)
    sort = listed.sort
    warn_unknown_sort(request, sort.unknown, entity="game")

    games, page_obj, elided_page_range = paginate(sort.queryset, find)

    data: TableData = {
        "caption": "Games",
        "columns": [
            Column("Name", "name", shrinkable=True),
            Column("Year", "year", priority=2),
            Column(listed.playtime_label, "filtered_playtime", priority=2),
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
                _wikidata_cell(game.wikidata),
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
    parsed_filter = parse_filter_dict(filter_json, GameFilter)
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
    presentation = date_time_presentation_for_request(request)
    form = GameForm(request.POST or None, library=library, presentation=presentation)
    graph = CatalogGraphForm(
        request.POST or None, game=None, library=library, presentation=presentation
    )
    references = ReferenceSetForm(request.POST or None, target=None, library=library)
    #: Both read, whatever either says. `and` stops at the first false
    #: one, and a graph the Game's own refusal never reached states no
    #: sentence of its own and lets no mark fall.
    game_reads = form.is_valid()
    references_read = references.is_valid()
    if graph.is_valid() and game_reads and references_read:
        game = submitted_game_or_form_error(form, graph, references)
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
            fields=Fragment(
                FormFields(form), editions_area(graph), references_area(references)
            ),
            width_class="max-w-xl md:max-w-4xl",
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
        #: A widget renders to text, thus its Media never bubbles.
        #: `<catalog-editor>` is a node, so it states its own.
        scripts=Fragment(
            ModuleScript("dist/elements/temporal-field.js"),
            ModuleScript("dist/add_game.js"),
        ),
    )


@login_required
@require_POST
def restore_game(request: HttpRequest, game_id: UUID) -> HttpResponse:
    """Undo; the plain manager, since the row is removed."""
    library = cast(User, request.user).library
    game = owned_or_404(Game.objects.filter(library=library), library, id=game_id)
    return restore_and_return(
        request,
        action=partial(restore_game_for_request, request, game),
        restored=f"{game.name} restored to your library.",
        fallback="games:list_games",
        retry=True,
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
        details=_removed_with_game(game, library),
        fallback="games:list_games",
        detail_url=game.get_absolute_url(),
        action=partial(remove_game_for_request, request, game),
        removed=f"{game.name} removed from your library.",
        undo="games:restore_game",
    )


def _removed_with_game(game: Game, library: UserLibrary) -> Node:
    tracked = tracked_game(library, game)
    runs = live_ordinary_runs(library, tracked).count() if tracked else 0
    counts = [
        (game_sessions(library, game).count(), "session"),
        (game.purchases.alive().count(), "purchase"),
        #: Removal stamps the PlayerGame; runs leave too.
        (runs, "playthrough"),
    ]
    present = [Li()[f"{count} {label}(s)"] for count, label in counts if count]
    return Ul()[*(present or [Li()["No associated data"]])]


@login_required
def edit_game(request: HttpRequest, game_id: UUID) -> HttpResponse:
    library = cast(User, request.user).library
    game = owned_or_404(Game.objects.for_library(library), library, id=game_id)
    presentation = date_time_presentation_for_request(request)
    form = GameForm(
        request.POST or None,
        instance=game,
        library=library,
        presentation=presentation,
    )
    graph = CatalogGraphForm(
        request.POST or None, game=game, library=library, presentation=presentation
    )
    references = ReferenceSetForm(request.POST or None, target=game, library=library)
    refused_status = 200
    #: Both read; see `add_game` for why the order is not `and`.
    game_reads = form.is_valid()
    references_read = references.is_valid()
    if graph.is_valid() and game_reads and references_read:
        written = submitted_game_or_form_error(form, graph, references)
        if written is not None:
            answer = record_facts_for_request(
                request,
                written,
                status=form.cleaned_data["status"],
                mastered=form.cleaned_data["mastered"],
                correlation_id=new_correlation_id(),
            )
            if answer.refusal is None:
                return redirect(return_url(request, fallback="games:list_games"))
            refused_status = answer.refusal.status_code
            #: The graph is written. Drawing it from storage rather
            #: than from the post is what makes the resubmit below
            #: land on those rows instead of making new ones.
            graph = CatalogGraphForm(
                None, game=written, library=library, presentation=presentation
            )
            references = ReferenceSetForm(None, target=written, library=library)
    #: A failed command lands here too: redirecting would read as
    #: a save. An edit resubmits onto the same row, so re-rendering
    #: invites no duplicate.
    return render_page(
        request,
        AddForm(
            form,
            request=request,
            fields=Fragment(
                FormFields(form), editions_area(graph), references_area(references)
            ),
            width_class="max-w-xl md:max-w-4xl",
        ),
        title="Edit Game",
        #: A widget renders to text, thus its Media never bubbles.
        #: `<catalog-editor>` is a node, so it states its own.
        scripts=Fragment(
            ModuleScript("dist/elements/search-select.js"),
            ModuleScript("dist/elements/temporal-field.js"),
        ),
        #: The same tail renders an invalid form.
        status=refused_status,
    )


# --- view_game content builders -------------------------------------------

_STAT_SVGS = {
    "hours": '<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="size-6"><path stroke-linecap="round" stroke-linejoin="round" d="M12 6v6h4.5m4.5 0a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z" /></svg>',
    "sessions": '<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="size-6"><path stroke-linecap="round" stroke-linejoin="round" d="M5.25 8.25h15m-16.5 7.5h15m-1.8-13.5-3.9 19.5m-2.1-19.5-3.9 19.5" /></svg>',
    "average": '<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="size-6"><path stroke-linecap="round" stroke-linejoin="round" d="M7.5 14.25v2.25m3-4.5v4.5m3-6.75v6.75m3-9v9M6 20.25h12A2.25 2.25 0 0 0 20.25 18V6A2.25 2.25 0 0 0 18 3.75H6A2.25 2.25 0 0 0 3.75 6v12A2.25 2.25 0 0 0 6 20.25Z" /></svg>',
    "playrange": '<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="size-6"><path stroke-linecap="round" stroke-linejoin="round" d="M6.75 3v2.25M17.25 3v2.25M3 18.75V7.5a2.25 2.25 0 0 1 2.25-2.25h13.5A2.25 2.25 0 0 1 21 7.5v11.25m-18 0A2.25 2.25 0 0 0 5.25 21h13.5A2.25 2.25 0 0 0 21 18.75m-18 0v-7.5A2.25 2.25 0 0 1 5.25 9h13.5A2.25 2.25 0 0 1 21 11.25v7.5m-9-6h.008v.008H12v-.008ZM12 15h.008v.008H12V15Zm0 2.25h.008v.008H12v-.008ZM9.75 15h.008v.008H9.75V15Zm0 2.25h.008v.008H9.75v-.008ZM7.5 15h.008v.008H7.5V15Zm0 2.25h.008v.008H7.5v-.008Zm6.75-4.5h.008v.008h-.008v-.008Zm0 2.25h.008v.008h-.008V15Zm0 2.25h.008v.008h-.008v-.008Zm2.25-4.5h.008v.008H16.5v-.008Zm0 2.25h.008v.008H16.5V15Z" /></svg>',
}


def _played_row(game: Game, origin: OriginUrl | None, played: int) -> Node:
    """'Played N times' split button.

    `played` counts runs whose completion is stated.

    The day may be unknown and still count.

    #687 took the '+1' action and its element away: a
    click filled in the run a tracked game already holds,
    which only untracking the game took back. #1024 owns
    stating a count.
    """
    from common.components import (
        ControlButton,
        DropdownLinkItem,
        SplitButtonDropdown,
    )

    count_button = ControlButton(
        variant="outline",
        href=action_url("games:add_playthrough", origin=origin),
    )[
        # One prose phrase = one flex item: the button is inline-flex, and flex
        # layout drops whitespace-only text between items, so the space must
        # live inside a single inline context.
        Span()[Span(data_count="")[str(played)], " times"]
    ]
    dropdown = SplitButtonDropdown(
        primary=count_button,
        id=f"played-{game.id}",
        aria_label="Playthrough actions",
        items=[
            DropdownLinkItem(
                action_url("games:add_playthrough_for_game", game.id, origin=origin),
                "Add playthrough\u2026",
            ),
        ],
    )
    return Div(class_="flex gap-2 items-center")[
        Span(class_="uppercase")["Played"], dropdown
    ]


#: Where a stat's value starts: past its ``size-6`` icon and the ``gap-2``.
_STAT_VALUE_INDENT_CLASS = "ml-8"


def _stat_popover(
    popover_id: str,
    tooltip: str,
    svg_key: str,
    value: Node | str,
    details: Node | None = None,
    *,
    beneath: Node | None = None,
) -> Node:
    """One header stat. ``details`` adds rows beneath the tooltip line — the
    playtime stat puts its alternate formats there rather than nesting a second
    popover inside this one.

    ``beneath`` hangs a second line under the value, outside the popover and
    indented to start where the value does. The popover keeps the one-line
    anatomy the other stats share, so its icon and reveal glyph sit where
    theirs do; inside the popover a second line would move both, because the
    glyph centres against the whole trigger."""
    content: Node | str = (
        tooltip
        if details is None
        else Div(class_="flex flex-col gap-1")[tooltip, details]
    )
    popover = Popover(
        popover_content=content,
        wrapped_classes="flex gap-2 items-center",
        id=popover_id,
        children=[Safe(_STAT_SVGS[svg_key]), value],
    )
    if beneath is None:
        return popover
    return Div(class_="flex flex-col")[
        popover, Div(class_=_STAT_VALUE_INDENT_CLASS)[beneath]
    ]


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
                    "slot": "Remove",
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
    add_url: str | None = None,
    organize_url: str | None = None,
) -> Node:
    buttons: list[Node] = []
    if add_url:
        #: Offered on an empty section too.
        buttons.append(
            ControlButton(
                href=add_url,
                color="gray",
                title=f"Add {title.lower()} for this game",
            )[
                Icon("plus", size=ICON_BUTTON_SIZE_CLASS),
                "Add",
            ]
        )
    if view_all_url and count:
        buttons.append(
            ControlButton(
                href=view_all_url,
                color="gray",
                title=f"View all {title.lower()} for this game",
            )[
                Icon("arrowright", size=ICON_BUTTON_SIZE_CLASS),
                "View all",
            ]
        )
    if organize_url and count:
        buttons.append(
            ControlButton(
                href=organize_url,
                color="gray",
                title=f"Organize {title.lower()} by playthrough",
            )[
                Icon("list-tree", size=ICON_BUTTON_SIZE_CLASS),
                "Organize",
            ]
        )
    heading = PageHeading(children=[title], badge=str(count) if count else "")
    if buttons:
        # No margin: the section wrapper's gap owns the distance to the table, so
        # a section with buttons spaces exactly like one without.
        # Three buttons and a badge outrun a phone.
        header = Div(class_="flex flex-wrap items-center justify-between gap-2")[
            heading,
            Div(class_="flex flex-wrap items-center gap-2")[*buttons],
        ]
    else:
        header = heading
    return Div(class_="mb-6 flex flex-col gap-4")[
        header,
        table if count else empty_message,
    ]


def _game_overview_metrics(sessions: PlayerSessionQuerySet) -> dict[str, Any]:
    """Request-free header metrics: total session count, play range, and the
    per-session average of elapsed time over the rows that state an end."""
    session_count = sessions.count()
    days = sessions.aggregate(first=Min("effective_day"), last=Max("effective_day"))

    #: Elapsed time, not the stated duration: a Corrected row's override
    #: and a Duration-only row's stated time are hand-written figures.
    timed = sessions.filter(ended_at__gt=F("started_at")).aggregate(
        total=Sum(F("ended_at") - F("started_at")), rows=Count("id")
    )
    elapsed_total = timed["total"] or timedelta(0)
    session_average_without_manual = round(
        safe_division(elapsed_total.total_seconds() / 3600, int(timed["rows"])), 1
    )
    return {
        "session_count": session_count,
        "playrange_start": days["first"],
        "playrange_end": days["last"],
        "session_average_without_manual": session_average_without_manual,
    }


def _platform_words(release: Release | None) -> str:
    """The Platform a Release names, or Unspecified."""
    if release is None or release.platform is None:
        return UNSPECIFIED_PLATFORM
    return release.platform.name


def _reads_plainly(entries: Sequence[EditionEntry]) -> bool:
    """One unnamed Edition, at most one Release."""
    if len(entries) > 1:
        return False
    if not entries:
        return True
    entry = entries[0]
    return not entry.edition.name and len(entry.releases) <= 1


def _catalog_controls_visible(game: Game) -> bool:
    """A shared Game is read-only for everyone."""
    return game.library_id is not None


def _release_words(release: Release, presentation: DateTimePresentation) -> str:
    """One Release as a phrase: the Platform, then when it landed."""
    platform = _platform_words(release)
    when = present_temporal_value(release.release_date, presentation)
    return platform if when == UNKNOWN_TEXT else f"{platform} ({when})"


def _platforms_cell(entry: EditionEntry, presentation: DateTimePresentation) -> str:
    """Every Release of one Edition, in one cell.

    A comma list rather than a cell each: the table hides a column
    by position, thus a row states exactly one cell per column.
    """
    if not entry.releases:
        return "No releases yet."
    return ", ".join(
        _release_words(release, presentation) for release in entry.releases
    )


def _plain_release_rows(
    entries: Sequence[EditionEntry],
    presentation: DateTimePresentation,
) -> list[Node]:
    """The header states an ordinary Game's Release."""
    if not _reads_plainly(entries):
        return []
    releases = entries[0].releases if entries else ()
    release = releases[0] if releases else None
    rows: list[Node] = [
        _meta_row(
            "Platform",
            Span(class_=META_VALUE_CLASS)[_platform_words(release)],
        ),
        _meta_row(
            "Released",
            TemporalText(
                None if release is None else release.release_date,
                presentation,
                class_=META_VALUE_CLASS,
            ),
        ),
    ]
    #: Nothing to press here: Edit Game owns the whole graph.
    return rows


def _references_row(references: Sequence[ExternalReference]) -> list[Node]:
    """No row when nothing is named outside."""
    if not references:
        return []
    return [_meta_row("References", ExternalReferenceLinks(references))]


def _references_cell(entry: EditionEntry, references: ReferenceMap) -> Node:
    """One Edition's references, then its Releases'."""
    held = held_by(references, entry.edition.pk)
    for release in entry.releases:
        held.extend(held_by(references, release.pk))
    return ExternalReferenceLinks(held)


def _releases_section(
    entries: Sequence[EditionEntry],
    presentation: DateTimePresentation,
    origin: OriginUrl | None,
    *,
    game: Game,
    references: ReferenceMap,
) -> Node:
    """What the header's two rows cannot say.

    One read-only row per Edition. Every edit goes to the Game
    form, which states the whole graph in one transaction, so
    nothing here writes.

    A placeholder, and it says so on the page. `Edition` and
    `Release` are the words the schema needs for IGDB, not words
    a reader wants: nothing a person makes names either one, and
    every one of 858 real Games holds exactly one of each. The
    section worth having states the playtime of each edition,
    which #690 makes readable by letting a Session name a
    Release. This shape is replaced then.
    """
    if _reads_plainly(entries):
        return Fragment()
    controls = _catalog_controls_visible(game)
    columns = [
        Column("Name"),
        Column("Platforms", wrap=True),
        Column("References", priority=2),
    ]
    if controls:
        columns.append(Column("Actions", align="right", priority=3))
    #: One link, drawn once per row: the form owns every Edition.
    edit = Div(class_="flex justify-end")[
        ControlButton(
            href=action_url("games:edit_game", game.pk, origin=origin), color="gray"
        )["Edit"]
    ]
    rows = [
        make_row(
            entry.edition.display_name,
            _platforms_cell(entry, presentation),
            _references_cell(entry, references),
            *((edit,) if controls else ()),
        )
        for entry in entries
    ]
    return Div(class_="mb-6 flex flex-col gap-4")[
        PageHeading(children=["Editions"], badge=str(len(entries))),
        P(
            class_="text-type-body text-warning bg-warning-soft "
            "border border-warning-subtle rounded px-3 py-2"
        )[EDITIONS_UNDER_CONSTRUCTION],
        StyledTable(
            columns=columns,
            rows=rows,
            data_table=True,
            caption=f"Editions of {game.name}",
            #: Two Games may share a name; their ids may not.
            caption_key=str(game.pk),
        ),
    ]


def _game_header(
    game: Game,
    request: HttpRequest,
    metrics: dict[str, Any],
    playtime: PlaytimeBreakdown,
    presentation: DateTimePresentation,
    durations: DurationPresentation,
    origin: OriginUrl | None,
    entries: Sequence[EditionEntry],
    references: Sequence[ExternalReference],
    played: int,
) -> Node:
    playrange_start = metrics["playrange_start"]
    playrange_end = metrics["playrange_end"]
    if playrange_start and playrange_end:
        start = presentation.format(playrange_start, "month_year")
        end = presentation.format(playrange_end, "month_year")
        playrange = start if start == end else f"{start} — {end}"
    else:
        playrange = "N/A"
    title_span = Span(class_="text-balance max-w-120")[
        Span(class_="text-type-title font-serif")[game.name],
    ]
    stats_row = Div(class_="flex gap-4 text-type-body dark:text-slate-400 mb-3")[
        _stat_popover(
            "popover-hours",
            "Total hours played",
            "hours",
            DurationText(playtime.total, durations),
            DurationAlternates(playtime.total, durations),
            beneath=(
                PlaytimeHalves(playtime, durations) if playtime.historical else None
            ),
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
        class_="flex flex-col mb-6 text-body gap-y-4 text-type-body",
    )[
        _meta_row(
            "Original release",
            TemporalText(
                game.original_release_date, presentation, class_=META_VALUE_CLASS
            ),
        ),
        *_references_row(references),
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
        _played_row(game, origin, played),
        *_plain_release_rows(entries, presentation),
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
    sessions: PlayerSessionQuerySet,
    presentation: DateTimePresentation,
    durations: DurationPresentation,
) -> Node:
    sessions = sessions.select_related("device").order_by("-sort_instant", "-id")
    session_count = sessions.count()
    rows = [
        make_row(
            session_time_range(session, presentation),
            Duration(
                session.effective_duration,
                durations,
                id_scope=f"game-session-{session.pk}",
                manual=session.timing_mode != PlayerSessionTimingMode.TIMED,
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
        view_all_url=filter_url(PlayerSessionFilter.where(game=[game.id])),
        organize_url=filter_url(
            PlayerSessionFilter.where(game=[game.id]), sort="playthrough"
        ),
    )


def _historical_playtime_section(
    game: Game,
    library: UserLibrary,
    presentation: DateTimePresentation,
    durations: DurationPresentation,
    origin: OriginUrl | None,
    request: HttpRequest,
) -> Node:
    records = list(
        listed_records(library).filter(player_game__game=game).order_by(*RECORD_ORDER)
    )
    data = historical_playtime_tabledata(
        records,
        run_labels_for(library, records),
        presentation,
        durations,
        exclude_columns=["Name", "Created"],
        origin=origin,
        caption="Historical playtime of this game",
    )
    table = StyledTable(
        columns=data["columns"],
        rows=data["rows"],
        data_table=True,
        caption="Historical playtime of this game",
        #: The request scopes the kept selection to this library.
        request=request,
        selection=SelectionDeclaration(
            #: The act's scope is the library's, not this game's: an
            #: "all" statement here would name every record the library
            #: holds. This section states no paginator, so the line
            #: renders no "select all matching" and the statement it
            #: posts is always the keys a person marked.
            filter="",
            csrf_token=get_token(request),
            actions=tray_actions(REMOVE_RECORD.name, origin=origin),
        ),
    )
    section = _game_section(
        "Historical playtime",
        len(records),
        table,
        "No historical playtime.",
        view_all_url=filter_url(HistoricalPlaytimeFilter.where(game=[game.id])),
        add_url=action_url("games:add_historical_playtime", game.pk, origin=origin),
    )
    return Div(id_="historical-playtime-container")[section]


def _playthroughs_section(
    game: Game,
    runs: Sequence[Playthrough],
    presentation: DateTimePresentation,
    clock: ActivityClock,
    origin: OriginUrl | None,
    csrf_token: str,
    request: HttpRequest,
) -> Node:
    data = playthrough_tabledata(
        runs,
        presentation,
        exclude_columns=["Game"],
        clock=clock,
        origin=origin,
        csrf_token=csrf_token,
    )
    # This embedded mini-table isn't a sortable list view (no ?sort= handling on
    # the detail page), and its builder states no sort keys.
    table = StyledTable(
        columns=data["columns"],
        rows=data["rows"],
        data_table=True,
        caption="Playthroughs of this game",
        #: The request scopes the kept selection to this library.
        request=request,
        selection=SelectionDeclaration(
            #: The act's scope is the library's, not this game's: an
            #: "all" statement here would name every run the library
            #: holds. This section states no paginator, so the line
            #: renders no "select all matching" and the statement it
            #: posts is always the keys a person marked.
            filter="",
            csrf_token=csrf_token,
            actions=tray_actions(REMOVE_RUN.name, origin=origin),
        ),
    )
    section = _game_section(
        "Playthroughs",
        len(runs),
        table,
        #: Reachable: conversion skipped a tracked game
        #: whose catalog row was removed.
        "No playthroughs yet.",
        view_all_url=filter_url(PlaythroughFilter.where(game=[game.id])),
    )
    return Div(id_="playthroughs-container")[section]


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
    sessions = game_sessions(library, game)
    purchases = Purchase.objects.for_library(library).filter(games=game)
    tracked = tracked_game(library, game)
    #: A run may name another library's PlayerGame.
    runs = list(
        numbered_for(
            library, [tracked.pk] if tracked else [], with_condition=True
        ).select_related("player_game__game")
    )
    #: Counted here, off rows already read.
    played = sum(1 for run in runs if run.completion_recorded_at is not None)
    hierarchy = game_hierarchy(game, library)
    #: One batch, one query per kind.
    referenced: list[CatalogTarget] = [game]
    for entry in hierarchy:
        referenced.append(entry.edition)
        referenced.extend(entry.releases)
    references = references_for(referenced)
    content = ContentContainer(class_="dark:text-white")[
        _game_header(
            game,
            request,
            _game_overview_metrics(sessions),
            game_playtime(library, game),
            presentation,
            durations,
            origin,
            hierarchy,
            held_by(references, game.pk),
            played,
        ),
        _releases_section(
            hierarchy, presentation, origin, game=game, references=references
        ),
        _purchases_section(game, purchases, presentation, origin),
        _sessions_section(game, sessions, presentation, durations),
        _historical_playtime_section(
            game, library, presentation, durations, origin, request
        ),
        _playthroughs_section(
            game,
            runs,
            presentation,
            activity_clock(library),
            origin,
            get_token(request),
            request,
        ),
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
