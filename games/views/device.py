from typing import Any

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse

from common.time import dateformat, local_strftime
from common.utils import A, Button
from games.forms import DeviceForm
from games.models import Device


@login_required
def list_devices(request: HttpRequest) -> HttpResponse:
    context: dict[Any, Any] = {}
    page_number = request.GET.get("page", 1)
    limit = request.GET.get("limit", 10)
    devices = Device.objects.order_by("-created_at")
    page_obj = None
    if int(limit) != 0:
        paginator = Paginator(devices, limit)
        page_obj = paginator.get_page(page_number)
        devices = page_obj.object_list

    context = {
        "title": "Manage devices",
        "page_obj": page_obj or None,
        "elided_page_range": (
            page_obj.paginator.get_elided_page_range(
                page_number, on_each_side=1, on_ends=1
            )
            if page_obj
            else None
        ),
        "data": {
            "header_action": A([], Button([], "Add device"), url="add_device"),
            "columns": [
                "Name",
                "Type",
                "Created",
                "Actions",
            ],
            "rows": [
                [
                    device.name,
                    device.get_type_display(),
                    local_strftime(device.created_at, dateformat),
                    render_to_string(
                        "cotton/button_group_sm.html",
                        {
                            "buttons": [
                                {
                                    "href": reverse("edit_device", args=[device.pk]),
                                    "text": "Edit",
                                    "color": "gray",
                                },
                                {
                                    "href": reverse("delete_device", args=[device.pk]),
                                    "text": "Delete",
                                    "color": "red",
                                },
                            ]
                        },
                    ),
                ]
                for device in devices
            ],
        },
    }
    return render(request, "list_purchases.html", context)


@login_required
def edit_device(request: HttpRequest, device_id: int = 0) -> HttpResponse:
    device = get_object_or_404(Device, id=device_id)
    form = DeviceForm(request.POST or None, instance=device)
    if form.is_valid():
        form.save()
        return redirect("list_devices")

    context: dict[str, Any] = {"form": form, "title": "Edit device"}
    return render(request, "add.html", context)


@login_required
def delete_device(request: HttpRequest, device_id: int) -> HttpResponse:
    device = get_object_or_404(Device, id=device_id)
    device.delete()
    return redirect("list_sessions")


@login_required
def add_device(request: HttpRequest) -> HttpResponse:
    context: dict[str, Any] = {}
    form = DeviceForm(request.POST or None)
    if form.is_valid():
        form.save()
        return redirect("index")

    context["form"] = form
    context["title"] = "Add New Device"
    return render(request, "add.html", context)
