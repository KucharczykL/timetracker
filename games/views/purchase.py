from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import (
    HttpRequest,
    HttpResponse,
    HttpResponseRedirect,
)
from django.db import transaction
from django.db.models import QuerySet
from django.shortcuts import get_object_or_404, redirect
from django.template.defaultfilters import date as date_filter
from django.template.defaultfilters import floatformat
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from common.components import (
    A,
    AddForm,
    ButtonGroup,
    Checkbox,
    Column,
    ContentContainer,
    CsrfInput,
    Div,
    Form,
    FormFields,
    H1,
    Fragment,
    GameLink,
    ICON_BUTTON_SIZE_CLASS,
    Icon,
    Input,
    LinkedPurchase,
    Modal,
    ModuleScript,
    Node,
    PriceConverted,
    PurchasePrice,
    SelectionFields,
    ControlButton,
    TableData,
    TableRow,
    TableRowData,
    make_row,
    paginated_table_content,
)
from common.components.primitives import Li, P, Ul
from common.layout import render_page
from common.time import dateformat
from common.utils import paginate
from games.forms import PurchaseForm
from games.models import Game, PlayEvent, Purchase
from games.sorting import (
    PURCHASE_DEFAULT_SORT,
    PURCHASE_SORTS,
    apply_sort,
    parse_find_filter,
)
from games.views.filtering import warn_unknown_sort
from games.views.general import use_custom_redirect


def _render_purchase_buttons(purchase_id, is_refunded, can_split=False):
    """Return button group HTML for a purchase row."""
    return ButtonGroup(
        [
            {
                "href": "#",
                "hx_get": reverse(
                    "games:refund_purchase_confirmation",
                    args=[purchase_id],
                ),
                "hx_target": "#global-modal-container",
                "slot": Icon("refund", size=ICON_BUTTON_SIZE_CLASS),
                "title": "Mark as refunded",
            }
            if not is_refunded
            else {},
            {
                "href": "#",
                "hx_get": reverse(
                    "games:split_purchase_confirmation",
                    args=[purchase_id],
                ),
                "hx_target": "#global-modal-container",
                "slot": Icon("split", size=ICON_BUTTON_SIZE_CLASS),
                "title": "Split into per-game purchases",
                "color": "gray",
            }
            if can_split
            else {},
            {
                "href": reverse("games:edit_purchase", args=[purchase_id]),
                "slot": Icon("edit", size=ICON_BUTTON_SIZE_CLASS),
                "title": "Edit",
                "color": "gray",
            },
            {
                "href": reverse("games:delete_purchase", args=[purchase_id]),
                "slot": Icon("delete", size=ICON_BUTTON_SIZE_CLASS),
                "title": "Delete",
                "color": "red",
            },
        ]
    )


def _render_purchase_row(purchase: Purchase) -> TableRowData:
    """Return a row for simple-table rendering."""
    # TODO: simplify if multiple purchases are no longer allowed
    date_finished = "-"
    try:
        latest_play_event = PlayEvent.objects.filter(
            game__in=purchase.games.all(),
            ended__isnull=False,
        ).latest("ended")
        if latest_play_event:
            if latest_play_event.ended:
                date_finished = latest_play_event.ended.strftime(dateformat)
    except PlayEvent.DoesNotExist:
        pass
    return make_row(
        LinkedPurchase(purchase),
        purchase.get_type_display(),
        PurchasePrice(purchase),
        str(purchase.infinite),
        purchase.date_purchased.strftime(dateformat),
        date_finished,
        (
            purchase.date_refunded.strftime(dateformat)
            if purchase.date_refunded
            else "-"
        ),
        purchase.created_at.strftime(dateformat),
        _render_purchase_buttons(
            purchase.id,
            bool(purchase.date_refunded),
            can_split=purchase.num_purchases > 1,
        ),
        id=f"purchase-row-{purchase.id}",
    )


