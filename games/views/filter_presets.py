"""Views for managing saved filter presets (FilterPreset model)."""

import json
import logging
from collections.abc import Callable
from typing import cast
from urllib.parse import quote

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from common.components import A, Li, Node, Span, Ul
from common.criteria import FilterError, OperatorFilter
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

# Validates a mode's ``?filter=`` JSON, raising FilterError or returning None.
type FilterParser = Callable[[str], OperatorFilter | None]

# Maps a FilterPreset.mode to the parser that validates that mode's filter JSON.
# Keys must stay in sync with FilterPreset.MODE_CHOICES (games/models.py).
MODE_PARSERS: dict[str, FilterParser] = {
    "games": parse_game_filter,
    "sessions": parse_session_filter,
    "purchases": parse_purchase_filter,
    "playevents": parse_playevent_filter,
    "devices": parse_device_filter,
    "platforms": parse_platform_filter,
}


ITEM_CLASS = (
    "flex justify-between items-center px-4 py-2 text-sm "
    "text-heading hover:bg-neutral-secondary-medium"
)
DELETE_CLASS = "text-red-500 hover:text-red-700 cursor-pointer ml-4"
EMPTY_CLASS = "px-4 py-2 text-sm text-body italic"


@login_required
def list_presets(request: HttpRequest) -> HttpResponse:
    """Return the current user's preset dropdown as an HTML fragment."""
    mode = request.GET.get("mode", "games")
    # `mode` is interpolated into reverse(f"games:list_{mode}") below; an unknown
    # value would raise NoReverseMatch (500). Reject it up front (mirrors
    # save_preset). MODE_PARSERS keys == FilterPreset.MODE_CHOICES (parity-tested).
    if mode not in MODE_PARSERS:
        return HttpResponse(status=400)

    # @login_required guarantees an authenticated User (never AnonymousUser).
    user = cast(User, request.user)
    presets = FilterPreset.objects.filter(mode=mode, user=user).order_by("name")

    # Built with the component node layer (not f-strings) so user-controlled
    # preset.name is auto-escaped — the string child and every attribute value
    # pass through escape() (fixes the stored-XSS in the old raw-HTML build).
    items: list[Node] = []
    for preset in presets:
        filter_json = json.dumps(preset.object_filter) if preset.object_filter else ""
        list_url = reverse(f"games:list_{mode}")
        delete_url = reverse("games:delete_preset", args=[preset.id])
        items.append(
            Li(data_preset_name=preset.name)[
                A(href=f"{list_url}?filter={quote(filter_json)}", class_=ITEM_CLASS)[
                    Span()[preset.name],
                    Span(
                        class_=DELETE_CLASS,
                        data_delete_preset=str(preset.id),
                        href=delete_url,
                    )["x"],
                ]
            ]
        )

    if not items:
        items = [Li(class_=EMPTY_CLASS)["No saved presets"]]

    return HttpResponse(Ul(class_="py-1")[items])


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
        if parsed is not None:
            # A non-None parse means the payload was a filter object; re-loading
            # it cannot raise (parse() already loaded + validated the JSON).
            object_filter = json.loads(filter_json_str)
        else:
            # parse() returns None for any non-object JSON. `null` legitimately
            # means "no filter" -> {}. A scalar/array is a malformed payload, not
            # an empty filter: reject it like bad JSON rather than silently saving
            # a match-everything preset behind a success toast (issue #206).
            if json.loads(filter_json_str) is not None:
                logger.warning(
                    "rejected preset save (mode=%s, user=%s, path=%s): "
                    "filter is not an object",
                    mode,
                    request.user,
                    request.path,
                )
                messages.error(request, "Invalid filter: expected a filter object.")
                return HttpResponse(status=400)

    # Upsert on the (user, mode, name) identity: re-saving a name overwrites the
    # stored filter rather than creating a duplicate row. The unique constraint
    # (FilterPreset.Meta) enforces that identity at the DB level; the filter bar
    # warns inline before the user confirms an overwrite (issue #212).
    _, created = FilterPreset.objects.update_or_create(
        user=cast(User, request.user),
        name=name,
        mode=mode,
        defaults={"object_filter": object_filter},
    )
    verb = "saved" if created else "updated"
    messages.success(request, f'Filter preset "{name}" {verb}.')
    return HttpResponse(status=201 if created else 200)


@login_required
@require_http_methods(["DELETE"])
def delete_preset(request: HttpRequest, preset_id: int) -> HttpResponse:
    """Delete one of the current user's filter presets.

    DELETE-only: a destructive action must not be reachable by GET, or a
    cross-site `<img src=.../>` would delete the victim's preset (CSRF only
    guards unsafe methods). Scoped to request.user so it cannot touch another
    user's preset (404 instead).
    """
    preset = get_object_or_404(FilterPreset, id=preset_id, user=request.user)
    name = preset.name
    preset.delete()
    messages.success(request, f'Preset "{name}" deleted.')
    return HttpResponse(status=200)


@login_required
def load_preset(request: HttpRequest, preset_id: int) -> HttpResponse:
    """Load one of the current user's presets and redirect to its list view."""
    preset = get_object_or_404(FilterPreset, id=preset_id, user=request.user)
    filter_json = json.dumps(preset.object_filter) if preset.object_filter else ""
    return redirect(
        f"{reverse(f'games:list_{preset.mode}')}?filter={quote(filter_json)}"
    )
