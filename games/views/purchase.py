from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import (
    HttpRequest,
    HttpResponse,
    HttpResponseRedirect,
)
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
    Button,
    ButtonGroup,
    Component,
    CsrfInput,
    Div,
    GameLink,
    Icon,
    LinkedPurchase,
    Modal,
    ModuleScript,
    PriceConverted,
    PurchasePrice,
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


def _render_purchase_buttons(purchase_id, is_refunded):
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
            _render_purchase_buttons(purchase.id, bool(purchase.date_refunded)),
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
        "header_action": A(
            [], Button([], "Add purchase"), url_name="games:add_purchase"
        ),
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
    from common.components import ModuleScript, PurchaseFilterBar

    filter_bar = PurchaseFilterBar(
        filter_json=filter_json,
        preset_list_url=reverse("games:list_presets"),
        preset_save_url=reverse("games:save_preset"),
    )
    content = mark_safe(str(filter_bar) + str(content))
    return render_page(
        request,
        content,
        title="Manage purchases",
        scripts=ModuleScript("range_slider.js")
        + ModuleScript("search_select.js")
        + ModuleScript("filter_bar.js"),
    )


def _purchase_additional_row() -> SafeText:
    """The 'Submit & Create Session' row shown below the main Submit button."""
    return Tr(
        children=[
            Td(),
            Td(
                children=[
                    Button(
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


@login_required
def add_purchase(request: HttpRequest, game_id: int = 0) -> HttpResponse:
    initial = {"date_purchased": timezone.now()}

    if request.method == "POST":
        form = PurchaseForm(request.POST or None, initial=initial)
        if form.is_valid():
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
        AddForm(form, request=request, additional_row=_purchase_additional_row()),
        title="Add New Purchase",
        scripts=mark_safe(
            ModuleScript("search_select.js") + ModuleScript("add_purchase.js")
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
            ModuleScript("search_select.js") + ModuleScript("add_purchase.js")
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


def _refund_confirmation_modal(purchase_id: int, request: HttpRequest) -> SafeText:
    form = Component(
        tag_name="form",
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
                    Button(
                        [("class", "w-full")],
                        "Refund",
                        color="blue",
                        size="lg",
                        type="submit",
                    ),
                    Button(
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
            Component(
                tag_name="h1",
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


@login_required
def finish_purchase(request: HttpRequest, purchase_id: int) -> HttpResponse:
    purchase = get_object_or_404(Purchase, id=purchase_id)
    for game in purchase.games.all():
        game.status = Game.Status.FINISHED
        game.save()
    return redirect("games:list_purchases")


def related_purchase_by_game(request: HttpRequest) -> HttpResponse:
    games: list[str] = request.GET.getlist("games")
    if games:
        from games.forms import related_purchase_queryset

        form = PurchaseForm()
        qs = (
            related_purchase_queryset()
            .filter(games__in=games)
            .order_by("games__sort_name")
        )

        form.fields["related_purchase"].queryset = qs
        first_option = qs.first()
        if first_option:
            form.fields["related_purchase"].initial = first_option.id
        return HttpResponse(str(form["related_purchase"]))
    else:
        # abort swap
        return HttpResponse(status=204)
