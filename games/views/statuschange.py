from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.middleware.csrf import get_token
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from common.components import (
    AddForm,
    Column,
    ConfirmPage,
    ContentContainer,
    Node,
    TableData,
    make_row,
    paginated_table_content,
)
from common.layout import render_page
from common.date_time_presentation import date_time_presentation_for_request
from common.utils import paginate
from games.sorting import parse_find_filter
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
        saved = form.save()
        return redirect("games:view_game", game_id=saved.game.id)
    return render_page(
        request, AddForm(form, request=request), title="Edit status change"
    )


@login_required
def list_statuschanges(request: HttpRequest) -> HttpResponse:
    presentation = date_time_presentation_for_request(request)
    find = parse_find_filter(request)
    statuschanges, page_obj, elided_page_range = paginate(
        GameStatusChange.objects.select_related("game").all(), find
    )

    data: TableData = {
        "columns": [
            Column("Game"),
            Column("Old Status"),
            Column("New Status"),
            Column("Timestamp"),
        ],
        "rows": [
            make_row(
                sc.game.name,
                sc.get_old_status_display() if sc.old_status else "-",
                sc.get_new_status_display(),
                presentation.format(sc.timestamp, "date") if sc.timestamp else "-",
            )
            for sc in statuschanges
        ],
    }
    content = ContentContainer()[
        paginated_table_content(
            data,
            page_obj=page_obj,
            elided_page_range=elided_page_range,
            request=request,
            page_size=find.per_page,
        )
    ]
    return render_page(request, content, title="Status changes")


def _delete_statuschange_content(statuschange, request: HttpRequest) -> Node:
    return ConfirmPage(
        title="Delete status change",
        message="Are you sure you want to delete this status change?",
        action_url=reverse("games:delete_statuschange", args=[statuschange.id]),
        csrf_token=get_token(request),
        cancel_url=reverse("games:view_game", args=[statuschange.game.id]),
        confirm_label="Delete",
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
