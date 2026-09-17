"""The Playtime page: its tabs, entry and Historical list."""

from common.components import PageTab, PageTabs, StatisticCard


def test_page_tabs_mark_only_the_current_tab():
    html = str(
        PageTabs(
            "Playtime",
            [PageTab("One", "/one"), PageTab("Two & more", "/two", current=True)],
        )
    )

    assert '<nav aria-label="Playtime"' in html
    assert html.count("<a ") == 2
    assert html.count('aria-current="page"') == 1
    assert 'href="/two" aria-current="page"' in html
    assert "Two &amp; more" in html


def test_a_statistic_card_states_its_title_only_when_given():
    assert 'title="What it counts"' in str(
        StatisticCard("Playtime", 3, title="What it counts")
    )
    assert "title=" not in str(StatisticCard("Playtime", 3))
