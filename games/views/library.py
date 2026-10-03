"""The authenticated Library overview and customization surface."""

from typing import cast

from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.http import HttpRequest, HttpResponse
from django.middleware.csrf import get_token
from django.urls import reverse

from common.components import (
    CopyableFactValue,
    EmptyState,
    FactList,
    Fragment,
    LiveSettingFields,
    PlaytimeSplit,
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
from common.duration_presentation import duration_presentation_for_request
from common.layout import render_page
from common.returns import OriginUrl, UrlName, action_url
from games.end_ways import END_WAY_LABELS
from games.endpoints import DEVICE_ACCESS_END
from games.filters import GameFilter, filter_url
from games.forms import LibraryPreferencesForm
from games.models import (
    Device,
    Game,
    Platform,
)
from games.reads.endpoints import stated, way_of
from games.reads.playtime import total_playtime
from games.reads.purchase_figures import (
    purchase_figures,
    spending_currency,
    valued_in_scope,
)
from games.views import stats_links
from games.views.session_reclassification import (
    TEMPORARY_NOTE,
    PlaytimeReviewPanel,
)
from timetracker.settings_commands import DEFAULT_DEVICE, SettingNamespace


def _actions(
    list_url: str, add_name: UrlName, *, origin: OriginUrl
) -> tuple[SummaryAction, ...]:
    return (
        SummaryAction("Browse", list_url),
        SummaryAction("Add", action_url(add_name, origin=origin)),
    )


DEFAULT_DEVICE_HELP = "Preselected when logging a game."


def default_device_help(stored: Device | None) -> str:
    """The default's help, or why it lapsed."""
    ended = None if stored is None else stated(stored, DEVICE_ACCESS_END)
    if ended is None:
        return DEFAULT_DEVICE_HELP
    way = END_WAY_LABELS[way_of(ended)]
    return f"{way}, so new sessions name no device. Choose another."


@login_required
def library(request: HttpRequest) -> HttpResponse:
    user = cast(User, request.user)
    library = user.library
    origin = request.get_full_path()
    presentation = date_time_presentation_for_request(request)
    durations = duration_presentation_for_request(request)
    playtime = total_playtime(library)
    games = Game.objects.for_library(library)
    spending = purchase_figures(library, None)
    devices = Device.objects.for_library(library)
    platforms = Platform.objects.for_library(library)
    game_count = games.count()
    purchase_count = spending.purchases
    device_count = devices.count()
    platform_count = platforms.count()
    refunded_purchase_count = spending.refunded
    default_device_source = "library"
    default_device_normal_source = "library"
    currency = spending_currency(library, spending)
    total_spent_value = f"{currency} {spending.total_spent:,.2f}"
    #: Both count add-ons.
    every_game = filter_url(GameFilter().of_every_kind())
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
            StatisticCard("Games", game_count, href=every_game),
            #: No link: the session list shows no record, so it sums less.
            StatisticCard(
                "Playtime",
                PlaytimeSplit(playtime, durations, id_scope="library-playtime"),
                title="Tracked sessions and historical records",
            ),
            StatisticCard(
                "Purchases",
                purchase_count,
                href=filter_url(stats_links.purchases_total(None)),
            ),
            StatisticCard("Devices", device_count, href=reverse("games:list_devices")),
        ),
    )
    stored_default = library.preferences.stored_default_device
    default_device_control = LiveSettingFields(
        LibraryPreferencesForm(
            devices=devices.order_by("name"), default_device=stored_default
        ),
        states={
            "default_device": SettingFieldState(
                key=DEFAULT_DEVICE,
                source=default_device_source,
                show_source=default_device_source != default_device_normal_source,
                help_text=default_device_help(stored_default),
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
            value=SummaryValue(game_count, every_game),
            actions=_actions(every_game, "games:add_game", origin=origin),
        ),
        SummaryRow(
            label="Platforms",
            subtitle="Platforms you added manually.",
            value=SummaryValue(platform_count, reverse("games:list_platforms")),
            actions=_actions(
                reverse("games:list_platforms"), "games:add_platform", origin=origin
            ),
        ),
        SummaryRow(
            label="Devices",
            subtitle="Hardware you use to play.",
            value=SummaryValue(device_count, reverse("games:list_devices")),
            actions=_actions(
                reverse("games:list_devices"), "games:add_device", origin=origin
            ),
            detail=default_device_control,
        ),
    )
    purchases_summary = SummaryRow(
        label="Temporary home",
        subtitle="Purchase management will move into the future Catalogue. This section provides a library summary in the meantime.",
        actions=(
            SummaryAction(
                "Add to library", action_url("games:add_to_library", origin=origin)
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
                href=filter_url(valued_in_scope(None)),
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
            "playtime",
            "Playtime",
            PlaytimeReviewPanel(library),
            description=TEMPORARY_NOTE,
        ),
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
        SectionedPageSection(
            "purchases",
            "Purchases",
            purchases_summary,
        ),
    ]
    content = SectionedPage(
        "Library",
        sections,
        description="Your games, play history, purchases, and customizations belong to this library and stay together when it is backed up or restored.",
        navigation_label="Library sections",
    )
    return render_page(request, content, title="Library")


__all__ = ["library"]
