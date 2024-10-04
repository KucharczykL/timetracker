from typing import Any

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import (
    HttpRequest,
    HttpResponse,
    HttpResponseBadRequest,
    HttpResponseRedirect,
)
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from common.components import A, Button, Icon, LinkedNameWithPlatformIcon
from common.time import dateformat
from common.utils import format_float_or_int
from games.forms import PurchaseForm
from games.models import Edition, Purchase
from games.views.general import use_custom_redirect


@login_required
def list_purchases(request: HttpRequest) -> HttpResponse:
    context: dict[Any, Any] = {}
    page_number = request.GET.get("page", 1)
    limit = request.GET.get("limit", 10)
    purchases = Purchase.objects.order_by("-date_purchased")
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
            "header_action": A([], Button([], "Add purchase"), url="add_purchase"),
            "columns": [
                "Name",
                "Type",
                "Price",
                "Currency",
                "Infinite",
                "Purchased",
                "Refunded",
                "Finished",
                "Dropped",
                "Created",
                "Actions",
            ],
            "rows": [
                [
                    LinkedNameWithPlatformIcon(
                        name=purchase.edition.name,
                        game_id=purchase.edition.game.pk,
                        platform=purchase.platform,
                    ),
                    purchase.get_type_display(),
                    format_float_or_int(purchase.price),
                    purchase.price_currency,
                    purchase.infinite,
                    purchase.date_purchased.strftime(dateformat),
                    (
                        purchase.date_refunded.strftime(dateformat)
                        if purchase.date_refunded
                        else "-"
                    ),
                    (
                        purchase.date_finished.strftime(dateformat)
                        if purchase.date_finished
                        else "-"
                    ),
                    (
                        purchase.date_dropped.strftime(dateformat)
                        if purchase.date_dropped
                        else "-"
                    ),
                    purchase.created_at.strftime(dateformat),
                    render_to_string(
                        "cotton/button_group.html",
                        {
                            "buttons": [
                                {
                                    "href": reverse(
                                        "finish_purchase", args=[purchase.pk]
                                    ),
                                    "slot": Icon("checkmark"),
                                    "title": "Mark as finished",
                                }
                                if not purchase.date_finished
                                else {},
                                {
                                    "href": reverse(
                                        "drop_purchase", args=[purchase.pk]
                                    ),
                                    "slot": Icon("eject"),
                                    "title": "Mark as dropped",
                                }
                                if not purchase.date_dropped
                                else {},
                                {
                                    "href": reverse(
                                        "refund_purchase", args=[purchase.pk]
                                    ),
                                    "slot": Icon("refund"),
                                    "title": "Mark as refunded",
                                }
                                if not purchase.date_refunded
                                else {},
                                {
                                    "href": reverse(
                                        "edit_purchase", args=[purchase.pk]
                                    ),
                                    "slot": Icon("edit"),
                                    "title": "Edit",
                                    "color": "gray",
                                },
                                {
                                    "href": reverse(
                                        "delete_purchase", args=[purchase.pk]
                                    ),
                                    "slot": Icon("delete"),
                                    "title": "Delete",
                                    "color": "red",
                                },
                            ]
                        },
                    ),
                ]
                for purchase in purchases
            ],
        },
    }
    return render(request, "list_purchases.html", context)


@login_required
def add_purchase(request: HttpRequest, edition_id: int = 0) -> HttpResponse:
    context: dict[str, Any] = {}
    initial = {"date_purchased": timezone.now()}

    if request.method == "POST":
        form = PurchaseForm(request.POST or None, initial=initial)
        if form.is_valid():
            purchase = form.save()
            if "submit_and_redirect" in request.POST:
                return HttpResponseRedirect(
                    reverse(
                        "add_session_for_purchase", kwargs={"purchase_id": purchase.id}
                    )
                )
            else:
                return redirect("list_purchases")
    else:
        if edition_id:
            edition = Edition.objects.get(id=edition_id)
            form = PurchaseForm(
                initial={
                    **initial,
                    "edition": edition,
                    "platform": edition.platform,
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
        return redirect("list_sessions")
    context["title"] = "Edit Purchase"
    context["form"] = form
    context["purchase_id"] = str(purchase_id)
    context["script_name"] = "add_purchase.js"
    return render(request, "add_purchase.html", context)


@login_required
def delete_purchase(request: HttpRequest, purchase_id: int) -> HttpResponse:
    purchase = get_object_or_404(Purchase, id=purchase_id)
    purchase.delete()
    return redirect("list_purchases")


@login_required
def drop_purchase(request: HttpRequest, purchase_id: int) -> HttpResponse:
    purchase = get_object_or_404(Purchase, id=purchase_id)
    purchase.date_dropped = timezone.now()
    purchase.save()
    return redirect("list_purchases")


@login_required
def refund_purchase(request: HttpRequest, purchase_id: int) -> HttpResponse:
    purchase = get_object_or_404(Purchase, id=purchase_id)
    purchase.date_refunded = timezone.now()
    purchase.save()
    return redirect("list_purchases")


@login_required
def finish_purchase(request: HttpRequest, purchase_id: int) -> HttpResponse:
    purchase = get_object_or_404(Purchase, id=purchase_id)
    purchase.date_finished = timezone.now()
    purchase.save()
    return redirect("list_purchases")


def related_purchase_by_edition(request: HttpRequest) -> HttpResponse:
    edition_id = request.GET.get("edition")
    if not edition_id:
        return HttpResponseBadRequest("Invalid edition_id")
    form = PurchaseForm()
    form.fields["related_purchase"].queryset = Purchase.objects.filter(
        edition_id=edition_id, type=Purchase.GAME
    ).order_by("edition__sort_name")
    return render(request, "partials/related_purchase_field.html", {"form": form})