@login_required
def list_purchases(request: HttpRequest) -> HttpResponse:
    purchases: QuerySet[Purchase] = Purchase.objects.select_related(
        "platform"
    ).prefetch_related("games", "games__platform")

    filter_json = request.GET.get("filter", "")
    if filter_json:
        from games.filters import parse_purchase_filter
        from games.views.filtering import apply_structured_filter

        purchase_filter = apply_structured_filter(
            request, parse_purchase_filter, filter_json
        )
        if purchase_filter is not None:
            purchases = purchases.filter(purchase_filter.to_q())

    sort = apply_sort(
        purchases, parse_find_filter(request), PURCHASE_SORTS, PURCHASE_DEFAULT_SORT
    )
    purchases = sort.queryset
    warn_unknown_sort(request, sort.unknown, entity="purchase")

    purchases, page_obj, elided_page_range = paginate(request, purchases)

    data: TableData = {
        "header_action": ControlButton(href=reverse("games:add_purchase"))[
            "Add purchase"
        ],
        "columns": [
            Column("Name", "name"),
            Column("Type", "type"),
            Column("Price", "price"),
            Column("Infinite", "infinite"),
            Column("Purchased", "purchased"),
            Column("Finished", "finished"),
            Column("Refunded", "refunded"),
            Column("Created", "created"),
            Column("Actions", align="right"),
        ],
        "sort_terms": sort.terms,
        "rows": [_render_purchase_row(purchase) for purchase in purchases],
    }
    content = paginated_table_content(
        data,
        page_obj=page_obj,
        elided_page_range=elided_page_range,
        request=request,
    )
    from common.components import (
        QuickFilterBar,
        parse_filter_dict,
    )
    from games.views.filtering import builder_url_for

    builder_url = builder_url_for("purchases", filter_json)
    parsed_filter = parse_filter_dict(filter_json)
    quick_bar = QuickFilterBar(
        mode="purchases",
        existing=parsed_filter,
        builder_url=builder_url,
        preset_api_url=reverse("api-1.0.0:list_presets"),
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


@transaction.atomic
def _create_separate_purchases(form: PurchaseForm, post) -> None:
    """Create one single-game Purchase per selected game from the shared form
    fields, each priced from its own ``price_for_game_<id>`` input. The
    ``m2m_changed`` signal sets ``num_purchases``/``price_per_game`` once each
    game is attached."""
    data = form.cleaned_data
    shared = {
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
def add_purchase(request: HttpRequest, game_id: int = 0) -> HttpResponse:
    initial = {"date_purchased": timezone.now()}

    if request.method == "POST":
        form = PurchaseForm(request.POST or None, initial=initial)
        if form.is_valid():
            if request.POST.get("pricing_mode") == "per_game":
                _create_separate_purchases(form, request.POST)
                return redirect("games:list_purchases")
            purchase = form.save()
            if "submit_and_redirect" in request.POST:
                return HttpResponseRedirect(
                    reverse(
                        "games:add_session_for_game",
                        kwargs={"game_id": purchase.first_game.id},
                    )
                )
            else:
                return redirect("games:list_purchases")
    else:
        if game_id:
            game = Game.objects.get(id=game_id)
            form = PurchaseForm(
                initial={
                    **initial,
                    "games": [game],
                    "platform": game.platform,
                }
            )
        else:
            form = PurchaseForm(initial=initial)

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
            ModuleScript("dist/add_purchase.js"),
        ),
    )


@login_required
@use_custom_redirect
def edit_purchase(request: HttpRequest, purchase_id: int) -> HttpResponse:
    purchase = get_object_or_404(Purchase, id=purchase_id)
    form = PurchaseForm(request.POST or None, instance=purchase)
    if form.is_valid():
        form.save()
        return redirect("games:list_sessions")
    return render_page(
        request,
        AddForm(form, request=request, additional_row=_purchase_additional_row()),
        title="Edit Purchase",
        scripts=Fragment(
            ModuleScript("dist/elements/search-select.js"),
            ModuleScript("dist/add_purchase.js"),
        ),
    )


@login_required
def delete_purchase(request: HttpRequest, purchase_id: int) -> HttpResponse:
    purchase = get_object_or_404(Purchase, id=purchase_id)
    purchase.delete()
    return redirect("games:list_purchases")


