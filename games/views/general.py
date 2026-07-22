import json
from datetime import datetime, timedelta
from typing import Any, Callable

from django.apps import apps
from django.contrib.auth.decorators import login_required
from django.db.models import (
    F,
    Sum,
)
from django.http import Http404, HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.timezone import localdate, localtime
from django.utils.timezone import now as timezone_now

from common.components import (
    CsrfInput,
    FilterBuilder,
    FilterCount,
    FilterGroup,
    FilterSummary,
)
from common.components.custom_elements import (
    FILTER_MODE_MODELS,
    ButtonDropdown,
    DropdownLinkItem,
)
from common.components.primitives import ContentContainer, PageHeading, Span
from common.layout import render_page
from common.time import format_duration
from games.filters import SessionFilter, filter_url, model_field_registry
from games.models import Device, Game, Platform, Purchase, Session
from games.sorting import parse_per_page_override
from games.views.filtering import BUILDER_MODES
from games.views.stats_content import stats_content
from games.views.stats_data import compute_stats
from timetracker.settings_resolver import resolve_for_user

# The Flowbite-datepicker UMD bundle is declared as media on the YearPicker
# component, so TimetrackerDocument() loads it automatically on the stats pages.


def model_counts(request: HttpRequest) -> dict[str, Any]:
    now = timezone_now()
    # Use a contiguous [midnight, next midnight) range in the active timezone
    # instead of day/month/year extracts: a range filter can use an index on
    # timestamp_start, whereas the extracts force a per-row datetime function.
    today = localtime(now).date()
    start_of_today = localtime(now).replace(hour=0, minute=0, second=0, microsecond=0)
    start_of_tomorrow = start_of_today + timedelta(days=1)
    # "Last 7 days" is a calendar-day window (today plus the previous six) so the
    # displayed total matches the list its navbar link points to.
    start_of_window = start_of_today - timedelta(days=6)
    today_played = Session.objects.filter(
        timestamp_start__gte=start_of_today,
        timestamp_start__lt=start_of_tomorrow,
    ).aggregate(time=Sum(F("duration_total")))["time"]
    last_7_played = Session.objects.filter(
        timestamp_start__gte=start_of_window,
        timestamp_start__lt=start_of_tomorrow,
    ).aggregate(time=Sum(F("duration_total")))["time"]

    today_iso = today.isoformat()
    today_url = filter_url(SessionFilter.where(timestamp_start=today_iso))
    last_7_url = filter_url(
        SessionFilter.where(
            timestamp_start__between=(
                (today - timedelta(days=6)).isoformat(),
                today_iso,
            )
        )
    )

    return {
        "game_available": Game.objects.exists(),
        "platform_available": Platform.objects.exists(),
        "purchase_available": Purchase.objects.exists(),
        "session_count": Session.objects.exists(),
        "today_played": format_duration(today_played, "%H h %m m"),
        "last_7_played": format_duration(last_7_played, "%H h %m m"),
        "today_url": today_url,
        "last_7_url": last_7_url,
    }


def global_current_year(request: HttpRequest) -> dict[str, int]:
    return {"global_current_year": datetime.now().year}


