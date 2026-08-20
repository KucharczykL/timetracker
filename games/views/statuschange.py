from typing import cast
from uuid import UUID

from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect

from common.components import (
    AddForm,
    Column,
    ContentContainer,
    ModuleScript,
    TableData,
    TruncatedText,
    make_row,
    paginated_table_content,
)
from common.date_time_presentation import date_time_presentation_for_request
from common.layout import render_page
from common.utils import paginate
from games.forms import GameStatusChangeForm
from games.models import GameStatusChange
from games.ownership import owned_or_404
from games.sorting import parse_find_filter
from games.views.deletion import confirm_and_delete
from games.views.returns import return_url


@login_required
def add_statuschange(request: HttpRequest) -> HttpResponse:
    library = cast(User, request.user).library
    form = GameStatusChangeForm(
        request.POST or None,
        library=library,
        presentation=date_time_presentation_for_request(request),
    )
    if form.is_valid():
        obj = form.save()
        return redirect(
            return_url(request, fallback="games:view_game", fallback_args=[obj.game.id])
        )
    return render_page(
        request,
        AddForm(form, request=request),
        title="Add status change",
        scripts=ModuleScript("dist/elements/date-time-field.js"),
    )


@login_required
def edit_statuschange(request: HttpRequest, statuschange_id: UUID) -> HttpResponse:
    library = cast(User, request.user).library
    statuschange = owned_or_404(
        GameStatusChange.objects.for_library(library), library, id=statuschange_id
    )
    form = GameStatusChangeForm(
        request.POST or None,
        instance=statuschange,
        library=library,
        presentation=date_time_presentation_for_request(request),
    )
    if form.is_valid():
        saved = form.save()
        return redirect(
            return_url(
                request, fallback="games:view_game", fallback_args=[saved.game.id]
            )
        )
    return render_page(
        request,
        AddForm(form, request=request),
        title="Edit status change",
        scripts=ModuleScript("dist/elements/date-time-field.js"),
    )


@login_required
def list_statuschanges(request: HttpRequest) -> HttpResponse:
    library = cast(User, request.user).library
    presentation = date_time_presentation_for_request(request)
    find = parse_find_filter(request)
    statuschanges, page_obj, elided_page_range = paginate(
        GameStatusChange.objects.for_library(library).select_related("game"), find
    )

    data: TableData = {
        "caption": "Status changes",
        "columns": [
            Column("Game", shrinkable=True),
            Column("Old Status"),
            Column("New Status", priority=2),
            Column("Timestamp", priority=3),
        ],
        "rows": [
            make_row(
                TruncatedText(sc.game.name),
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


@login_required
def delete_statuschange(request: HttpRequest, pk: UUID) -> HttpResponse:
    library = cast(User, request.user).library
    statuschange = owned_or_404(
        GameStatusChange.objects.for_library(library), library, id=pk
    )
    return confirm_and_delete(
        request,
        statuschange,
        title="Delete status change",
        message="Permanently delete this status change?",
        fallback="games:view_game",
        fallback_args=[statuschange.game.id],
    )
