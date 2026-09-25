from functools import partial
from typing import cast
from uuid import UUID

from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.http import HttpRequest, HttpResponse
from django.middleware.csrf import get_token
from django.shortcuts import redirect
from django.urls import reverse
from django.views.decorators.http import require_POST

from common.components import (
    AddForm,
    Column,
    ContentContainer,
    Li,
    QuickFilterBar,
    TableData,
    TruncatedText,
    Ul,
    drop_columns,
    make_row,
    paginated_table_content,
    parse_filter_dict,
)
from common.date_time_presentation import date_time_presentation_for_request
from common.filter_execution import execute_filter, regex_timeout_view
from common.layout import render_page
from common.utils import paginate
from games.bulk_removal import REMOVE_DEVICE
from games.bulk_tray import tray_actions
from games.filters import (
    DeviceFilter,
    filter_query_context_for_library,
    parse_device_filter,
)
from games.forms import DeviceForm
from games.list_columns import column_choice
from games.models import Device
from games.ownership import owned_or_404
from games.reads.device_departures import sessions_naming
from games.sorting import (
    DEVICE_DEFAULT_SORT,
    DEVICE_SORTS,
    apply_sort,
    parse_find_filter,
)
from games.views.device_menu import device_row_menu
from games.views.filtering import (
    apply_structured_filter,
    builder_url_for,
    warn_unknown_sort,
)
from games.views.removal import confirm_and_remove, restore_and_return
from games.views.returns import return_url
from games.writes.answers import CommandFailed
from games.writes.device import create_device, describe_device
from games.writes.device import remove_device as remove_device_row
from games.writes.device import restore_device as restore_device_row
from games.writes.playergame import new_correlation_id

DEVICE_COLUMNS: list[Column] = [
    Column("Name", "name", key="name", hideable=False),
    Column("Type", "type", priority=2, key="type"),
    Column("Created", "created", key="created", hidden_by_default=True),
]


@login_required
@regex_timeout_view
def list_devices(request: HttpRequest) -> HttpResponse:
    library = cast(User, request.user).library
    presentation = date_time_presentation_for_request(request)
    origin = request.get_full_path()
    devices = Device.objects.for_library(library)

    filter_json = request.GET.get("filter", "")
    if filter_json:
        device_filter = apply_structured_filter(
            request, parse_device_filter, filter_json
        )
        if device_filter is not None:
            devices = execute_filter(
                device_filter,
                devices,
                filter_query_context_for_library(library),
            )

    find = parse_find_filter(request)
    sort = apply_sort(devices, find, DEVICE_SORTS, DEVICE_DEFAULT_SORT)
    devices = sort.queryset
    warn_unknown_sort(request, sort.unknown, entity="device")
    devices, page_obj, elided_page_range = paginate(devices, find)
    #: One read serves cells and rows.
    page_devices = list(devices)

    hidden, picker = column_choice(request, "devices", DEVICE_COLUMNS)
    kept_columns, kept_cells = drop_columns(
        DEVICE_COLUMNS,
        [
            [
                TruncatedText(device.name),
                device.get_type_display(),
                presentation.format(device.created_at, "date"),
            ]
            for device in page_devices
        ],
        hidden,
    )
    data: TableData = {
        "caption": "Devices",
        "columns": kept_columns,
        #: Every row carries its menu.
        "menu_slot": True,
        "sort_terms": sort.terms,
        "rows": [
            make_row(*cells, key=str(device.pk), menu=device_row_menu(device, origin))
            for device, cells in zip(page_devices, kept_cells, strict=True)
        ],
        "column_picker": picker,
        "selection": {
            "filter": filter_json,
            "csrf_token": get_token(request),
            "actions": tray_actions(REMOVE_DEVICE.name, origin=origin),
        },
    }
    content = paginated_table_content(
        data,
        page_obj=page_obj,
        elided_page_range=elided_page_range,
        request=request,
        page_size=find.per_page,
    )
    builder_url = builder_url_for(
        "devices", filter_json, find.sort, find.per_page_override
    )
    parsed_filter = parse_filter_dict(filter_json, DeviceFilter)
    quick_bar = QuickFilterBar(
        presentation=presentation,
        mode="devices",
        existing=parsed_filter,
        preset_api_url=reverse("api-1.0.0:list_presets"),
        builder_url=builder_url,
        per_page_override=find.per_page_override,
    )
    content = ContentContainer()[quick_bar, content]
    return render_page(
        request,
        content,
        title="Manage devices",
    )


def _render_form(
    request: HttpRequest, form: DeviceForm, title: str, *, status: int = 200
) -> HttpResponse:
    response = render_page(request, AddForm(form, request=request), title=title)
    response.status_code = status
    return response


@login_required
def edit_device(request: HttpRequest, device_id: UUID) -> HttpResponse:
    user = cast(User, request.user)
    library = user.library
    device = owned_or_404(Device.objects.for_library(library), library, id=device_id)
    form = DeviceForm(request.POST or None, library=library, device=device)
    title = "Edit device"
    if form.is_valid():
        try:
            describe_device(
                user,
                device,
                name=form.cleaned_data["name"],
                device_type=form.cleaned_data["type"],
                correlation_id=new_correlation_id(),
            )
        except CommandFailed as failure:
            form.add_error(None, failure.message)
            return _render_form(request, form, title, status=failure.status_code)
        return redirect(return_url(request, fallback="games:list_devices"))

    return _render_form(request, form, title)


@login_required
@require_POST
def restore_device(request: HttpRequest, device_id: UUID) -> HttpResponse:
    """Undo; the plain manager, since the row is removed."""
    user = cast(User, request.user)
    library = user.library
    device = owned_or_404(Device.objects.filter(library=library), library, id=device_id)
    return restore_and_return(
        request,
        action=partial(
            restore_device_row, user, device, correlation_id=new_correlation_id()
        ),
        restored=f"{device.name} restored to your library.",
        fallback="games:list_devices",
    )


@login_required
def remove_device(request: HttpRequest, device_id: UUID) -> HttpResponse:
    user = cast(User, request.user)
    library = user.library
    device = owned_or_404(Device.objects.for_library(library), library, id=device_id)
    return confirm_and_remove(
        request,
        device,
        title="Remove device",
        message=f"Remove {device.name} from your library?",
        details=Ul()[
            Li()[f"{sessions_naming(library, device).count()} session(s) still name it"]
        ],
        action=partial(
            remove_device_row, user, device, correlation_id=new_correlation_id()
        ),
        fallback="games:list_devices",
        removed=f"{device.name} removed from your library.",
        undo="games:restore_device",
    )


@login_required
def add_device(request: HttpRequest) -> HttpResponse:
    user = cast(User, request.user)
    form = DeviceForm(request.POST or None, library=user.library)
    title = "Add New Device"
    if form.is_valid():
        try:
            create_device(
                user,
                name=form.cleaned_data["name"],
                device_type=form.cleaned_data["type"],
                idempotency_key=form.submission_key(),
                correlation_id=new_correlation_id(),
            )
        except CommandFailed as failure:
            form.add_error(None, failure.message)
            return _render_form(request, form, title, status=failure.status_code)
        return redirect(return_url(request, fallback="games:list_devices"))

    return _render_form(request, form, title)
