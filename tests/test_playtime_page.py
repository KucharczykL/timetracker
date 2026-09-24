"""The Playtime page: tabs, entry, Historical list."""

import html
import json
import re
import uuid
from datetime import timedelta

import pytest
from devices import create_device
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from historical_playtime_rows import record_row
from session_rows import session_row, tracked_run
from statistic_cards import statistic_card

from common.components import PageTab, PageTabs, StatisticCard
from common.returns import action_url
from games.events.dispatch import RowUnreadable
from games.models import (
    FilterPreset,
    Game,
    HistoricalPlaytime,
    HistoricalPlaytimeProvenance,
    HistoricalPlaytimeRun,
    Playthrough,
    PlaythroughKind,
)
from games.reads.historical_playtime_records import RECORD_ORDER, library_records
from games.sorting import HISTORICAL_PLAYTIME_SORTS
from games.views.historical_playtime import PROVENANCE_TONES


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


def _tab_corners(html: str) -> list[list[str]]:
    """The rounding classes each tab link carries, in render order."""
    return [
        [
            word
            for word in link.split('class="')[1].split('"')[0].split()
            if word.startswith("rounded-")
        ]
        for link in html.split("<a ")[1:]
    ]


def test_page_tabs_round_the_row_at_its_ends_only():
    """A tab row is a joined row, so only its two outer ends round. The tabs
    are ``ControlLink``, so nothing refuses a corner stated by class here —
    only this assertion does."""
    two = str(PageTabs("Playtime", [PageTab("One", "/one"), PageTab("Two", "/two")]))
    assert _tab_corners(two) == [["rounded-s-base"], ["rounded-e-base"]]

    three = str(
        PageTabs(
            "Playtime",
            [
                PageTab("One", "/one"),
                PageTab("Two", "/two"),
                PageTab("Three", "/three"),
            ],
        )
    )
    assert _tab_corners(three) == [["rounded-s-base"], [], ["rounded-e-base"]]

    lone = str(PageTabs("Playtime", [PageTab("Only", "/only")]))
    assert _tab_corners(lone) == [["rounded-base"]]


def test_a_statistic_card_states_its_title_only_when_given():
    assert 'title="What it counts"' in str(
        StatisticCard("Playtime", 3, title="What it counts")
    )
    assert "title=" not in str(StatisticCard("Playtime", 3))


# ── The pages ──────────────────────────────────────────────────────────────

HOUR = timedelta(hours=1)
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
        deck = create_device(library=library, name="Steam Deck")
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
        low_device = create_device(library=library, name="A device")
        high_device = create_device(library=library, name="Z device")
        low_game = Game.objects.create(library=library, name="Alpha", sort_name="alpha")
        high_game = Game.objects.create(
            library=library, name="Omega", sort_name="omega"
        )
        low = record_row(
            [tracked_run(library, low_game)],
            duration=timedelta(hours=1),
            when="2001",
            device=low_device,
        )
        high = record_row(
            [tracked_run(library, high_game)],
            duration=timedelta(hours=2),
            when="2002",
            provenance=HistoricalPlaytimeProvenance.MANUALLY_ENTERED,
            device=high_device,
        )
        HistoricalPlaytime.objects.filter(pk=high.pk).update(
            created_at=low.created_at + timedelta(minutes=1)
        )

        ascending = client.get(reverse(HISTORICAL), {"sort": key}).content.decode()
        descending = client.get(
            reverse(HISTORICAL), {"sort": f"-{key}"}
        ).content.decode()

        assert rows_in_order(ascending) == [str(low.pk), str(high.pk)]
        assert rows_in_order(descending) == [str(high.pk), str(low.pk)]

    def test_an_unknown_when_sorts_last_both_ways(self, client, owner):
        library = owner.library
        run = tracked_run(library, Game.objects.create(library=library, name="G"))
        unknown = record_row([run])
        known = record_row([run], when="2001")

        for sort in ("when", "-when"):
            body = client.get(reverse(HISTORICAL), {"sort": sort}).content.decode()
            assert rows_in_order(body) == [str(known.pk), str(unknown.pk)], sort

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

    def test_the_page_costs_the_same_for_more_records_and_runs(self, client, owner):
        library = owner.library

        def queries_for_page() -> int:
            client.get(reverse(HISTORICAL))
            with CaptureQueriesContext(connection) as captured:
                client.get(reverse(HISTORICAL))
            return len(captured)

        first = tracked_run(library, Game.objects.create(library=library, name="G"))
        record_row([first])
        one_record = queries_for_page()
        for index in range(4):
            run = tracked_run(
                library, Game.objects.create(library=library, name=f"G{index}")
            )
            record_row([run, second_run(run), second_run(run)])

        assert queries_for_page() == one_record

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

        labels = re.findall(
            r'href="/tracker/[a-z]+/filter" role="menuitem"[^>]*>([^<]+)<', body
        )
        assert labels == [
            "Device",
            "Game",
            "Historical Playtime",
            "Platform",
            "Playthrough",
            "Purchase",
            "Session",
        ]


