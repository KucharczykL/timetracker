from functools import partial
from typing import cast
from uuid import UUID

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import QuerySet
from django.http import (
    HttpRequest,
    HttpResponse,
)
from django.shortcuts import redirect
from django.template.defaultfilters import floatformat, pluralize
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from common.components import (
    ICON_BUTTON_SIZE_CLASS,
    AddForm,
    ButtonGroup,
    Cell,
    Checkbox,
    Column,
    ContentContainer,
    ControlButton,
    Div,
    FormFields,
    Fragment,
    GameLink,
    Icon,
    Input,
    Link,
    LinkedPurchase,
    ModuleScript,
    Node,
    PriceConverted,
    PurchasePrice,
    SelectionFields,
    TableData,
    drop_columns,
    make_row,
    paginated_table_content,
)
from common.components.primitives import Li, P, Ul
from common.date_time_presentation import (
    DateTimePresentation,
    date_time_presentation_for_request,
)
from common.filter_execution import execute_filter, regex_timeout_view
from common.layout import render_page
from common.returns import OriginUrl, action_url
from common.temporal_presentation import TemporalText
from common.utils import label_with_details, paginate
from games.forms import PurchaseForm
from games.list_columns import column_choice
from games.models import Game, PlayerGameStatus, Purchase, UserLibrary
from games.ownership import owned_or_404
from games.reads.playthrough_completions import (
    PURCHASE_RUNS,
    completion_exists,
    reported_completion,
    reported_completion_day,
)
from games.removal import remove, restore
from games.sorting import (
    PURCHASE_DEFAULT_SORT,
    PURCHASE_SORTS,
    apply_sort,
    parse_find_filter,
)
from games.views.filtering import warn_unknown_sort
from games.views.removal import (
    confirm_and_apply,
    confirm_and_remove,
    restore_and_return,
)
from games.views.returns import origin_from, return_url
from games.writes.answers import CommandFailed
from games.writes.playergame import new_correlation_id, record_facts


def _render_purchase_buttons(
    purchase_id: UUID, is_refunded, can_split=False, *, origin: OriginUrl | None
):
    """Return button group HTML for a purchase row."""
    return ButtonGroup(
        [
            {
                "href": action_url("games:refund_purchase", purchase_id, origin=origin),
                "slot": Icon("refund", size=ICON_BUTTON_SIZE_CLASS),
                "title": "Mark as refunded",
            }
            if not is_refunded
            else {},
            {
                "href": action_url("games:split_purchase", purchase_id, origin=origin),
                "slot": Icon("split", size=ICON_BUTTON_SIZE_CLASS),
                "title": "Split into per-game purchases",
                "color": "gray",
            }
            if can_split
            else {},
            {
                "href": action_url("games:edit_purchase", purchase_id, origin=origin),
                "slot": Icon("edit", size=ICON_BUTTON_SIZE_CLASS),
                "title": "Edit",
                "color": "gray",
            },
            {
                "href": action_url("games:remove_purchase", purchase_id, origin=origin),
                "slot": Icon("delete", size=ICON_BUTTON_SIZE_CLASS),
                "title": "Remove",
                "color": "red",
            },
        ]
    )


PURCHASE_COLUMNS: list[Column] = [
    Column("Name", "name", shrinkable=True, key="name", hideable=False),
    Column("Type", "type", priority=2, key="type"),
    Column("Price", "price", priority=3, key="price"),
    Column("Infinite", "infinite", key="infinite", hidden_by_default=True),
    Column("Purchased", "purchased", priority=2, key="purchased"),
    Column("Finished", "finished", key="finished"),
    Column("Refunded", "refunded", key="refunded", hidden_by_default=True),
    Column("Created", "created", key="created", hidden_by_default=True),
    Column("Actions", align="right", priority=4, key="actions", hideable=False),
]


