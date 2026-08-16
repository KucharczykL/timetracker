import json
from datetime import timedelta
from typing import Any, cast

from django.apps import apps
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
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
    Div,
    Duration,
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
from common.date_time_presentation import date_time_presentation_for_request
from common.duration_presentation import duration_presentation_for_request
from common.layout import render_page
from games.filters import SessionFilter, filter_url, model_field_registry
from games.models import Device, Game, Platform, Purchase, Session
from games.sorting import parse_per_page_override
from games.views.filtering import BUILDER_MODES
from games.views.stats_content import stats_content
from games.views.stats_data import compute_stats
from timetracker.settings_resolver import resolve_for_user


def model_counts(request: HttpRequest) -> dict[str, Any]:
    user = getattr(request, "user", None)
    library = (
        cast(User, user).library if user is not None and user.is_authenticated else None
    )
    sessions = (
        Session.objects.for_library(library)
        if library is not None
        else Session.objects.none()
    )
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
    today_played = sessions.filter(
        timestamp_start__gte=start_of_today,
        timestamp_start__lt=start_of_tomorrow,
    ).aggregate(time=Sum(F("duration_total")))["time"]
    last_7_played = sessions.filter(
        timestamp_start__gte=start_of_window,
        timestamp_start__lt=start_of_tomorrow,
    ).aggregate(time=Sum(F("duration_total")))["time"]

    durations = duration_presentation_for_request(request)

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
        "game_available": (
            Game.objects.for_library(library).exists() if library is not None else False
        ),
        "platform_available": (
            Platform.objects.visible_to(library).exists()
            if library is not None
            else False
        ),
        "purchase_available": (
            Purchase.objects.for_library(library).exists()
            if library is not None
            else False
        ),
        "session_count": sessions.exists(),
        "today_played": Duration(
            today_played, durations, id_scope="navbar-today", link=today_url
        ),
        "last_7_played": Duration(
            last_7_played, durations, id_scope="navbar-last-7", link=last_7_url
        ),
    }


def global_current_year(request: HttpRequest) -> dict[str, int]:
    return {"global_current_year": localdate().year}


@login_required
def stats_alltime(request: HttpRequest) -> HttpResponse:
    library = cast(User, request.user).library
    data = compute_stats(library, None)
    presentation = date_time_presentation_for_request(request)
    durations = duration_presentation_for_request(request)
    return render_page(
        request, stats_content(data, presentation, durations), title=data["title"]
    )


@login_required
def stats(request: HttpRequest, year: int = 0) -> HttpResponse:
    selected_year = request.GET.get("year")
    if selected_year:
        return HttpResponseRedirect(
            reverse("games:stats_by_year", args=[selected_year])
        )
    if year == 0:
        return HttpResponseRedirect(reverse("games:stats_alltime"))
    library = cast(User, request.user).library
    data = compute_stats(library, year)
    presentation = date_time_presentation_for_request(request)
    durations = duration_presentation_for_request(request)
    return render_page(
        request, stats_content(data, presentation, durations), title=data["title"]
    )


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
    presentation = date_time_presentation_for_request(request)
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
    # Direct builder URLs use the same inherit-or-pin contract.
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

    content = ContentContainer(class_="flex flex-col gap-4")[
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
        # Summary and count sit on one line. They are custom elements with no
        # display rule, so under the old block-flow container they paired up
        # only by inline formatting; the flex column would stack them, hence
        # the explicit row.
        Div(class_="flex flex-wrap items-baseline gap-2")[
            FilterSummary(model=model, model_label=label, models=models_json),
            FilterCount(
                model=model,
                noun_singular=str(meta.verbose_name),
                noun_plural=str(meta.verbose_name_plural),
                endpoint=reverse("api-1.0.0:filter_count"),
            ),
        ],
        FilterGroup(presentation=presentation, model=model, filter=filter_json),
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
