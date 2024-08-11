from typing import Any

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse

from common.utils import truncate_with_popover
from games.forms import EditionForm
from games.models import Edition
from games.views import dateformat


@login_required
def list_editions(request: HttpRequest) -> HttpResponse:
    context: dict[Any, Any] = {}
    page_number = request.GET.get("page", 1)
    limit = request.GET.get("limit", 10)
    editions = Edition.objects.order_by("-created_at")
    page_obj = None
    if int(limit) != 0:
        paginator = Paginator(editions, limit)
        page_obj = paginator.get_page(page_number)
        editions = page_obj.object_list

    context = {
        "title": "Manage editions",
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
                "Game",
                "Name",
                "Sort Name",
                "Platform",
                "Year",
                "Wikidata",
                "Created",
                "Actions",
            ],
            "rows": [
                [
                    truncate_with_popover(edition.game.name),
                    truncate_with_popover(
                        edition.name
                        if edition.game.name != edition.name
                        else "(identical)"
                    ),
                    truncate_with_popover(
                        edition.sort_name
                        if edition.sort_name is not None
                        and edition.game.name != edition.sort_name
                        else "(identical)"
                    ),
                    truncate_with_popover(str(edition.platform)),
                    edition.year_released,
                    edition.wikidata,
                    edition.created_at.strftime(dateformat),
                    render_to_string(
                        "components/button_group_sm.html",
                        {
                            "buttons": [
                                {
                                    "href": reverse("edit_edition", args=[edition.pk]),
                                    "text": "Edit",
                                },
                                {
                                    "href": reverse(
                                        "delete_edition", args=[edition.pk]
                                    ),
                                    "text": "Delete",
                                    "color": "red",
                                },
                            ]
                        },
                    ),
                ]
                for edition in editions
            ],
        },
    }
    return render(request, "list_purchases.html", context)


@login_required
def edit_device(request: HttpRequest, edition_id: int = 0) -> HttpResponse:
    edition = get_object_or_404(Edition, id=edition_id)
    form = EditionForm(request.POST or None, instance=edition)
    if form.is_valid():
        form.save()
        return redirect("list_editions")

    context: dict[str, Any] = {"form": form, "title": "Edit edition"}
    return render(request, "add.html", context)


@login_required
def delete_edition(request: HttpRequest, edition_id: int) -> HttpResponse:
    edition = get_object_or_404(Edition, id=edition_id)
    edition.delete()
    return redirect("list_editions")