def _view_purchase_content(purchase: Purchase) -> Node:
    first_game = purchase.first_game
    owned = f"Owned on {date_filter(purchase.date_purchased, 'd/m/Y')}"
    if purchase.date_refunded:
        owned += f" (refunded {date_filter(purchase.date_refunded, 'd/m/Y')})"

    row_class = "text-slate-500 text-xl"
    inner = Div(class_="flex flex-col gap-5 mb-3")[
        Div(class_="font-bold font-serif text-slate-500 text-2xl")[
            A(href=reverse("games:view_game", args=[first_game.id]))[first_game.name]
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
        Ul()[[Li()[GameLink(game.id, game.name)] for game in purchase.games.all()]],
    ]
    return ContentContainer(class_="dark:text-white")[inner]


@login_required
def view_purchase(request: HttpRequest, purchase_id: int) -> HttpResponse:
    purchase = get_object_or_404(Purchase, id=purchase_id)
    return render_page(
        request,
        _view_purchase_content(purchase),
        title=f"Purchase: {purchase.full_name}",
    )


@login_required
def drop_purchase(request: HttpRequest, purchase_id: int) -> HttpResponse:
    purchase = get_object_or_404(Purchase, id=purchase_id)
    for game in purchase.games.all():
        game.status = Game.Status.ABANDONED
        game.save()
    return redirect("games:list_purchases")


def _refund_confirmation_modal(purchase_id: int, request: HttpRequest) -> Node:
    form = Form(
        hx_post=reverse("games:refund_purchase", args=[purchase_id]),
        hx_target=f"#purchase-row-{purchase_id}",
        hx_swap="outerHTML",
    )[
        CsrfInput(request),
        P(class_="dark:text-white text-center mt-3 text-sm")[
            "Games will be marked as abandoned."
        ],
        Div(class_="flex flex-col gap-2 mt-5")[
            ControlButton(
                color="blue",
                type="submit",
            )["Refund"],
            ControlButton(
                color="gray",
                onclick="this.closest('#refund-confirmation-modal').remove()",
            )["Cancel"],
        ],
    ]
    return Modal("refund-confirmation-modal")[
        H1(class_="text-2xl leading-6 font-medium dark:text-white text-center")[
            "Confirm Refund"
        ],
        P(class_="dark:text-white text-center mt-5")[
            "Are you sure you want to mark this purchase as refunded?"
        ],
        form,
    ]


@login_required
def refund_purchase_confirmation(
    request: HttpRequest, purchase_id: int
) -> HttpResponse:
    return HttpResponse(_refund_confirmation_modal(purchase_id, request))


@login_required
@require_POST
def refund_purchase(request: HttpRequest, purchase_id: int) -> HttpResponse:
    purchase = get_object_or_404(Purchase, id=purchase_id)

    for game in purchase.games.all():
        game.status = Game.Status.ABANDONED
        game.save()

    purchase.refund()

    messages.success(request, "Purchase refunded")
    row_data = _render_purchase_row(purchase)
    row_html = str(TableRow(data=row_data))
    modal_close = (
        '<template id="refund-confirmation-modal" hx-swap-oob="outerHTML"></template>'
    )
    return HttpResponse(row_html + modal_close, status=200)


def _split_confirmation_modal(purchase: Purchase, request: HttpRequest) -> Node:
    count = purchase.num_purchases
    form = Form(
        hx_post=reverse("games:split_purchase", args=[purchase.id]),
    )[
        CsrfInput(request),
        P(class_="dark:text-white text-center mt-3 text-sm")[
            f"Creates {count} separate purchases, one per game, with the "
            "price split evenly. Each can then be priced and refunded "
            "independently."
        ],
        Div(class_="flex flex-col gap-2 mt-5")[
            ControlButton(
                color="blue",
                type="submit",
            )["Split"],
            ControlButton(
                color="gray",
                onclick="this.closest('#split-confirmation-modal').remove()",
            )["Cancel"],
        ],
    ]
    return Modal("split-confirmation-modal")[
        H1(class_="text-2xl leading-6 font-medium dark:text-white text-center")[
            "Split purchase"
        ],
        P(class_="dark:text-white text-center mt-5")[
            f"Split “{purchase.standardized_name}” into per-game purchases?"
        ],
        form,
    ]


@login_required
def split_purchase_confirmation(request: HttpRequest, purchase_id: int) -> HttpResponse:
    purchase = get_object_or_404(Purchase, id=purchase_id)
    return HttpResponse(_split_confirmation_modal(purchase, request))


@login_required
@require_POST
@transaction.atomic
def split_purchase(request: HttpRequest, purchase_id: int) -> HttpResponse:
    """Replace one multi-game (unsplittable-style) purchase with one single-game
    purchase per game, splitting the price evenly as a starting point. Each new
    purchase is then independently priceable and refundable."""
    purchase = get_object_or_404(Purchase, id=purchase_id)
    games = list(purchase.games.all())
    count = len(games)
    if count > 1:
        share = purchase.price / count
        for game in games:
            new_purchase = Purchase(
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
        purchase.delete()
        messages.success(request, f"Split into {count} purchases")

    response = HttpResponse(status=204)
    response["HX-Redirect"] = reverse("games:list_purchases")
    return response


@login_required
def finish_purchase(request: HttpRequest, purchase_id: int) -> HttpResponse:
    purchase = get_object_or_404(Purchase, id=purchase_id)
    for game in purchase.games.all():
        game.status = Game.Status.FINISHED
        game.save()
    return redirect("games:list_purchases")