@pytest.mark.django_db
def test_the_library_card_states_live_playtime_only(client, owner, django_user_model):
    library = owner.library
    run = tracked_run(library, Game.objects.create(library=library, name="G"))
    started = timezone.now() - timedelta(hours=2)
    session_row(run.player_game.game, started_at=started, ended_at=started + HOUR)
    record_row([run])
    record_row([run])
    removed = record_row([run])
    HistoricalPlaytime.objects.filter(pk=removed.pk).update(removed_at=timezone.now())
    other = django_user_model.objects.create_user(username="other").library
    record_row([tracked_run(other, Game.objects.create(library=other, name="O"))])

    body = client.get(reverse("games:library")).content.decode()

    card = statistic_card(body, "Playtime")
    #: One tracked hour and two live records of an hour each. The removed
    #: record and the other library's are outside the figure.
    assert "3.0 h" in card
    assert "1.0 h" in card
    assert "</span> tracked" in card
    assert "2.0 h" in card
    assert "</span> historical" in card
    assert 'title="Tracked sessions and historical records"' in card


def test_every_provenance_has_a_tone():
    assert set(PROVENANCE_TONES) == set(HistoricalPlaytimeProvenance.values)


@pytest.mark.django_db
@pytest.mark.untracked_games
def test_each_row_offers_edit_and_remove_back_to_the_list(client, owner):
    library = owner.library
    run = tracked_run(library, Game.objects.create(library=library, name="G"))
    record = record_row([run])
    page = f"{reverse(HISTORICAL)}?page=1"

    body = client.get(page).content.decode()

    for route in ("games:edit_historical_playtime", "games:remove_historical_playtime"):
        assert action_url(route, record.pk, origin=page) in html.unescape(body)
    #: Behind the row's own trigger, not in a column of their own.
    assert f'id="record-menu-{record.pk}"' in body
    assert ">Actions<" not in body


@pytest.mark.django_db
@pytest.mark.untracked_games
def test_a_run_the_page_cannot_name_is_a_defect(client, owner):
    library = owner.library
    run = tracked_run(library, Game.objects.create(library=library, name="G"))
    record = record_row([run])
    bucket = Playthrough.objects.create(
        pk=uuid.uuid7(),
        library=library,
        player_game=run.player_game,
        kind=PlaythroughKind.IMPORTED_HISTORY,
        created_at=timezone.now(),
    )
    HistoricalPlaytimeRun.objects.create(
        id=uuid.uuid7(), library=library, record=record, playthrough=bucket
    )
    client.raise_request_exception = True

    with pytest.raises(RowUnreadable, match=str(record.pk)):
        client.get(reverse(HISTORICAL))


def summary_of(body: str) -> str:
    """The first row's second line."""
    [line] = re.findall(r'data-row-summary=""[^>]*>([^<]*)<', body)[:1]
    return html.unescape(line)


@pytest.mark.django_db
@pytest.mark.untracked_games
class TestHistoricalListSummary:
    """The stacked cell's second line, below md."""

    def test_the_list_states_the_seven_columns_and_sorts_them(self, client, owner):
        library = owner.library
        run = tracked_run(library, Game.objects.create(library=library, name="G"))
        record_row([run])

        body = client.get(reverse(HISTORICAL)).content.decode()

        for label in (
            "Name",
            "When",
            "Duration",
            "Provenance",
            "Playthroughs",
            "Device",
            "Created",
        ):
            assert f">{label}<" in body
        assert ">Actions<" not in body
        assert "?sort=when" in html.unescape(body)

    def test_a_row_states_the_day_the_duration_and_the_device(self, client, owner):
        library = owner.library
        deck = create_device(library=library, name="Steam Deck")
        run = tracked_run(library, Game.objects.create(library=library, name="G"))
        record_row([run], duration=timedelta(hours=2), when="2026-03-05", device=deck)

        summary = summary_of(client.get(reverse(HISTORICAL)).content.decode())

        assert summary == "2026-03-05, 2.0 h, Steam Deck"

    def test_an_unknown_day_states_no_part(self, client, owner):
        library = owner.library
        run = tracked_run(library, Game.objects.create(library=library, name="G"))
        record_row([run], when=None)

        assert "Unknown" not in summary_of(
            client.get(reverse(HISTORICAL)).content.decode()
        )

    def test_a_record_with_no_device_states_no_part(self, client, owner):
        library = owner.library
        run = tracked_run(library, Game.objects.create(library=library, name="G"))
        record_row([run], when="2026-03-05")

        assert "No device" not in summary_of(
            client.get(reverse(HISTORICAL)).content.decode()
        )
