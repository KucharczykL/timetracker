from common.components import (
    Div,
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
