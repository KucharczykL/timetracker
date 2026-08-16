import pytest

from common.components import (
    AccountMenu,
    CopyControl,
    Div,
    EntitySummaryAction,
    EntitySummaryList,
    EntitySummaryRow,
    FactList,
    StatisticCard,
    StatisticGrid,
    TooltipDefinition,
    TooltipDefinitionList,
    collect_media,
)


def test_statistic_card_keeps_values_plain_and_non_interactive():
    html = str(StatisticCard("Games", 851))

    assert 'data-statistic-card=""' in html
    assert "<a" not in html
    assert "href=" not in html
    assert "Games" in html and ">851<" in html


def test_three_statistics_fill_the_wide_grid_and_zero_keeps_the_same_shape():
    plain = str(StatisticCard("Unavailable", "—"))
    zero = str(StatisticCard("Devices", 0))

    assert "<a" not in plain
    assert "<a" not in zero
    grid = str(
        StatisticGrid(
            StatisticCard("Games", 0),
            StatisticCard("Spent", 0),
            StatisticCard("Devices", 0),
        )
    )
    assert 'data-statistic-grid=""' in grid
    assert grid.count('data-statistic-card=""') == 3
    assert "grid-cols-2" in grid
    assert "@xl:grid-cols-3" in grid
    assert "last:col-span-2" in grid
    assert " p-4" not in grid


def test_fact_list_accepts_arbitrary_value_children():
    html = str(
        FactList(
            [
                (
                    "Library ID",
                    Div()[
                        "018f0000-0000-7000-8000-000000000000",
                        CopyControl("018f0000-0000-7000-8000-000000000000"),
                    ],
                ),
                ("Created", "31/12/2022"),
            ]
        )
    )

    assert '<dl data-fact-list=""' in html
    assert html.count("<dt") == 2
    assert html.count("<dd") == 2
    assert "Copy" in html


def test_fact_list_does_not_reuse_tooltip_presentation():
    fact_html = str(FactList([("Created", "31/12/2022")]))
    tooltip_html = str(TooltipDefinitionList([TooltipDefinition("Source", "Database")]))

    assert "data-tooltip-definition-list" not in fact_html
    assert "data-fact-list" not in tooltip_html
    assert 'data-tooltip-definition-list=""' in tooltip_html


def test_copy_control_exposes_value_description_live_label_and_media():
    control = CopyControl(
        "018f0000-0000-7000-8000-000000000000",
        description="Copy Library ID",
    )
    html = str(control)

    assert '<copy-control value="018f0000-0000-7000-8000-000000000000"' in html
    assert 'data-copy-control=""' in html
    assert 'data-copy-label=""' in html
    assert 'aria-live="polite"' in html
    assert 'aria-label="Copy Library ID"' in html
    assert 'data-copy-icon=""' in html
    assert "sr-only" in html
    media = collect_media(control)
    assert "<pop-over" in html
    assert 'data-pop-over-trigger=""' in html
    assert 'role="tooltip"' in html
    assert "dist/elements/copy-control.js" in media.js
    assert "dist/elements/pop-over.js" in media.js


def test_entity_row_renders_both_presentations_from_one_action_source():
    actions = (
        EntitySummaryAction("Browse", "/tracker/game/list"),
        EntitySummaryAction("Add", "/tracker/game/add"),
    )
    html = str(
        EntitySummaryRow(
            label="Games",
            subtitle="Games currently tracked in this library.",
            count=851,
            count_href="/tracker/game/list",
            actions=actions,
        )
    )

    assert html.count('href="/tracker/game/list"') == 3
    assert html.count('href="/tracker/game/add"') == 2
    assert 'data-entity-summary-wide-actions=""' in html
    assert 'data-entity-summary-overflow=""' in html
    assert 'aria-label="Games actions"' in html
    assert 'aria-label="851 Games"' in html


def test_entity_list_is_divider_separated_without_a_nested_card_border():
    html = str(
        EntitySummaryList(
            EntitySummaryRow(
                label="Devices",
                subtitle="Hardware you use to play.",
                count=2,
                detail="Preselected when logging a game.",
            )
        )
    )

    opening = html[: html.index(">")]
    assert 'data-entity-summary-list=""' in opening
    assert "divide-y" in opening
    assert "border" not in opening
    assert 'data-entity-summary-detail=""' in html


def test_entity_row_with_no_actions_renders_no_empty_overflow_menu():
    html = str(
        EntitySummaryRow(
            label="Play events",
            subtitle="No management surface.",
            count=0,
        )
    )

    assert "data-entity-summary-overflow" not in html
    assert "<drop-down" not in html


def _account_menu(**overrides):
    values = {
        "username": "alexandra-with-a-long-name",
        "initials": "AW",
        "today_played": Div()["Today value"],
        "last_7_played": Div()["Last 7 days value"],
        "stats_url": "/tracker/stats/2026",
        "settings_url": "/tracker/settings",
        "admin_settings_url": "/tracker/admin-settings",
        "theme_disabled": False,
        "logout_url": "/logout/",
        "csrf_token": "token",
    }
    values.update(overrides)
    return AccountMenu(**values)


def test_account_menu_has_exact_order_groups_and_circular_trigger():
    html = str(_account_menu())
    trigger = html[: html.index("data-menu")]
    panel = html[html.index("data-menu") :]

    assert 'aria-label="Open account menu for alexandra-with-a-long-name"' in trigger
    assert "rounded-full" in trigger
    assert ">AW<" in trigger
    ordered = [
        "alexandra-with-a-long-name",
        "theme-toggle",
        "Today",
        "Today value",
        "Last 7 days",
        "Last 7 days value",
        "Stats",
        "Settings",
        "Admin settings",
        "Log out",
    ]
    positions = [panel.index(value) for value in ordered]
    assert positions == sorted(positions)
    assert panel.count('role="separator"') == 2
    assert 'action="/logout/"' in panel
    assert 'name="csrfmiddlewaretoken" value="token"' in panel


def test_account_menu_omits_admin_without_changing_the_initials_trigger():
    html = str(_account_menu(admin_settings_url=None))

    assert "Admin settings" not in html
    assert ">AW<" in html
    assert "Open account menu for alexandra-with-a-long-name" in html


def test_account_menu_rejects_empty_initials():
    with pytest.raises(ValueError, match="initials must not be empty"):
        _account_menu(initials="")


def test_account_menu_forwards_the_theme_disabled_state():
    html = str(_account_menu(theme_disabled=True))

    assert '<theme-toggle disabled="true"' in html