def use_custom_redirect(
    func: Callable[..., HttpResponse],
) -> Callable[..., HttpResponse]:
    """
    Will redirect to "return_path" session variable if set.
    """

    def wrapper(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        response = func(request, *args, **kwargs)
        if isinstance(response, HttpResponseRedirect) and (
            next_url := request.session.get("return_path")
        ):
            return HttpResponseRedirect(next_url)
        return response

    return wrapper


@login_required
def stats_alltime(request: HttpRequest) -> HttpResponse:
    request.session["return_path"] = request.path
    data = compute_stats(None)
    return render_page(request, stats_content(data), title=data["title"])


@login_required
def stats(request: HttpRequest, year: int = 0) -> HttpResponse:
    selected_year = request.GET.get("year")
    if selected_year:
        return HttpResponseRedirect(
            reverse("games:stats_by_year", args=[selected_year])
        )
    if year == 0:
        return HttpResponseRedirect(reverse("games:stats_alltime"))
    request.session["return_path"] = request.path
    data = compute_stats(year)
    return render_page(request, stats_content(data), title=data["title"])


# The lists backed by an OperatorFilter + nested builder. Keys are model keys
# (Model._meta.model_name); `mode` is the plural preset/list mode. Derived from
# the canonical FILTER_MODE_MODELS so the pairs cannot drift; which modes have
# a builder at all is BUILDER_MODES' single say (games/views/filtering.py).
_BUILDER_MODELS: dict[str, str] = {
    FILTER_MODE_MODELS[mode]: mode for mode in BUILDER_MODES
}


@login_required
def filter_builder(request: HttpRequest, model: str) -> HttpResponse:
    """Advanced nested-filter builder page for one model (#196).

    Mounts the toolbar + NL summary + live count + root <filter-group>, seeded
    from ?filter=. Apply navigates back to the model's list with ?filter=.
    """
    mode = _BUILDER_MODELS.get(model)
    if mode is None:
        raise Http404(f"No filter builder for model {model!r}")

    # filter_for_model returns the OperatorFilter *class* (no `.model` attr); resolve
    # the Django model the same way filter_for_model / model_field_registry do.
    django_model = apps.get_model("games", model)
    meta = django_model._meta
    label = str(meta.verbose_name_plural).title()
    filter_json = request.GET.get("filter", "")
    # The list's active ?sort= is threaded in so a preset saved here captures it
    # and Apply navigates back preserving it (#77). Empty when no sort is active.
    sort = request.GET.get("sort", "")
    # Normalize direct builder URLs too: "" means inherit the current user
    # default; a valid non-negative integer is an explicit preset pin (#386).
    per_page_override = parse_per_page_override(request.GET.get("per_page"))
    per_page = "" if per_page_override is None else str(per_page_override)
    models_json = json.dumps(model_field_registry(model))

    def _item(model):
        model_name = model._meta.verbose_name
        model_label = model_name.title()
        return DropdownLinkItem(
            url=reverse("games:filter_builder", args=[model_name]),
            label=model_label,
        )

    items = [_item(m) for m in [Device, Game, Platform, Purchase, Session]]

    model_switcher = ButtonDropdown(
        id="model-switcher", items=items, label=meta.verbose_name.title()
    )

    content = ContentContainer()[
        PageHeading(
            [
                Span(class_="flex align-center gap-2")[
                    "Advanced filter builder for", model_switcher
                ]
            ]
        ),
        # The preset save/delete fetches send X-CSRFToken (filter-builder.ts reads the
        # csrftoken cookie, falling back to this hidden input). render_page/Page() do
        # NOT emit a CSRF token, so a standalone builder page would otherwise have
        # NEITHER the cookie set NOR a token input → 403 on save/delete. CsrfInput
        # calls get_token(request), which both sets the cookie and renders the input.
        CsrfInput(request),
        FilterBuilder(
            model=model,
            mode=mode,
            preset_api_url=reverse("api-1.0.0:list_presets"),
            sort=sort,
            per_page=per_page,
        ),
        FilterSummary(model=model, model_label=label, models=models_json),
        FilterCount(
            model=model,
            noun_singular=str(meta.verbose_name),
            noun_plural=str(meta.verbose_name_plural),
            endpoint=reverse("api-1.0.0:filter_count"),
        ),
        FilterGroup(model=model, filter=filter_json),
    ]
    return render_page(request, content, title=f"Filter {label}")


@login_required
def index(request: HttpRequest) -> HttpResponse:
    landing_page = resolve_for_user(request.user, "DEFAULT_LANDING_PAGE")
    if landing_page == "games:stats_by_year":
        return redirect(landing_page, year=localdate().year)
    if isinstance(landing_page, str):
        return redirect(landing_page)
    return redirect("games:list_sessions")
