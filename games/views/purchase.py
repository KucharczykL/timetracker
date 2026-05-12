from typing import Any

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import (
    HttpRequest,
    HttpResponse,
    HttpResponseRedirect,
)
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from common.components import A, Button, Icon, LinkedPurchase, PurchasePrice
from common.time import dateformat
from games.forms import PurchaseForm
from games.models import Game, Purchase
from games.views.general import use_custom_redirect


def _render_purchase_buttons(purchase_id, is_refunded):
    """Return button group HTML for a purchase row."""
    return render_to_string(
        "cotton/button_group.html",
        {
            "buttons": [
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
        },
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
    context: dict[Any, Any] = {}
    page_number = request.GET.get("page", 1)
    limit = request.GET.get("limit", 10)
    purchases = Purchase.objects.order_by("-date_purchased", "-created_at")
    page_obj = None
    if int(limit) != 0:
        paginator = Paginator(purchases, limit)
        page_obj = paginator.get_page(page_number)
        purchases = page_obj.object_list

    context = {
        "title": "Manage purchases",
        "page_obj": page_obj or None,
        "elided_page_range": (
            page_obj.paginator.get_elided_page_range(
                page_number, on_each_side=1, on_ends=1
            )
            if page_obj
            else None
        ),
        "data": {
            "header_action": A([], Button([], "Add purchase"), url_name="games:add_purchase"),
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
        },
    }
    return render(request, "list_purchases.html", context)


@login_required
def add_purchase(request: HttpRequest, game_id: int = 0) -> HttpResponse:
    context: dict[str, Any] = {}
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

    context["form"] = form
    context["title"] = "Add New Purchase"
    context["script_name"] = "add_purchase.js"
    return render(request, "add_purchase.html", context)


@login_required
@use_custom_redirect
def edit_purchase(request: HttpRequest, purchase_id: int) -> HttpResponse:
    context = {}
    purchase = get_object_or_404(Purchase, id=purchase_id)
    form = PurchaseForm(request.POST or None, instance=purchase)
    if form.is_valid():
        form.save()
        return redirect("games:list_sessions")
    context["title"] = "Edit Purchase"
    context["form"] = form
    context["purchase_id"] = str(purchase_id)
    context["script_name"] = "add_purchase.js"
    return render(request, "add_purchase.html", context)


@login_required
def delete_purchase(request: HttpRequest, purchase_id: int) -> HttpResponse:
    purchase = get_object_or_404(Purchase, id=purchase_id)
    purchase.delete()
    return redirect("games:list_purchases")


@login_required
def view_purchase(request: HttpRequest, purchase_id: int) -> HttpResponse:
    purchase = get_object_or_404(Purchase, id=purchase_id)
    return render(
        request,
        "view_purchase.html",
        {"purchase": purchase, "title": f"Purchase: {purchase.full_name}"},
    )


@login_required
def drop_purchase(request: HttpRequest, purchase_id: int) -> HttpResponse:
    purchase = get_object_or_404(Purchase, id=purchase_id)
    for game in purchase.games.all():
        game.status = Game.Status.ABANDONED
        game.save()
    return redirect("games:list_purchases")


@login_required
def refund_purchase_confirmation(
    request: HttpRequest, purchase_id: int
) -> HttpResponse:
    return render(
        request,
        "partials/refund_purchase_confirmation.html",
        {"purchase_id": purchase_id},
    )


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
    row_html = render_to_string(
        "cotton/table_row.html",
        {"data": row_data},
    )
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
    games: list[str] = []
    games = request.GET.getlist("games")
    context = {}
    if games:
        form = PurchaseForm()
        qs = Purchase.objects.filter(games__in=games, type=Purchase.GAME).order_by(
            "games__sort_name"
        )

        form.fields["related_purchase"].queryset = qs
        first_option = qs.first()
        if first_option:
            form.fields["related_purchase"].initial = first_option.id
        context["form"] = form
        return render(request, "partials/related_purchase_field.html", context)
    else:
        # abort swap
        return HttpResponse(status=204)
