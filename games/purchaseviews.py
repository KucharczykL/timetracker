from typing import Any

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models.manager import BaseManager
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.template.loader import render_to_string
from django.urls import reverse

from games.models import Purchase
from games.views import dateformat


@login_required
def list_purchases(request: HttpRequest) -> HttpResponse:
    context: dict[Any, Any] = {}
    page_number = request.GET.get("page", 1)
    limit = request.GET.get("limit", 10)
    purchases = Purchase.objects.order_by("-date_purchased")
    page_obj = None
    if int(limit) != 0:
        paginator = Paginator(Purchase.objects.order_by("-date_purchased"), limit)
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
            "columns": [
                "Name",
                "Platform",
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
                    purchase.edition.name,
                    purchase.platform,
                    purchase.price,
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
                        "components/button_group_sm.html",
                        {
                            "buttons": [
                                {
                                    "href": reverse(
                                        "edit_purchase", args=[purchase.pk]
                                    ),
                                    "text": "Edit",
                                },
                                {
                                    "href": reverse(
                                        "delete_purchase", args=[purchase.pk]
                                    ),
                                    "text": "Delete",
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