def _purchases_with_completions(library: UserLibrary) -> QuerySet[Purchase]:
    """The list's rows, carrying the Finished facts."""
    return (
        Purchase.objects.for_library(library)
        .select_related("platform")
        .prefetch_related("games", "games__platform")
        .annotate(
            has_completion=completion_exists(library, None),
            completed_value=reported_completion(library, PURCHASE_RUNS),
            completed_day=reported_completion_day(library, PURCHASE_RUNS),
        )
    )


def _purchase_cells(
    purchase: Purchase, presentation: DateTimePresentation, *, origin: OriginUrl | None
) -> list[Cell]:
    """One row's cells, one for each column."""
    #: Read the act, not the value.
    #: A null value is a completion nobody dated, which
    #: TemporalText prints as Unknown. No completion is a dash.
    date_finished = (
        TemporalText(purchase.completed_value, presentation)
        if purchase.has_completion
        else "-"
    )
    return [
        LinkedPurchase(purchase),
        purchase.get_type_display(),
        PurchasePrice(purchase),
        str(purchase.infinite),
        presentation.format(purchase.date_purchased, "date"),
        date_finished,
        (
            presentation.format(purchase.date_refunded, "date")
            if purchase.date_refunded
            else "-"
        ),
        presentation.format(purchase.created_at, "date"),
        _render_purchase_buttons(
            purchase.id,
            bool(purchase.date_refunded),
            can_split=purchase.num_purchases > 1,
            origin=origin,
        ),
    ]


