from datetime import date
from functools import partial
from typing import Any, Protocol, cast
from uuid import UUID

from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db.models import QuerySet
from django.http import (
    HttpRequest,
    HttpResponse,
)
from django.middleware.csrf import get_token
from django.urls import reverse
from django.views.decorators.http import require_POST

from common.components import (
    Cell,
    Column,
    ContentContainer,
    PurchaseAmount,
    PurchaseName,
    QuickFilterBar,
    TableData,
    drop_columns,
    make_row,
    paginated_table_content,
    parse_filter_dict,
)
from common.components.primitives import P
from common.date_time_presentation import (
    DateTimePresentation,
    date_time_presentation_for_request,
)
from common.filter_execution import execute_filter, regex_timeout_view
from common.layout import render_page
from common.temporal_presentation import TemporalText
from common.utils import paginate
from games.commands.endpoint import ActStatement
from games.endpoints import PURCHASE_REFUND
from games.events.purchase import PURCHASE_REFUND_EVENTS
from games.filters import (
    PurchaseFilter,
    filter_query_context_for_library,
    parse_purchase_filter,
)
from games.list_columns import column_choice
from games.models import (
    Game,
    LibraryEntry,
    Purchase,
    PurchaseKind,
    PurchaseQuerySet,
    UserLibrary,
)
from games.ownership import owned_or_404
from games.price_fields import price_presentations
from games.purchase_forms import (
    PurchaseAddForm,
    PurchaseEditForm,
    edit_groups,
    edit_presentations,
    purchase_groups,
)
from games.reads.endpoints import stated
from games.reads.entries import EventSequence
from games.reads.playthrough_completions import (
    PURCHASE_RUNS,
    completion_exists,
    reported_completion,
    reported_completion_day,
)
from games.reads.purchases import ValuedPurchase, latest_refund_act, library_purchases
from games.sorting import (
    PURCHASE_DEFAULT_SORT,
    PURCHASE_SORTS,
    apply_sort,
    parse_find_filter,
)
from games.views.copy_pages import form_page, held_entry, one_click, press_key
from games.views.filtering import (
    apply_structured_filter,
    builder_url_for,
    warn_unknown_sort,
)
from games.views.general import request_calendar_today
from games.views.library_cards import release_words
from games.views.purchase_menu import purchase_row_menu, purchase_summary
from games.views.removal import (
    confirm_and_remove,
    restore_and_return,
)
from games.writes.answers import CONFLICT_STATUS, CommandFailed
from games.writes.playergame import new_correlation_id
from games.writes.purchase import (
    record_purchase,
    refund_purchase,
    restate_purchase,
)
from games.writes.purchase import remove_purchase as remove_purchase_write
from games.writes.purchase import restore_purchase as restore_purchase_write
from timetracker.temporal import TemporalValue

PURCHASE_COLUMNS: list[Column] = [
    Column("Name", "name", shrinkable=True, key="name", hideable=False),
    Column("Kind", "kind", priority=2, key="kind"),
    Column("Amount", "amount", priority=3, key="amount"),
    Column("Purchased", "purchased", priority=2, key="purchased"),
    Column("Refunded", "refunded", key="refunded", hidden_by_default=True),
    Column("Finished", "finished", key="finished"),
    Column("Created", "created", key="created", hidden_by_default=True),
]


def purchase_list_rows(library: UserLibrary) -> PurchaseQuerySet:
    """The list's rows, carrying the Finished facts."""
    return (
        library_purchases(library)
        .annotated_for_filtering(library)
        .select_related("entry__player_game__game", "entry__release__platform")
        .annotate(
            has_completion=completion_exists(library, None, PURCHASE_RUNS),
            completed_value=reported_completion(library, PURCHASE_RUNS),
            completed_day=reported_completion_day(library, PURCHASE_RUNS),
        )
    )


class ListedPurchase(ValuedPurchase, Protocol):
    """A row `purchase_list_rows` annotated."""

    has_completion: bool
    completed_value: TemporalValue | None
    completed_day: date | None


