from common.components import (
    Div,
    EntitySummaryAction,
    EntitySummaryList,
    EntitySummaryRow,
    FactList,
    StatisticCard,
    StatisticGrid,
    TooltipDefinition,
    TooltipDefinitionList,
)


def test_statistic_card_links_the_value_with_a_subject_accessible_name():
    html = str(StatisticCard("Games", 851, href="/tracker/game/list"))

    assert 'data-statistic-card=""' in html
    assert 'href="/tracker/game/list"' in html
    assert 'aria-label="851 Games"' in html
    assert "Games" in html and ">851<" in html
    assert "Browse" not in html


def test_plain_and_zero_statistics_keep_the_same_card_shape():
    plain = str(StatisticCard("Unavailable", "—"))
    zero = str(StatisticCard("Devices", 0, href="/tracker/device/list"))

    assert "<a" not in plain
    assert 'aria-label="0 Devices"' in zero
    assert 'href="/tracker/device/list"' in zero
    grid = str(StatisticGrid(StatisticCard("Games", 0), StatisticCard("Devices", 0)))
    assert 'data-statistic-grid=""' in grid
    assert grid.count('data-statistic-card=""') == 2


def test_fact_list_accepts_arbitrary_value_children():
    html = str(
        FactList(
            [
                (
                    "Library ID",
                    Div()[
                        "018f0000-0000-7000-8000-000000000000",
                        "Copy",
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
