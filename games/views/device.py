from typing import cast
from uuid import UUID

from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.urls import reverse

from common.components import (
    ICON_BUTTON_SIZE_CLASS,
    AddForm,
    ButtonGroup,
    Column,
    ContentContainer,
    Icon,
    Li,
    QuickFilterBar,
    TableData,
    TruncatedText,
    Ul,
    make_row,
    paginated_table_content,
    parse_filter_dict,
)
from common.date_time_presentation import date_time_presentation_for_request
from common.filter_execution import execute_filter, regex_timeout_view
from common.layout import render_page
from common.returns import action_url
from common.utils import paginate
from games.filters import filter_query_context_for_library, parse_device_filter
from games.forms import DeviceForm
from games.models import Device
from games.ownership import owned_or_404
from games.sorting import (
    DEVICE_DEFAULT_SORT,
    DEVICE_SORTS,
    apply_sort,
    parse_find_filter,
)
from games.views.filtering import (
    apply_structured_filter,
    builder_url_for,
    warn_unknown_sort,
)
from games.views.retirement import confirm_and_retire
from games.views.returns import return_url


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

    data: TableData = {
        "caption": "Devices",
        "columns": [
            Column("Name", "name"),
            Column("Type", "type", priority=2),
            Column("Created", "created"),
            Column("Actions", align="right", priority=3),
        ],
        "sort_terms": sort.terms,
        "rows": [
            make_row(
                TruncatedText(device.name),
                device.get_type_display(),
                presentation.format(device.created_at, "date"),
                ButtonGroup(
                    [
                        {
                            "href": action_url(
                                "games:edit_device", device.pk, origin=origin
                            ),
                            "slot": Icon("edit", size=ICON_BUTTON_SIZE_CLASS),
                            "color": "gray",
                        },
                        {
                            "href": action_url(
                                "games:delete_device", device.pk, origin=origin
                            ),
                            "slot": Icon("delete", size=ICON_BUTTON_SIZE_CLASS),
                            "color": "red",
                        },
                    ]
                ),
            )
            for device in devices
        ],
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
    parsed_filter = parse_filter_dict(filter_json)
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


@login_required
def edit_device(request: HttpRequest, device_id: UUID) -> HttpResponse:
    library = cast(User, request.user).library
    device = owned_or_404(Device.objects.for_library(library), library, id=device_id)
    form = DeviceForm(request.POST or None, instance=device, library=library)
    if form.is_valid():
        form.save()
        return redirect(return_url(request, fallback="games:list_devices"))

    return render_page(request, AddForm(form, request=request), title="Edit device")


@login_required
def delete_device(request: HttpRequest, device_id: UUID) -> HttpResponse:
    library = cast(User, request.user).library
    device = owned_or_404(Device.objects.for_library(library), library, id=device_id)
    return confirm_and_retire(
        request,
        device,
        title="Delete device",
        noun="device",
        label=device.name,
        message=f"Permanently delete {device.name}?",
        details=Ul()[
            Li()[f"{device.session_set.count()} session(s) lose their device"]
        ],
        fallback="games:list_devices",
    )


@login_required
def add_device(request: HttpRequest) -> HttpResponse:
    library = cast(User, request.user).library
    form = DeviceForm(request.POST or None, library=library)
    if form.is_valid():
        form.save()
        return redirect(return_url(request, fallback="games:list_devices"))

    return render_page(request, AddForm(form, request=request), title="Add New Device")
