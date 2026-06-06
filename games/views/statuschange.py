from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.safestring import SafeText

from common.components import (
    A,
    AddForm,
    Button,
    Component,
    CsrfInput,
    Div,
    paginated_table_content,
)
from common.layout import render_page
from common.time import dateformat, local_strftime
from games.forms import GameStatusChangeForm
from games.models import GameStatusChange


@login_required
def add_statuschange(request: HttpRequest) -> HttpResponse:
    form = GameStatusChangeForm(request.POST or None)
    if form.is_valid():
        obj = form.save()
        return redirect("games:view_game", game_id=obj.game.id)
    return render_page(
        request, AddForm(form, request=request), title="Add status change"
    )


@login_required
def edit_statuschange(request: HttpRequest, statuschange_id: int) -> HttpResponse:
    statuschange = get_object_or_404(GameStatusChange, id=statuschange_id)
    form = GameStatusChangeForm(request.POST or None, instance=statuschange)
    if form.is_valid():
        form.save()
        return redirect("games:list_platforms")
    return render_page(
        request, AddForm(form, request=request), title="Edit status change"
    )


@login_required
def list_statuschanges(request: HttpRequest) -> HttpResponse:
    page_number = request.GET.get("page", 1)
    limit = request.GET.get("limit", 10)
    statuschanges = GameStatusChange.objects.select_related("game").all()
    page_obj = None
    if int(limit) != 0:
        paginator = Paginator(statuschanges, limit)
        page_obj = paginator.get_page(page_number)
        statuschanges = page_obj.object_list
    elided_page_range = (
        page_obj.paginator.get_elided_page_range(page_number, on_each_side=1, on_ends=1)
        if page_obj
        else None
    )

    data = {
        "header_action": None,
        "columns": ["Game", "Old Status", "New Status", "Timestamp"],
        "rows": [
            [
                sc.game.name,
                sc.get_old_status_display() if sc.old_status else "-",
                sc.get_new_status_display(),
                local_strftime(sc.timestamp, dateformat) if sc.timestamp else "-",
            ]
            for sc in statuschanges
        ],
    }
    content = paginated_table_content(
        data,
        page_obj=page_obj,
        elided_page_range=elided_page_range,
        request=request,
    )
    return render_page(request, content, title="Status changes")


def _delete_statuschange_content(statuschange, request: HttpRequest) -> SafeText:
    inner = Div(
        [],
        [
            Component(
                tag_name="p",
                children=["Are you sure you want to delete this status change?"],
            ),
            Button(
                [("class", "w-full")], "Delete", color="red", type="submit", size="lg"
            ),
            A(
                [("class", "")],
                Button([("class", "w-full")], "Cancel", color="gray"),
                href=reverse("games:view_game", args=[statuschange.game.id]),
            ),
        ],
    )
    form = Component(
        tag_name="form",
        attributes=[("method", "post"), ("class", "dark:text-white")],
        children=[CsrfInput(request), inner],
    )
    return Div(
        [
            (
                "class",
                "2xl:max-w-(--breakpoint-2xl) xl:max-w-(--breakpoint-xl) "
                "md:max-w-(--breakpoint-md) sm:max-w-(--breakpoint-sm) self-center",
            )
        ],
        [form],
    )


@login_required
def delete_statuschange(request: HttpRequest, pk: int) -> HttpResponse:
    statuschange = get_object_or_404(GameStatusChange, id=pk)
    if request.method == "POST":
        game_id = statuschange.game.id
        statuschange.delete()
        return redirect("games:view_game", game_id=game_id)
    return render_page(
        request,
        _delete_statuschange_content(statuschange, request),
        title="Delete status change",
    )
