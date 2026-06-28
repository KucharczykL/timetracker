from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.safestring import SafeText

from common.components import (
    CONTENT_MAX_WIDTH_CLASS,
    A,
    AddForm,
    Column,
    CsrfInput,
    Div,
    Form,
    StyledButton,
    TableData,
    make_row,
    paginated_table_content,
)
from common.components.primitives import P
from common.layout import render_page
from common.time import dateformat, local_strftime
from common.utils import paginate
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
    statuschanges, page_obj, elided_page_range = paginate(
        request, GameStatusChange.objects.select_related("game").all()
    )

    data: TableData = {
        "header_action": None,
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
                local_strftime(sc.timestamp, dateformat) if sc.timestamp else "-",
            )
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
    inner = Div()[
        P()["Are you sure you want to delete this status change?"],
        StyledButton(color="red", type="submit", size="lg", class_="w-full")["Delete"],
        A(href=reverse("games:view_game", args=[statuschange.game.id]))[
            StyledButton(color="gray", class_="w-full")["Cancel"]
        ],
    ]
    form = Form(method="post", class_="dark:text-white")[CsrfInput(request), inner]
    return Div(class_=f"w-full {CONTENT_MAX_WIDTH_CLASS} self-center")[form]


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
