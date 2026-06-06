"""Views for managing saved filter presets (FilterPreset model)."""

import json
from urllib.parse import quote

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.safestring import mark_safe

from games.models import FilterPreset


@login_required
def list_presets(request: HttpRequest) -> HttpResponse:
    """Return a preset dropdown as an HTML fragment."""
    mode = request.GET.get("mode", "games")
    presets = FilterPreset.objects.filter(mode=mode).order_by("name")

    items: list[str] = []
    for preset in presets:
        filter_json = json.dumps(preset.object_filter) if preset.object_filter else ""
        list_url = reverse(f"games:list_{mode}")
        delete_url = reverse("games:delete_preset", args=[preset.id])

        items.append(
            f"<li>"
            f'<a href="{list_url}?filter={quote(filter_json)}" '
            f'class="flex justify-between items-center px-4 py-2 text-sm '
            f'text-heading hover:bg-neutral-secondary-medium">'
            f"<span>{preset.name}</span>"
            f'<span class="text-red-500 hover:text-red-700 cursor-pointer ml-4" '
            f'data-delete-preset="{preset.id}" '
            f'href="{delete_url}">x</span>'
            f"</a></li>"
        )

    if not items:
        items = ['<li class="px-4 py-2 text-sm text-body italic">No saved presets</li>']

    return HttpResponse(mark_safe(f'<ul class="py-1">{"".join(items)}</ul>'))


@login_required
def save_preset(request: HttpRequest) -> HttpResponse:
    """Save the current filter as a new preset."""
    if request.method != "POST":
        return HttpResponse(status=405)

    name = request.POST.get("name", "").strip()
    mode = request.POST.get("mode", "games")
    filter_json_str = request.POST.get("filter", "")

    if not name:
        messages.error(request, "Preset name is required.")
        return HttpResponse(status=400)

    object_filter: dict = {}
    if filter_json_str:
        try:
            object_filter = json.loads(filter_json_str)
        except json.JSONDecodeError:
            pass

    FilterPreset.objects.create(
        name=name,
        mode=mode,
        object_filter=object_filter,
    )
    messages.success(request, f'Filter preset "{name}" saved.')
    return HttpResponse(status=201)


@login_required
def delete_preset(request: HttpRequest, preset_id: int) -> HttpResponse:
    """Delete a saved filter preset."""
    preset = get_object_or_404(FilterPreset, id=preset_id)
    name = preset.name
    preset.delete()
    messages.success(request, f'Preset "{name}" deleted.')
    return HttpResponse(status=200)


@login_required
def load_preset(request: HttpRequest, preset_id: int) -> HttpResponse:
    """Load a preset and redirect to the appropriate list view."""
    preset = get_object_or_404(FilterPreset, id=preset_id)
    filter_json = json.dumps(preset.object_filter) if preset.object_filter else ""
    return redirect(
        f"{reverse(f'games:list_{preset.mode}')}?filter={quote(filter_json)}"
    )
