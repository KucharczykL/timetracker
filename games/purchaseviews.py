from typing import Any

from django.contrib.auth.decorators import login_required
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
    purchases: BaseManager[Purchase] = Purchase.objects.all()[0:10]
    context = {
        "title": "Manage purchases",
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
