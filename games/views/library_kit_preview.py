"""Authenticated, DEBUG-only Library component-kit showcase."""

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.middleware.csrf import get_token
from django.urls import reverse
from django.utils.timezone import localdate

from common.components import (
    AccountMenu,
    ControlButton,
    CopyControl,
    Div,
    EntitySummaryAction,
    EntitySummaryList,
    EntitySummaryRow,
    FactList,
    Link,
    SectionedPageHeader,
    SectionedPageScaffold,
    SectionedPageSection,
    Span,
    StatisticCard,
    StatisticGrid,
    custom_element_builder,
)
from common.layout import render_page

_LibraryKitPreview = custom_element_builder("library-kit-preview")


@login_required
def library_kit_preview(request: HttpRequest) -> HttpResponse:
    """Compose the Library UI kit from static fixtures only."""

    library_id = "018f0000-0000-7000-8000-000000000000"
    statistics_and_facts = Div(class_="@container flex flex-col gap-6")[
        StatisticGrid(
            StatisticCard("Games", 851),
            StatisticCard("Total spent", "CZK 12,345.67"),
            StatisticCard("Devices", 0),
        ),
        FactList(
            [
                (
                    "Library ID",
                    Div(class_="flex min-w-0 items-center gap-1")[
                        Span(class_="min-w-0 break-all font-mono")[library_id],
                        CopyControl(library_id, description="Copy Library ID"),
                    ],
                ),
                ("Created", "31/12/2022"),
            ]
        ),
    ]
    games_actions = (
        EntitySummaryAction("Browse", reverse("games:list_games")),
        EntitySummaryAction("Add", reverse("games:add_game")),
    )
    platform_actions = (
        EntitySummaryAction("Browse", reverse("games:list_platforms")),
        EntitySummaryAction("Add", reverse("games:add_platform")),
    )
    device_actions = (
        EntitySummaryAction("Browse", reverse("games:list_devices")),
        EntitySummaryAction("Add", reverse("games:add_device")),
    )
    entity_summaries = EntitySummaryList(
        EntitySummaryRow(
            label="Games",
            subtitle="Games currently tracked in this library.",
            count=851,
            count_href=reverse("games:list_games"),
            actions=games_actions,
        ),
        EntitySummaryRow(
            label="Platforms",
            subtitle="Platforms you added manually.",
            count=7,
            count_href=reverse("games:list_platforms"),
            actions=platform_actions,
        ),
        EntitySummaryRow(
            label="Devices",
            subtitle="Hardware you use to play.",
            count=0,
            count_href=reverse("games:list_devices"),
            actions=device_actions,
            detail="Preselected when logging a game.",
        ),
    )
    sessions_url = reverse("games:list_sessions")
    stats_url = reverse("games:stats_by_year", args=[localdate().year])
    csrf_token = get_token(request)
    account_menus = Div(class_="flex flex-wrap items-start gap-6")[
        AccountMenu(
            username="alexandra-with-a-deliberately-long-username",
            initials="AL",
            today_played=Link(href=f"{sessions_url}?preview=today")["1h 20m"],
            last_7_played=Link(href=f"{sessions_url}?preview=last-7")["8h 15m"],
            stats_url=stats_url,
            settings_url=reverse("games:settings"),
            admin_settings_url=reverse("games:admin_settings"),
            theme_disabled=False,
            logout_url=reverse("logout"),
            csrf_token=csrf_token,
            id="preview-account-admin",
        ),
        AccountMenu(
            username="preview-normal-user",
            initials="PN",
            today_played=Link(href=f"{sessions_url}?preview=today")["0m"],
            last_7_played=Link(href=f"{sessions_url}?preview=last-7")["2h"],
            stats_url=stats_url,
            settings_url=reverse("games:settings"),
            admin_settings_url=None,
            theme_disabled=False,
            logout_url=reverse("logout"),
            csrf_token=csrf_token,
            id="preview-account-user",
        ),
    ]
    conversion_toasts = Div(class_="flex flex-wrap gap-3 pb-40 md:pb-0")[
        ControlButton(data_preview_conversion_toast="running", color="gray")[
            "Show running"
        ],
        ControlButton(data_preview_conversion_toast="failed", color="gray")[
            "Show failed"
        ],
        ControlButton(data_preview_conversion_toast="complete", color="gray")[
            "Show completed"
        ],
    ]
    sections = [
        SectionedPageSection(
            "statistics-and-facts",
            "Statistics and facts",
            statistics_and_facts,
        ),
        SectionedPageSection(
            "entity-summaries",
            "Entity summaries",
            entity_summaries,
        ),
        SectionedPageSection(
            "account-menus",
            "Account menus",
            account_menus,
        ),
        SectionedPageSection(
            "conversion-toasts",
            "Conversion toast appearances",
            conversion_toasts,
        ),
    ]
    content = Div(class_="flex flex-col gap-6")[
        SectionedPageHeader(
            "Library UI component kit",
            description=(
                "Authenticated DEBUG-only fixtures for issue #826; values are "
                "static and nothing on this page changes Library data."
            ),
        ),
        _LibraryKitPreview()[
            SectionedPageScaffold(
                sections,
                navigation_label="Library kit sections",
                jump_label="Jump to a component group",
            )
        ],
    ]
    return render_page(request, content, title="Library UI component kit")


__all__ = ["library_kit_preview"]
