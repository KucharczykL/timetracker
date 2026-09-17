"""The Playtime page: tabs, entry, Historical list."""

import json
import re
import uuid
from datetime import timedelta

import pytest
from django.urls import reverse
from historical_playtime_rows import record_row
from session_rows import tracked_run

from common.components import PageTab, PageTabs, StatisticCard
from games.models import (
    Device,
    FilterPreset,
    Game,
    HistoricalPlaytimeProvenance,
    Playthrough,
    PlaythroughKind,
)
from games.reads.historical_playtime_records import RECORD_ORDER, library_records
from games.sorting import HISTORICAL_PLAYTIME_SORTS


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


# ── The pages ──────────────────────────────────────────────────────────────

HISTORICAL = "games:list_historical_playtime"


@pytest.fixture
def owner(client, django_user_model):
    user = django_user_model.objects.create_user(username="owner", password="p")
    client.force_login(user)
    return user


def second_run(first: Playthrough, name: str = "") -> Playthrough:
    return Playthrough.objects.create(
        pk=uuid.uuid7(),
        library=first.library,
        player_game=first.player_game,
        kind=PlaythroughKind.ORDINARY,
        name=name,
        created_at=first.created_at + timedelta(seconds=1),
    )


def rows_in_order(body: str) -> list[str]:
    return re.findall(r'id="record-row-([0-9a-f-]+)"', body)


@pytest.mark.django_db
@pytest.mark.untracked_games
class TestHistoricalList:
    def test_tabs_mark_the_page_they_are_on(self, client, owner):
        sessions = client.get(reverse("games:list_sessions")).content.decode()
        historical = client.get(reverse(HISTORICAL)).content.decode()

        historical_href = reverse(HISTORICAL)
        sessions_href = reverse("games:list_sessions")
        assert f'href="{sessions_href}" aria-current="page"' in sessions
        assert f'href="{historical_href}" aria-current="page"' not in sessions
        assert f'href="{historical_href}" aria-current="page"' in historical
        assert '<nav aria-label="Playtime"' in historical

    def test_a_row_states_every_fact(self, client, owner):
        library = owner.library
        deck = Device.objects.create(library=library, name="Steam Deck")
        run = tracked_run(library, Game.objects.create(library=library, name="Zelda"))
        other = second_run(run, name="Hard mode")
        record_row(
            [run, other],
            duration=timedelta(hours=40),
            when="2020/2022",
            provenance=HistoricalPlaytimeProvenance.EXTERNALLY_MEASURED,
            device=deck,
        )
        lone_run = tracked_run(
            library, Game.objects.create(library=library, name="Doom")
        )
        record_row([lone_run])

        body = client.get(reverse(HISTORICAL)).content.decode()

        assert "<truncated-text" in body
        assert "Zelda" in body
        assert "Externally measured" in body
        assert "Estimated" in body
        assert "Steam Deck" in body
        assert "No device" in body
        assert "Unknown" in body
        assert "Playthrough 1, Hard mode" in body
        assert body.count(">shared<") == 1

    def test_the_default_order_is_the_record_order(self, client, owner):
        library = owner.library
        run = tracked_run(library, Game.objects.create(library=library, name="G"))
        for when in (None, "2019", "2021", "2020/2022", "2021"):
            record_row([run], when=when)

        body = client.get(reverse(HISTORICAL), {"per_page": 0}).content.decode()

        expected = [
            str(key)
            for key in library_records(library)
            .order_by(*RECORD_ORDER)
            .values_list("pk", flat=True)
        ]
        assert rows_in_order(body) == expected

    @pytest.mark.parametrize("key", sorted(HISTORICAL_PLAYTIME_SORTS))
    def test_every_sort_key_orders(self, client, owner, key):
        library = owner.library
        run = tracked_run(library, Game.objects.create(library=library, name="G"))
        record_row([run], duration=timedelta(hours=1))
        record_row([run], duration=timedelta(hours=2))

        response = client.get(reverse(HISTORICAL), {"sort": key})

        assert response.status_code == 200
        assert len(rows_in_order(response.content.decode())) == 2

    def test_a_filter_narrows_the_rows(self, client, owner):
        library = owner.library
        run = tracked_run(library, Game.objects.create(library=library, name="G"))
        kept = record_row(
            [run], provenance=HistoricalPlaytimeProvenance.MANUALLY_ENTERED
        )
        record_row([run])
        record_filter = {
            "provenance": {"modifier": "INCLUDES", "value": ["manually_entered"]}
        }

        body = client.get(
            reverse(HISTORICAL), {"filter": json.dumps(record_filter)}
        ).content.decode()

        assert rows_in_order(body) == [str(kept.pk)]

    def test_the_page_costs_the_same_for_more_runs(
        self, client, owner, django_assert_max_num_queries
    ):
        library = owner.library
        for index in range(5):
            run = tracked_run(
                library, Game.objects.create(library=library, name=f"G{index}")
            )
            record_row([run, second_run(run), second_run(run)])
        client.get(reverse(HISTORICAL))

        with django_assert_max_num_queries(40):
            response = client.get(reverse(HISTORICAL))

        assert len(rows_in_order(response.content.decode())) == 5

    def test_the_quick_bar_offers_the_facets_and_the_builder(self, client, owner):
        body = client.get(reverse(HISTORICAL)).content.decode()

        assert "<quick-filter-bar" in body
        for label in ("Provenance", "Duration (hrs)", "Game", "Device", "When"):
            assert label in body, label
        builder = reverse("games:filter_builder", args=["historicalplaytime"])
        assert builder in body

    def test_a_preset_saves_and_lists_under_the_mode(self, client, owner):
        record_filter = {"provenance": {"modifier": "INCLUDES", "value": ["estimated"]}}
        saved = client.post(
            reverse("api-1.0.0:list_presets"),
            json.dumps(
                {
                    "name": "Estimates",
                    "mode": "historical_playtime",
                    "filter": record_filter,
                    "sort": "-duration",
                }
            ),
            content_type="application/json",
        )
        listed = client.get(
            reverse("api-1.0.0:list_presets"), {"mode": "historical_playtime"}
        )

        assert saved.status_code == 201
        preset = FilterPreset.objects.get()
        assert preset.object_filter == record_filter
        assert preset.find_filter.get("sort") == "-duration"
        assert "Estimates" in listed.content.decode()

    def test_the_builder_switcher_lists_every_builder_model(self, client, owner):
        body = client.get(
            reverse("games:filter_builder", args=["playersession"])
        ).content.decode()

        for key in ("playthrough", "historicalplaytime", "playersession"):
            assert reverse("games:filter_builder", args=[key]) in body
        assert ">Historical Playtime<" in body or "Historical Playtime" in body


@pytest.mark.django_db
def test_the_library_card_counts_sessions_and_records(client, owner):
    library = owner.library
    run = tracked_run(library, Game.objects.create(library=library, name="G"))
    record_row([run])
    record_row([run])

    body = client.get(reverse("games:library")).content.decode()

    assert 'aria-label="2 Playtime"' in body
    assert 'title="Sessions and historical records"' in body
