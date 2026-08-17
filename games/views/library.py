"""The authenticated Library overview and customization surface."""

from typing import cast

from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db.models import F, Sum
from django.http import HttpRequest, HttpResponse
from django.middleware.csrf import get_token
from django.urls import reverse

from common.components import (
    CopyableFactValue,
    EmptyState,
    FactList,
    Fragment,
    LiveSettingFields,
    SectionedPage,
    SectionedPageSection,
    SettingFieldState,
    StatisticCard,
    StatisticGrid,
    SummaryAction,
    SummaryList,
    SummaryRow,
    SummaryValue,
)
from common.date_time_presentation import date_time_presentation_for_request
from common.layout import render_page
from common.returns import OriginUrl, UrlName, action_url
from games.filters import PurchaseFilter, filter_url
from games.forms import LibraryPreferencesForm
from games.models import (
    Device,
    Game,
    Platform,
    Purchase,
    PurchaseConversionState,
    Session,
)
from games.views import stats_links
from timetracker.settings_commands import SettingNamespace


def _actions(
    list_name: UrlName, add_name: UrlName, *, origin: OriginUrl
) -> tuple[SummaryAction, ...]:
    return (
        SummaryAction("Browse", reverse(list_name)),
        SummaryAction("Add", action_url(add_name, origin=origin)),
    )


@login_required
def library(request: HttpRequest) -> HttpResponse:
    user = cast(User, request.user)
    library = user.library
    origin = request.get_full_path()
    presentation = date_time_presentation_for_request(request)
    games = Game.objects.for_library(library)
    sessions = Session.objects.for_library(library)
    purchases = Purchase.objects.for_library(library)
    devices = Device.objects.for_library(library)
    platforms = Platform.objects.for_library(library)
    not_refunded = purchases.not_refunded()
    conversion = PurchaseConversionState.objects.get(library=library)
    game_count = games.count()
    session_count = sessions.count()
    purchase_count = purchases.count()
    device_count = devices.count()
    platform_count = platforms.count()
    refunded_purchase_count = purchases.refunded().count()
    default_device_source = "library"
    default_device_normal_source = "library"
    total_spent = not_refunded.aggregate(total=Sum(F("converted_price")))["total"] or 0
    currency = conversion.published_currency
    total_spent_value = f"{currency} {total_spent:,.2f}"
    overview = Fragment(
        FactList(
            [
                (
                    "Library ID",
                    CopyableFactValue(str(library.pk), description="Copy Library ID"),
                ),
                ("Created", presentation.format(library.created_at, "date")),
            ]
        ),
        StatisticGrid(
            StatisticCard("Games", game_count, href=reverse("games:list_games")),
            StatisticCard(
                "Sessions", session_count, href=reverse("games:list_sessions")
            ),
            StatisticCard(
                "Purchases",
                purchase_count,
                href=filter_url(stats_links.purchases_total(None)),
            ),
            StatisticCard("Devices", device_count, href=reverse("games:list_devices")),
        ),
    )
    default_device_control = LiveSettingFields(
        LibraryPreferencesForm(
            devices=devices.order_by("name"),
            default_device=library.preferences.default_device,
        ),
        states={
            "default_device": SettingFieldState(
                key="default-device",
                source=default_device_source,
                show_source=default_device_source != default_device_normal_source,
                help_text="Preselected when logging a game.",
            )
        },
        patch_url_template="/api/library/__key__",
        csrf=get_token(request),
        namespace=SettingNamespace.LIBRARY,
    )
    customization = SummaryList(
        SummaryRow(
            label="Games",
            subtitle="Games currently tracked in this library.",
            value=SummaryValue(game_count, reverse("games:list_games")),
            actions=_actions("games:list_games", "games:add_game", origin=origin),
        ),
        SummaryRow(
            label="Platforms",
            subtitle="Platforms you added manually.",
            value=SummaryValue(platform_count, reverse("games:list_platforms")),
            actions=_actions(
                "games:list_platforms", "games:add_platform", origin=origin
            ),
        ),
        SummaryRow(
            label="Devices",
            subtitle="Hardware you use to play.",
            value=SummaryValue(device_count, reverse("games:list_devices")),
            actions=_actions("games:list_devices", "games:add_device", origin=origin),
            detail=default_device_control,
        ),
    )
    purchases_summary = SummaryRow(
        label="Temporary home",
        subtitle="Purchase management will move into the future Catalogue. This section provides a library summary in the meantime.",
        actions=(
            SummaryAction(
                "Add purchase", action_url("games:add_purchase", origin=origin)
            ),
        ),
        detail=StatisticGrid(
            StatisticCard(
                "Purchases",
                purchase_count,
                href=filter_url(stats_links.purchases_total(None)),
            ),
            StatisticCard(
                "Total spent",
                total_spent_value,
                href=filter_url(PurchaseFilter.where(is_refunded=False)),
            ),
            StatisticCard(
                "Refunded purchases",
                refunded_purchase_count,
                href=filter_url(stats_links.purchases_refunded(None)),
            ),
        ),
    )
    sections = [
        SectionedPageSection("overview", "Overview", overview),
        SectionedPageSection(
            "activity",
            "Activity",
            EmptyState(
                title="Activity is coming later",
                description="This section will be added as part of the Player's Journal.",
            ),
        ),
        SectionedPageSection(
            "customization",
            "Customization",
            customization,
            description="Games currently includes every game in your library. After IGDB integration, this area will contain only games and platforms you customized or created. Devices will remain here.",
        ),
        SectionedPageSection("purchases", "Purchases", purchases_summary),
    ]
    content = SectionedPage(
        "Library",
        sections,
        description="Your games, play history, purchases, and customizations belong to this library and stay together when it is backed up or restored.",
        navigation_label="Library sections",
    )
    return render_page(request, content, title="Library")


__all__ = ["library"]
