"""Views for managing saved filter presets (FilterPreset model)."""

import json
import logging
from urllib.parse import quote

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse

from common.criteria import FilterError
from games.filters import (
    parse_device_filter,
    parse_game_filter,
    parse_platform_filter,
    parse_playevent_filter,
    parse_purchase_filter,
    parse_session_filter,
)
from games.models import FilterPreset

logger = logging.getLogger("games")

# Maps a FilterPreset.mode to the parser that validates that mode's filter JSON.
# Keys must stay in sync with FilterPreset.MODE_CHOICES (games/models.py).
MODE_PARSERS = {
    "games": parse_game_filter,
    "sessions": parse_session_filter,
    "purchases": parse_purchase_filter,
    "playevents": parse_playevent_filter,
    "devices": parse_device_filter,
    "platforms": parse_platform_filter,
}


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

    return HttpResponse(f'<ul class="py-1">{"".join(items)}</ul>')


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

    parse = MODE_PARSERS.get(mode)
    if parse is None:
        logger.warning(
            "rejected preset save (user=%s, path=%s): unknown mode %r",
            request.user,
            request.path,
            mode,
        )
        messages.error(request, f"Unknown preset mode '{mode}'.")
        return HttpResponse(status=400)

    object_filter: dict = {}
    if filter_json_str:
        try:
            parsed = parse(filter_json_str)  # raises FilterError on bad JSON/semantics
        except FilterError as exc:
            logger.warning(
                "rejected preset save (mode=%s, user=%s, path=%s): %s",
                mode,
                request.user,
                request.path,
                exc,
            )
            messages.error(request, f"Invalid filter: {exc}")
            return HttpResponse(status=400)
        # parse() returns None for empty/null/non-object JSON; store {} then so a
        # scalar/null is never persisted into the dict-typed field. After a
        # successful parse(), json.loads cannot raise (parse() already loaded it).
        object_filter = json.loads(filter_json_str) if parsed is not None else {}

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