@login_required
@regex_timeout_view
def list_purchases(request: HttpRequest) -> HttpResponse:
    presentation = date_time_presentation_for_request(request)
    library = cast(User, request.user).library
    origin = request.get_full_path()
    purchases: QuerySet[Purchase] = _purchases_with_completions(library)

    filter_json = request.GET.get("filter", "")
    if filter_json:
        from games.filters import (
            filter_query_context_for_library,
            parse_purchase_filter,
        )
        from games.views.filtering import apply_structured_filter

        purchase_filter = apply_structured_filter(
            request, parse_purchase_filter, filter_json
        )
        if purchase_filter is not None:
            purchases = execute_filter(
                purchase_filter,
                purchases,
                filter_query_context_for_library(library),
            )
            #: `game_filter` joins; a bundle answers per match.
            purchases = purchases.distinct()

    find = parse_find_filter(request)
    sort = apply_sort(purchases, find, PURCHASE_SORTS, PURCHASE_DEFAULT_SORT)
    purchases = sort.queryset
    warn_unknown_sort(request, sort.unknown, entity="purchase")

    purchases, page_obj, elided_page_range = paginate(purchases, find)

    hidden, picker = column_choice(request, "purchases", PURCHASE_COLUMNS)
    kept_columns, kept_cells = drop_columns(
        PURCHASE_COLUMNS,
        [
            _purchase_cells(purchase, presentation, origin=origin)
            for purchase in purchases
        ],
        hidden,
    )
    data: TableData = {
        "caption": "Purchases",
        "columns": kept_columns,
        "sort_terms": sort.terms,
        "rows": [
            make_row(*cells, id=f"purchase-row-{purchase.id}")
            for purchase, cells in zip(purchases, kept_cells, strict=True)
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
    from common.components import (
        QuickFilterBar,
        parse_filter_dict,
    )
    from games.filters import PurchaseFilter
    from games.views.filtering import builder_url_for

    builder_url = builder_url_for(
        "purchases", filter_json, find.sort, find.per_page_override
    )
    parsed_filter = parse_filter_dict(filter_json, PurchaseFilter)
    quick_bar = QuickFilterBar(
        presentation=presentation,
        mode="purchases",
        existing=parsed_filter,
        builder_url=builder_url,
        preset_api_url=reverse("api-1.0.0:list_presets"),
        per_page_override=find.per_page_override,
    )
    content = ContentContainer()[quick_bar, content]
    return render_page(
        request,
        content,
        title="Manage purchases",
    )


def _purchase_additional_row() -> Node:
    """The 'Submit & Create Session' button shown below the main Submit button."""
    return ControlButton(
        color="gray",
        type="submit",
        name="submit_and_redirect",
    )["Submit & Create Session"]


def _pricing_controls() -> Node:
    """Pricing UI for the add-purchase form.

    By default the form's own single Price field is the bundle price. When 2+
    games are selected and "Separate price per game" is checked, the per-game
    inputs (the general ``selection-fields`` element) take over and the bundle
    Price is hidden. Toggle/visibility wiring lives in ts/add_purchase.ts; the
    hidden ``pricing_mode`` tells the view which path to take.
    """
    return Div(id_="pricing-controls")[
        Div(id_="separate-prices-row", class_="hidden")[
            Checkbox(
                name="separate_prices",
                label="Separate price per game",
                id_="id_separate_prices",
            ),
        ],
        Input(
            type="hidden",
            name="pricing_mode",
            id_="id_pricing_mode",
            value="combined",
        ),
        SelectionFields(
            source="games",
            name_prefix="price_for_game_",
            field_type="number",
            min_items=2,
            active=False,
            input_attributes=[
                ("step", "0.01"),
                ("min", "0"),
                ("inputmode", "decimal"),
                ("placeholder", "Price"),
            ],
        ),
    ]


#: No dispatch here: run_in_transaction refuses to nest.
@transaction.atomic
def _create_separate_purchases(form: PurchaseForm, post) -> None:
    """Create one single-game Purchase per selected game from the shared form
    fields, each priced from its own ``price_for_game_<id>`` input. The
    ``m2m_changed`` signal sets ``num_purchases``/``price_per_game`` once each
    game is attached."""
    data = form.cleaned_data
    shared = {
        "library": form.library,
        "platform": data.get("platform"),
        "date_purchased": data["date_purchased"],
        "date_refunded": data.get("date_refunded"),
        "infinite": data.get("infinite", False),
        "price_currency": data["price_currency"],
        "ownership_type": data["ownership_type"],
        "type": data["type"],
        "related_game": data.get("related_game"),
        "name": data.get("name") or "",
    }
    for game in data["games"]:
        raw_price = post.get(f"price_for_game_{game.id}", "")
        try:
            price = float(raw_price) if raw_price not in (None, "") else 0.0
        except ValueError:
            price = 0.0
        purchase = Purchase(price=price, **shared)
        purchase.save()
        purchase.games.set([game])


@login_required
def add_purchase(request: HttpRequest, game_id: UUID | None = None) -> HttpResponse:
    library = cast(User, request.user).library
    presentation = date_time_presentation_for_request(request)
    initial = {"date_purchased": timezone.now()}

    if request.method == "POST":
        form = PurchaseForm(
            request.POST or None,
            initial=initial,
            library=library,
            user=cast(User, request.user),
            presentation=presentation,
        )
        if form.is_valid():
            if request.POST.get("pricing_mode") == "per_game":
                _create_separate_purchases(form, request.POST)
                return redirect(return_url(request, fallback="games:list_purchases"))
            purchase = form.save()
            if "submit_and_redirect" in request.POST:
                return redirect(
                    action_url(
                        "games:add_session_for_game",
                        game_id=purchase.first_game.id,
                        origin=origin_from(request),
                    )
                )
            return redirect(return_url(request, fallback="games:list_purchases"))
    else:
        if game_id:
            game = owned_or_404(Game.objects.for_library(library), library, id=game_id)
            form = PurchaseForm(
                initial={
                    **initial,
                    "games": [game],
                    "platform": game.platform,
                },
                library=library,
                user=cast(User, request.user),
                presentation=presentation,
            )
            # Chained from add_game: game and platform are pre-filled, so focus
            # the first empty field the user still needs to fill instead.
            form.fields["games"].widget.autofocus = False
            form.fields["price"].widget.attrs["autofocus"] = "autofocus"
        else:
            form = PurchaseForm(
                initial=initial,
                library=library,
                user=cast(User, request.user),
                presentation=presentation,
            )

    return render_page(
        request,
        AddForm(
            form,
            request=request,
            fields=Fragment(FormFields(form), _pricing_controls()),
            additional_row=_purchase_additional_row(),
        ),
        title="Add New Purchase",
        scripts=Fragment(
            ModuleScript("dist/elements/search-select.js"),
            ModuleScript("dist/elements/date-picker.js"),
            ModuleScript("dist/add_purchase.js"),
        ),
    )


@login_required
def edit_purchase(request: HttpRequest, purchase_id: UUID) -> HttpResponse:
    library = cast(User, request.user).library
    purchase = owned_or_404(
        Purchase.objects.for_library(library), library, id=purchase_id
    )
    form = PurchaseForm(
        request.POST or None,
        instance=purchase,
        library=library,
        user=cast(User, request.user),
        presentation=date_time_presentation_for_request(request),
    )
    if form.is_valid():
        form.save()
        return redirect(return_url(request, fallback="games:list_purchases"))
    return render_page(
        request,
        AddForm(form, request=request, additional_row=_purchase_additional_row()),
        title="Edit Purchase",
        scripts=Fragment(
            ModuleScript("dist/elements/search-select.js"),
            ModuleScript("dist/elements/date-picker.js"),
            ModuleScript("dist/add_purchase.js"),
        ),
    )


@login_required
@require_POST
def restore_purchase(request: HttpRequest, purchase_id: UUID) -> HttpResponse:
    """Undo; the plain manager, since the row is removed."""
    library = cast(User, request.user).library
    purchase = owned_or_404(
        Purchase.objects.filter(library=library), library, id=purchase_id
    )
    return restore_and_return(
        request,
        action=partial(restore, purchase),
        restored="Purchase restored.",
        fallback="games:list_purchases",
    )


@login_required
def remove_purchase(request: HttpRequest, purchase_id: UUID) -> HttpResponse:
    library = cast(User, request.user).library
    purchase = owned_or_404(
        Purchase.objects.for_library(library), library, id=purchase_id
    )
    return confirm_and_remove(
        request,
        purchase,
        title="Remove purchase",
        message=f"Remove this purchase of {purchase.first_game}?",
        fallback="games:list_purchases",
        detail_url=reverse("games:view_purchase", args=[purchase_id]),
        removed="Purchase removed.",
        undo="games:restore_purchase",
    )


def _view_purchase_content(
    purchase: Purchase, presentation: DateTimePresentation
) -> Node:
    first_game = purchase.first_game
    owned = f"Owned on {presentation.format(purchase.date_purchased, 'date')}"
    if purchase.date_refunded:
        owned += f" (refunded {presentation.format(purchase.date_refunded, 'date')})"

    row_class = "text-slate-500 text-type-body"
    title_class = "text-type-title font-serif text-slate-500"
    inner = Div(class_="flex flex-col gap-5 mb-3")[
        Div(class_=title_class)[
            Link(href=first_game.get_absolute_url())[first_game.name]
        ],
        Div(class_=row_class)[purchase.get_type_display()],
        Div(class_=row_class)[owned],
        Div(class_=row_class)[PriceConverted([purchase.standardized_price])],
        Div(class_=row_class)[
            P()[
                "Price per game: ",
                PriceConverted([floatformat(purchase.price_per_game, 0)]),
                f" {purchase.converted_currency}",
            ]
        ],
        Div(class_=row_class)["Games included in this purchase:"],
        Ul()[[Li()[GameLink(game, game.name)] for game in purchase.games.all()]],
    ]
    return ContentContainer(class_="dark:text-white")[inner]


def _purchase_page_title(purchase: Purchase, presentation: DateTimePresentation) -> str:
    return label_with_details(
        purchase.standardized_name,
        f"{purchase.num_purchases} game{pluralize(purchase.num_purchases)}",
        presentation.format(purchase.date_purchased, "date"),
        purchase.standardized_price,
    )


@login_required
def view_purchase(request: HttpRequest, purchase_id: UUID) -> HttpResponse:
    library = cast(User, request.user).library
    purchase = owned_or_404(
        Purchase.objects.for_library(library), library, id=purchase_id
    )
    presentation = date_time_presentation_for_request(request)
    return render_page(
        request,
        _view_purchase_content(purchase, presentation),
        title=f"Purchase: {_purchase_page_title(purchase, presentation)}",
    )


def _refund(user: User, purchase: Purchase) -> None:
    """Abandon every game of the purchase, then mark it refunded."""
    correlation_id = new_correlation_id()
    games = list(purchase.games.all())
    for abandoned, game in enumerate(games):
        try:
            record_facts(
                user,
                game,
                status=PlayerGameStatus.ABANDONED,
                correlation_id=correlation_id,
            )
        except CommandFailed as failure:
            if not abandoned:
                raise
            #: Say how far it went: the earlier games are
            #: abandoned already and no rollback takes them
            #: back. Refunding again restates the same fact,
            #: which build() absorbs, so a retry is safe.
            raise CommandFailed(
                f"{failure.message} {abandoned} of {len(games)} games were "
                "abandoned before this one. Refunding again is safe.",
                failure.status_code,
            ) from failure
    purchase.refund()


@login_required
def refund_purchase(request: HttpRequest, purchase_id: UUID) -> HttpResponse:
    library = cast(User, request.user).library
    purchase = owned_or_404(
        Purchase.objects.for_library(library), library, id=purchase_id
    )

    def refund() -> None:
        _refund(cast(User, request.user), purchase)
        messages.success(request, "Purchase refunded")

    return confirm_and_apply(
        request,
        action=refund,
        title="Refund purchase",
        message=(
            f"Mark this purchase of {purchase.first_game} as refunded? "
            "Its games will be marked as abandoned."
        ),
        confirm_label="Refund",
        fallback="games:list_purchases",
    )


def _split(purchase: Purchase) -> int:
    """Replace one multi-game purchase with one purchase per game.

    The price is split evenly as a starting point. Each new purchase
    is then priced and refunded on its own. Answers how many there are.
    """
    games = list(purchase.games.all())
    count = len(games)
    if count < 2:
        return count
    #: No dispatch here: run_in_transaction refuses to nest.
    with transaction.atomic():
        share = purchase.price / count
        for game in games:
            new_purchase = Purchase(
                library=purchase.library,
                price=share,
                price_currency=purchase.price_currency,
                date_purchased=purchase.date_purchased,
                date_refunded=purchase.date_refunded,
                infinite=purchase.infinite,
                ownership_type=purchase.ownership_type,
                type=purchase.type,
                related_game=purchase.related_game,
                name=purchase.name,
                platform=purchase.platform,
                needs_price_update=True,
            )
            new_purchase.save()
            new_purchase.games.set([game])
        #: The parts carry the facts now.
        remove(purchase)
    return count


@login_required
def split_purchase(request: HttpRequest, purchase_id: UUID) -> HttpResponse:
    library = cast(User, request.user).library
    purchase = owned_or_404(
        Purchase.objects.for_library(library), library, id=purchase_id
    )
    count = purchase.num_purchases

    def split() -> None:
        parts = _split(purchase)
        if parts > 1:
            messages.success(request, f"Split into {parts} purchases")

    return confirm_and_apply(
        request,
        action=split,
        title="Split purchase",
        message=f"Split “{purchase.standardized_name}” into per-game purchases?",
        details=P(class_="text-type-body")[
            f"Creates {count} separate purchases, one per game, with the "
            "price split evenly. Each can then be priced and refunded "
            "independently."
        ],
        confirm_label="Split",
        fallback="games:list_purchases",
        #: The bundle's own page is gone once it splits.
        reject=reverse("games:view_purchase", args=[purchase_id])
        if count > 1
        else None,
    )
