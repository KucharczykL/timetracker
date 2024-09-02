from typing import Any

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse

from common.utils import A, truncate_with_popover
from games.forms import EditionForm
from games.models import Edition, Game
from games.views.general import dateformat


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
                    A(
                        [
                            (
                                "href",
                                reverse(
                                    "view_game",
                                    args=[edition.game.pk],
                                ),
                            )
                        ],
                        truncate_with_popover(edition.game.name),
                    ),
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
                        "cotton/button_group_sm.html",
                        {
                            "buttons": [
                                {
                                    "href": reverse("edit_edition", args=[edition.pk]),
                                    "text": "Edit",
                                    "color": "gray",
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
def edit_edition(request: HttpRequest, edition_id: int = 0) -> HttpResponse:
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


@login_required
def add_edition(request: HttpRequest, game_id: int = 0) -> HttpResponse:
    context: dict[str, Any] = {}
    if request.method == "POST":
        form = EditionForm(request.POST or None)
        if form.is_valid():
            edition = form.save()
            if "submit_and_redirect" in request.POST:
                return HttpResponseRedirect(
                    reverse(
                        "add_purchase_for_edition", kwargs={"edition_id": edition.id}
                    )
                )
            else:
                return redirect("index")
    else:
        if game_id:
            game = get_object_or_404(Game, id=game_id)
            form = EditionForm(
                initial={
                    "game": game,
                    "name": game.name,
                    "sort_name": game.sort_name,
                    "year_released": game.year_released,
                }
            )
        else:
            form = EditionForm()

    context["form"] = form
    context["title"] = "Add New Edition"
    context["script_name"] = "add_edition.js"
    return render(request, "add_edition.html", context)