def _purchase_cells(
    purchase: Purchase, presentation: DateTimePresentation
) -> list[Cell]:
    """One row's cells, one for each column."""
    if not hasattr(purchase, "has_completion"):
        raise ValueError(
            f"purchase {purchase.pk} carries no list annotations; "
            "read the rows through purchase_list_rows()"
        )
    listed = cast(ListedPurchase, purchase)
    #: Read the act, not the value.
    #: A null value is a completion nobody dated, which
    #: TemporalText prints as Unknown. No completion is a dash.
    date_finished = (
        TemporalText(listed.completed_value, presentation)
        if listed.has_completion
        else "-"
    )
    refunded = stated(purchase, PURCHASE_REFUND)
    return [
        PurchaseName(purchase),
        PurchaseKind(purchase.kind).label,
        PurchaseAmount(purchase),
        TemporalText(purchase.purchased, presentation),
        "-" if refunded is None else TemporalText(refunded.when, presentation),
        date_finished,
        presentation.format(purchase.created_at, "date"),
    ]


@login_required
@regex_timeout_view
def list_purchases(request: HttpRequest) -> HttpResponse:
    presentation = date_time_presentation_for_request(request)
    library = cast(User, request.user).library
    purchases: QuerySet[Purchase] = purchase_list_rows(library)

    filter_json = request.GET.get("filter", "")
    if filter_json:
        purchase_filter = apply_structured_filter(
            request, parse_purchase_filter, filter_json
        )
        if purchase_filter is not None:
            purchases = execute_filter(
                purchase_filter,
                purchases,
                filter_query_context_for_library(library),
            )

    find = parse_find_filter(request)
    sort = apply_sort(purchases, find, PURCHASE_SORTS, PURCHASE_DEFAULT_SORT)
    warn_unknown_sort(request, sort.unknown, entity="purchase")
    page, page_obj, elided_page_range = paginate(sort.queryset, find)
    #: One read serves cells and rows.
    page_purchases: list[Purchase] = list(page)

    origin = request.get_full_path()
    csrf_token = get_token(request)
    hidden, picker = column_choice(request, "purchases", PURCHASE_COLUMNS)
    kept_columns, kept_cells = drop_columns(
        PURCHASE_COLUMNS,
        [_purchase_cells(purchase, presentation) for purchase in page_purchases],
        hidden,
    )
    data: TableData = {
        "caption": "Purchases",
        "columns": kept_columns,
        #: Every row carries its menu.
        "menu_slot": True,
        "sort_terms": sort.terms,
        "rows": [
            make_row(
                *cells,
                id=f"purchase-row-{purchase.id}",
                menu=purchase_row_menu(purchase, origin, csrf_token),
            )
            for purchase, cells in zip(page_purchases, kept_cells, strict=True)
        ],
        "column_picker": picker,
    }
    content = paginated_table_content(
        data,
        page_obj=page_obj,
        elided_page_range=elided_page_range,
        request=request,
        page_size=find.per_page,
    )
    quick_bar = QuickFilterBar(
        presentation=presentation,
        mode="purchases",
        existing=parse_filter_dict(filter_json, PurchaseFilter),
        builder_url=builder_url_for(
            "purchases", filter_json, find.sort, find.per_page_override
        ),
        preset_api_url=reverse("api-1.0.0:list_presets"),
        per_page_override=find.per_page_override,
    )
    content = ContentContainer()[quick_bar, content]
    return render_page(
        request,
        content,
        title="Manage purchases",
    )


UNDO_OVERTAKEN = "This purchase changed since; nothing was undone."
ALREADY_REFUNDED = "This purchase is already refunded."


def _held_purchase(request: HttpRequest, purchase_id: UUID) -> Purchase:
    library = cast(User, request.user).library
    return owned_or_404(
        library_purchases(library).select_related(*_PURCHASE_PATHS),
        library,
        id=purchase_id,
    )


def _any_purchase(request: HttpRequest, purchase_id: UUID) -> Purchase:
    """Removed or not, for remove and restore."""
    library = cast(User, request.user).library
    return owned_or_404(
        Purchase.objects.filter(library=library).select_related(*_PURCHASE_PATHS),
        library,
        id=purchase_id,
    )


_PURCHASE_PATHS = ("entry__player_game__game", "entry__release__platform")


def _title(act: str, entry: LibraryEntry) -> str:
    return f"{act} - {entry.player_game.game.name} ({release_words(entry)})"


def _game_fallback(game: Game) -> dict[str, Any]:
    return {"fallback": "games:view_game", "fallback_args": [game.pk, game.url_slug]}


