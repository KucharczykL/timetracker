from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse

from common.components import (
    AddForm,
    ButtonGroup,
    Column,
    DeviceFilterBar,
    Fragment,
    ICON_BUTTON_SIZE_CLASS,
    Icon,
    ControlButton,
    TableData,
    make_row,
    paginated_table_content,
)
from common.layout import render_page
from common.time import dateformat, local_strftime
from common.utils import paginate
from games.filters import parse_device_filter
from games.forms import DeviceForm
from games.views.filtering import apply_structured_filter
from games.models import Device


@login_required
def list_devices(request: HttpRequest) -> HttpResponse:
    devices = Device.objects.order_by("-created_at")

    filter_json = request.GET.get("filter", "")
    if filter_json:
        device_filter = apply_structured_filter(
            request, parse_device_filter, filter_json
        )
        if device_filter is not None:
            devices = devices.filter(device_filter.to_q())

    devices, page_obj, elided_page_range = paginate(request, devices)

    data: TableData = {
        "header_action": ControlButton(href=reverse("games:add_device"))["Add device"],
        "columns": [
            Column("Name"),
            Column("Type"),
            Column("Created"),
            Column("Actions", align="right"),
        ],
        "rows": [
            make_row(
                device.name,
                device.get_type_display(),
                local_strftime(device.created_at, dateformat),
                ButtonGroup(
                    [
                        {
                            "href": reverse("games:edit_device", args=[device.pk]),
                            "slot": Icon("edit", size=ICON_BUTTON_SIZE_CLASS),
                            "color": "gray",
                        },
                        {
                            "href": reverse("games:delete_device", args=[device.pk]),
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
    )
    filter_bar = DeviceFilterBar(
        filter_json=filter_json,
        preset_list_url=reverse("games:list_presets") + "?mode=devices",
        preset_save_url=reverse("games:save_preset") + "?mode=devices",
    )
    content = Fragment(filter_bar, content)
    return render_page(
        request,
        content,
        title="Manage devices",
    )


@login_required
def edit_device(request: HttpRequest, device_id: int = 0) -> HttpResponse:
    device = get_object_or_404(Device, id=device_id)
    form = DeviceForm(request.POST or None, instance=device)
    if form.is_valid():
        form.save()
        return redirect("games:list_devices")

    return render_page(request, AddForm(form, request=request), title="Edit device")


@login_required
def delete_device(request: HttpRequest, device_id: int) -> HttpResponse:
    device = get_object_or_404(Device, id=device_id)
    device.delete()
    return redirect("games:list_sessions")


@login_required
def add_device(request: HttpRequest) -> HttpResponse:
    form = DeviceForm(request.POST or None)
    if form.is_valid():
        form.save()
        return redirect("games:index")

    return render_page(request, AddForm(form, request=request), title="Add New Device")
