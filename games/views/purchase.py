from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import (
    HttpRequest,
    HttpResponse,
    HttpResponseRedirect,
)
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect
from django.template.defaultfilters import date as date_filter
from django.template.defaultfilters import floatformat
from django.urls import reverse
from django.utils import timezone
from django.utils.safestring import SafeText, mark_safe
from django.views.decorators.http import require_POST

from common.components import (
    A,
    AddForm,
    ButtonGroup,
    Checkbox,
    CsrfInput,
    Div,
    Element,
    FormFields,
    Fragment,
    GameLink,
    Icon,
    Input,
    LinkedPurchase,
    Modal,
    ModuleScript,
    Node,
    PriceConverted,
    PurchasePrice,
    SelectionFields,
    StyledButton,
    TableRow,
    paginated_table_content,
)
from common.components.primitives import Li, P, Td, Tr, Ul
from common.layout import render_page
from common.time import dateformat
from common.utils import paginate
from games.forms import PurchaseForm
from games.models import Game, Purchase
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
                "slot": Icon("refund"),
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
                "slot": Icon("split"),
                "title": "Split into per-game purchases",
                "color": "gray",
            }
            if can_split
            else {},
            {
                "href": reverse("games:edit_purchase", args=[purchase_id]),
                "slot": Icon("edit"),
                "title": "Edit",
                "color": "gray",
            },
            {
                "href": reverse("games:delete_purchase", args=[purchase_id]),
                "slot": Icon("delete"),
                "title": "Delete",
                "color": "red",
            },
        ]
    )


def _render_purchase_row(purchase):
    """Return a row dict for simple-table rendering."""
    return {
        "row_id": f"purchase-row-{purchase.id}",
        "cell_data": [
            LinkedPurchase(purchase),
            purchase.get_type_display(),
            PurchasePrice(purchase),
            purchase.infinite,
            purchase.date_purchased.strftime(dateformat),
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
        ],
    }


@login_required
def list_purchases(request: HttpRequest) -> HttpResponse:
    purchases = Purchase.objects.order_by("-date_purchased", "-created_at")

    filter_json = request.GET.get("filter", "")
    if filter_json:
        from games.filters import parse_purchase_filter

        pf = parse_purchase_filter(filter_json)
        if pf is not None:
            purchases = purchases.filter(pf.to_q())

    purchases, page_obj, elided_page_range = paginate(request, purchases)

    data = {
        "header_action": A(href=reverse("games:add_purchase"))[
            StyledButton()["Add purchase"]
        ],
        "columns": [
            "Name",
            "Type",
            "Price",
            "Infinite",
            "Purchased",
            "Refunded",
            "Created",
            "Actions",
        ],
        "rows": [_render_purchase_row(purchase) for purchase in purchases],
    }
    content = paginated_table_content(
        data,
        page_obj=page_obj,
        elided_page_range=elided_page_range,
        request=request,
    )
    from common.components import PurchaseFilterBar

    filter_bar = PurchaseFilterBar(
        filter_json=filter_json,
        preset_list_url=reverse("games:list_presets"),
        preset_save_url=reverse("games:save_preset"),
    )
    content = Fragment(filter_bar, content)
    return render_page(
        request,
        content,
        title="Manage purchases",
    )


def _purchase_additional_row() -> SafeText:
    """The 'Submit & Create Session' row shown below the main Submit button."""
    return Tr(
        children=[
            Td(),
            Td(
                children=[
                    StyledButton(
                        [],
                        "Submit & Create Session",
                        color="gray",
                        type="submit",
                        name="submit_and_redirect",
                    )
                ],
            ),
        ],
    )