@login_required
def add_purchase(request: HttpRequest, entry_id: UUID) -> HttpResponse:
    user = cast(User, request.user)
    entry = held_entry(request, entry_id)
    form = PurchaseAddForm(
        request.POST or None,
        library=user.library,
        presentation=date_time_presentation_for_request(request),
        today=request_calendar_today(request, user.library),
    )
    return form_page(
        request,
        form,
        title=_title("Add purchase", entry),
        write=lambda: record_purchase(
            user,
            form.draft(entry.pk),
            correlation_id=new_correlation_id(),
            idempotency_key=form.submission_key(),
        ),
        done="Purchase added.",
        game=lambda: entry.player_game.game,
        groups=purchase_groups(),
        presentations=price_presentations(),
        submit_label="Add purchase",
    )


@login_required
def edit_purchase(request: HttpRequest, purchase_id: UUID) -> HttpResponse:
    user = cast(User, request.user)
    purchase = _held_purchase(request, purchase_id)
    form = PurchaseEditForm(
        request.POST or None,
        purchase=purchase,
        presentation=date_time_presentation_for_request(request),
    )

    def restate() -> object:
        cleaned = form.cleaned_data
        return restate_purchase(
            user,
            purchase,
            kind=cleaned["kind"],
            name=cleaned["name"],
            price=form.stated_price(),
            note=cleaned["note"],
            purchased=form.purchased(),
            refund=form.refund_statement(),
            correlation_id=new_correlation_id(),
        )

    return form_page(
        request,
        form,
        title=_title("Edit purchase", purchase.entry),
        write=restate,
        done="Purchase saved.",
        game=lambda: purchase.entry.player_game.game,
        groups=edit_groups(),
        presentations=edit_presentations(),
    )


@login_required
def remove_purchase(request: HttpRequest, purchase_id: UUID) -> HttpResponse:
    user = cast(User, request.user)
    purchase = _any_purchase(request, purchase_id)
    game = purchase.entry.player_game.game
    return confirm_and_remove(
        request,
        purchase,
        title="Remove purchase",
        message=f"Remove this purchase of {game.name}?",
        details=P()[
            purchase_summary(purchase, date_time_presentation_for_request(request))
        ],
        **_game_fallback(game),
        action=partial(
            remove_purchase_write, user, purchase, correlation_id=new_correlation_id()
        ),
        removed="Purchase removed.",
        undo="games:restore_purchase",
    )


@login_required
@require_POST
def restore_purchase(request: HttpRequest, purchase_id: UUID) -> HttpResponse:
    user = cast(User, request.user)
    purchase = _any_purchase(request, purchase_id)
    return restore_and_return(
        request,
        action=partial(
            restore_purchase_write, user, purchase, correlation_id=new_correlation_id()
        ),
        restored="Purchase restored.",
        **_game_fallback(purchase.entry.player_game.game),
    )


@login_required
@require_POST
def refund_purchase_now(request: HttpRequest, purchase_id: UUID) -> HttpResponse:
    """Refunded today; Undo voids it."""
    user = cast(User, request.user)
    purchase = _held_purchase(request, purchase_id)
    key = press_key(request, "purchase", "refund")
    today = TemporalValue.from_day(request_calendar_today(request, user.library))

    def refund() -> str:
        refunded = refund_purchase(
            user,
            purchase,
            ActStatement(today, ""),
            correlation_id=new_correlation_id(),
            idempotency_key=key,
        )
        if refunded.sequence is None:
            raise CommandFailed(ALREADY_REFUNDED, CONFLICT_STATUS)
        return reverse(
            "games:undo_purchase_refund", args=[purchase.pk, refunded.sequence]
        )

    return one_click(
        request, purchase.entry.player_game.game, write=refund, done="Refunded."
    )


@login_required
@require_POST
def undo_purchase_refund(
    request: HttpRequest, purchase_id: UUID, sequence: EventSequence
) -> HttpResponse:
    """Void this press's refund, if still latest."""
    user = cast(User, request.user)
    purchase = _held_purchase(request, purchase_id)

    def void() -> None:
        latest = latest_refund_act(user.library, purchase.pk)
        if (
            latest is None
            or latest.sequence != sequence
            or latest.event_type != PURCHASE_REFUND_EVENTS.stated.event_type
        ):
            raise CommandFailed(UNDO_OVERTAKEN, CONFLICT_STATUS)
        restate_purchase(
            user, purchase, refund=None, correlation_id=new_correlation_id()
        )

    return restore_and_return(
        request,
        action=void,
        restored="Refund undone.",
        **_game_fallback(purchase.entry.player_game.game),
    )