def _pricing_controls() -> Node:
    """Pricing UI for the add-purchase form.

    By default the form's own single Price field is the bundle price. When 2+
    games are selected and "Separate price per game" is checked, the per-game
    inputs (the general ``selection-fields`` element) take over and the bundle
    Price is hidden. Toggle/visibility wiring lives in ts/add_purchase.ts; the
    hidden ``pricing_mode`` tells the view which path to take.
    """
    return Div(attributes=[("id", "pricing-controls")])[
        Div(attributes=[("id", "separate-prices-row"), ("class", "hidden")])[
            Checkbox(
                name="separate_prices",
                label="Separate price per game",
                attributes=[("id", "id_separate_prices")],
            ),
        ],
        Input(
            type="hidden",
            attributes=[
                ("name", "pricing_mode"),
                ("id", "id_pricing_mode"),
                ("value", "combined"),
            ],
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
        scripts=mark_safe(
            ModuleScript("dist/elements/search-select.js")
            + ModuleScript("dist/add_purchase.js")
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
        scripts=mark_safe(
            ModuleScript("dist/elements/search-select.js")
            + ModuleScript("dist/add_purchase.js")
        ),
    )


@login_required
def delete_purchase(request: HttpRequest, purchase_id: int) -> HttpResponse:
    purchase = get_object_or_404(Purchase, id=purchase_id)
    purchase.delete()
    return redirect("games:list_purchases")


def _view_purchase_content(purchase: Purchase) -> SafeText:
    first_game = purchase.first_game
    owned = f"Owned on {date_filter(purchase.date_purchased, 'd/m/Y')}"
    if purchase.date_refunded:
        owned += f" (refunded {date_filter(purchase.date_refunded, 'd/m/Y')})"

    row_class = "text-slate-500 text-xl"
    inner = Div(
        [("class", "flex flex-col gap-5 mb-3")],
        [
            Div(
                [("class", "font-bold font-serif text-slate-500 text-2xl")],
                [
                    A(
                        [],
                        first_game.name,
                        href=reverse("games:view_game", args=[first_game.id]),
                    )
                ],
            ),
            Div([("class", row_class)], [purchase.get_type_display()]),
            Div([("class", row_class)], [owned]),
            Div(
                [("class", row_class)], [PriceConverted([purchase.standardized_price])]
            ),
            Div(
                [("class", row_class)],
                [
                    P(
                        children=[
                            "Price per game: ",
                            PriceConverted([floatformat(purchase.price_per_game, 0)]),
                            f" {purchase.converted_currency}",
                        ],
                    )
                ],
            ),
            Div([("class", row_class)], ["Games included in this purchase:"]),
            Ul(
                children=[
                    Li(children=[GameLink(game.id, game.name)])
                    for game in purchase.games.all()
                ],
            ),
        ],
    )
    return Div(
        [("class", "dark:text-white max-w-sm sm:max-w-xl lg:max-w-3xl mx-auto")],
        [inner],
    )


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
    form = Element(
        "form",
        attributes=[
            ("hx-post", reverse("games:refund_purchase", args=[purchase_id])),
            ("hx-target", f"#purchase-row-{purchase_id}"),
            ("hx-swap", "outerHTML"),
        ],
        children=[
            CsrfInput(request),
            P(
                attributes=[("class", "dark:text-white text-center mt-3 text-sm")],
                children=["Games will be marked as abandoned."],
            ),
            Div(
                [("class", "items-center mt-5")],
                [
                    StyledButton(
                        [("class", "w-full")],
                        "Refund",
                        color="blue",
                        size="lg",
                        type="submit",
                    ),
                    StyledButton(
                        [("class", "mt-0 w-full")],
                        "Cancel",
                        color="gray",
                        size="base",
                        onclick="this.closest('#refund-confirmation-modal').remove()",
                    ),
                ],
            ),
        ],
    )
    return Modal(
        "refund-confirmation-modal",
        children=[
            Element(
                "h1",
                attributes=[
                    (
                        "class",
                        "text-2xl leading-6 font-medium dark:text-white text-center",
                    )
                ],
                children=["Confirm Refund"],
            ),
            P(
                attributes=[("class", "dark:text-white text-center mt-5")],
                children=["Are you sure you want to mark this purchase as refunded?"],
            ),
            form,
        ],
    )


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
    form = Element(
        "form",
        attributes=[("hx-post", reverse("games:split_purchase", args=[purchase.id]))],
        children=[
            CsrfInput(request),
            P(
                attributes=[("class", "dark:text-white text-center mt-3 text-sm")],
                children=[
                    f"Creates {count} separate purchases, one per game, with the "
                    "price split evenly. Each can then be priced and refunded "
                    "independently."
                ],
            ),
            Div(
                [("class", "items-center mt-5")],
                [
                    StyledButton(
                        [("class", "w-full")],
                        "Split",
                        color="blue",
                        size="lg",
                        type="submit",
                    ),
                    StyledButton(
                        [("class", "mt-0 w-full")],
                        "Cancel",
                        color="gray",
                        size="base",
                        onclick="this.closest('#split-confirmation-modal').remove()",
                    ),
                ],
            ),
        ],
    )
    return Modal(
        "split-confirmation-modal",
        children=[
            Element(
                "h1",
                attributes=[
                    (
                        "class",
                        "text-2xl leading-6 font-medium dark:text-white text-center",
                    )
                ],
                children=["Split purchase"],
            ),
            P(
                attributes=[("class", "dark:text-white text-center mt-5")],
                children=[
                    f"Split “{purchase.standardized_name}” into per-game purchases?"
                ],
            ),
            form,
        ],
    )


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
