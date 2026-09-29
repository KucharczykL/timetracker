"""The Library tab, its filter, and its row menu."""

import json
import uuid

import pytest
from django.urls import reverse
from entries import end_entry_access, record_entry, remove_entry

from common.criteria import FilterError
from games.end_ways import EndWay
from games.filters import (
    LibraryEntryFilter,
    filter_query_context_for_library,
    filter_url,
    parse_entry_filter,
)
from games.list_columns import state_shown_columns
from games.models import Game, LibraryEntry, Platform
from games.reads.entries import library_entries
from games.views.entry_menu import entry_row_menu
from games.views.library_list import ENTRY_COLUMNS
from timetracker.temporal import TemporalValue

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def ps5():
    return Platform.objects.create(name="PS5", group="Sony")


@pytest.fixture
def graph(owned_library, stated_graph, ps5):
    return stated_graph(
        Game(name="Tunic", library=owned_library), owned_library, platform=ps5
    )


@pytest.fixture
def other_graph(owned_library, stated_graph):
    return stated_graph(Game(name="Hades", library=owned_library), owned_library)


@pytest.fixture
def stranger_entry(django_user_model, stated_graph, ps5):
    stranger = django_user_model.objects.create_user("stranger").library
    graph = stated_graph(Game(name="Tunic", library=stranger), stranger, platform=ps5)
    return record_entry(stranger, graph.release, access="borrowed", format="physical")


@pytest.fixture
def logged_in(client, owned_user):
    client.force_login(owned_user)
    return client


def _matching(library, criteria: dict) -> set[uuid.UUID]:
    parsed = parse_entry_filter(json.dumps(criteria))
    assert parsed is not None
    rows = library_entries(library).filter(
        parsed.to_q(filter_query_context_for_library(library))
    )
    return set(rows.values_list("pk", flat=True))


# ── The filter ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "criteria",
    [
        {"access": {"value": ["borrowed"], "modifier": "INCLUDES"}},
        {"format": {"value": ["physical"], "modifier": "INCLUDES"}},
        {"is_ended": {"value": True}},
        {"access_end_way": {"value": ["sold"], "modifier": "INCLUDES"}},
        {
            "acquired": {
                "value": "2021-01-01",
                "value2": "2021-12-31",
                "modifier": "BETWEEN",
            }
        },
        {"search": {"value": "Tunic", "modifier": "INCLUDES"}},
        {"note": {"value": "shelf", "modifier": "INCLUDES"}},
    ],
    ids=lambda criteria: next(iter(criteria)),
)
def test_each_criterion_matches_one_copy_and_no_other_librarys(
    owned_library, graph, other_graph, stranger_entry, criteria
):
    wanted = record_entry(
        owned_library,
        graph.release,
        access="borrowed",
        format="physical",
        note="shelf",
        acquired=TemporalValue.parse("2021-05"),
    )
    end_entry_access(wanted, way=EndWay.SOLD)
    record_entry(owned_library, other_graph.release)
    end_entry_access(stranger_entry, way=EndWay.SOLD)

    assert _matching(owned_library, criteria) == {wanted.pk}


def test_platform_and_game_match_through_the_release(
    owned_library, graph, other_graph, ps5
):
    wanted = record_entry(owned_library, graph.release)
    record_entry(owned_library, other_graph.release)

    assert _matching(
        owned_library, {"platform": {"value": [str(ps5.pk)], "modifier": "INCLUDES"}}
    ) == {wanted.pk}
    assert _matching(
        owned_library,
        {"game": {"value": [str(graph.game.pk)], "modifier": "INCLUDES"}},
    ) == {wanted.pk}


def test_a_game_filter_narrows_to_matching_games(owned_library, graph, other_graph):
    wanted = record_entry(owned_library, other_graph.release)
    record_entry(owned_library, graph.release)

    assert _matching(
        owned_library,
        {"game_filter": {"name": {"value": "Hades", "modifier": "EQUALS"}}},
    ) == {wanted.pk}


def test_an_unknown_key_is_refused():
    with pytest.raises(FilterError):
        parse_entry_filter(json.dumps({"price": {"value": 3}}))


def test_filter_url_names_the_library_tab(graph):
    url = filter_url(LibraryEntryFilter.where(game=[graph.game.pk]))

    assert url.startswith(reverse("games:list_library") + "?filter=")


# ── The page ────────────────────────────────────────────────────────────────


def test_the_tab_lists_live_copies_of_this_library_alone(
    logged_in, owned_library, graph, stranger_entry
):
    held = record_entry(owned_library, graph.release, format="physical")
    gone = remove_entry(record_entry(owned_library, graph.release))

    html = logged_in.get(reverse("games:list_library")).content.decode()

    assert str(held.pk) in html
    assert str(gone.pk) not in html
    assert str(stranger_entry.pk) not in html
    assert "Physical" in html


def test_both_tabs_render_the_tab_row(logged_in):
    for route in ("games:list_games", "games:list_library"):
        html = logged_in.get(reverse(route)).content.decode()
        assert f'href="{reverse("games:list_library")}"' in html
        assert 'aria-current="page"' in html


def test_the_library_tab_offers_add_to_library_and_both_acts(logged_in):
    html = logged_in.get(reverse("games:list_library")).content.decode()

    assert reverse("games:add_to_library") in html
    assert reverse("games:run_bulk_action", args=["entry.edit"]) in html
    assert reverse("games:run_bulk_action", args=["entry.remove"]) in html


def test_an_ended_copy_shows_its_way(logged_in, owned_library, graph):
    end_entry_access(
        record_entry(owned_library, graph.release),
        way=EndWay.SOLD,
        ended=TemporalValue.parse("2024"),
    )

    html = logged_in.get(reverse("games:list_library")).content.decode()

    assert "Sold · 2024" in html


def test_the_builder_page_renders_for_copies(logged_in):
    response = logged_in.get(reverse("games:filter_builder", args=["libraryentry"]))

    assert response.status_code == 200


# ── The row menu ────────────────────────────────────────────────────────────


def test_a_held_copys_menu_links_to_end_access(owned_library, graph):
    entry = LibraryEntry.objects.select_related(
        "player_game__game", "release__platform"
    ).get(pk=record_entry(owned_library, graph.release).pk)

    html = str(entry_row_menu(entry, "/tracker/game/library"))

    assert "Tunic (PS5) actions" in html
    assert f"{reverse('games:end_library_entry', args=[entry.pk])}?" in html
    assert reverse("games:edit_library_entry", args=[entry.pk]) in html
    assert "Resume" not in html
    assert reverse("games:remove_library_entry", args=[entry.pk]) in html


def test_an_ended_copys_menu_offers_resume(owned_library, other_graph):
    ended = end_entry_access(record_entry(owned_library, other_graph.release))
    entry = LibraryEntry.objects.select_related(
        "player_game__game", "release__platform"
    ).get(pk=ended.pk)

    html = str(entry_row_menu(entry, None))

    assert "Hades (Unspecified) actions" in html
    assert reverse("games:resume_library_entry", args=[entry.pk]) in html
    assert reverse("games:edit_library_entry_end", args=[entry.pk]) in html
    assert "End access" not in html


# ── Game detail ─────────────────────────────────────────────────────────────


def test_game_detail_links_view_all_to_the_tab(logged_in, owned_library, graph):
    record_entry(owned_library, graph.release)

    html = logged_in.get(graph.game.get_absolute_url()).content.decode()

    assert "View all copies of this game" in html
    assert reverse("games:list_library") + "?filter=" in html


def test_the_note_column_is_off_until_chosen(
    logged_in, owned_user, owned_library, graph
):
    record_entry(owned_library, graph.release, note="boxed, with manual")

    assert (
        "boxed, with manual"
        not in logged_in.get(reverse("games:list_library")).content.decode()
    )

    state_shown_columns(owned_user, "entries", ["game", "note"], ENTRY_COLUMNS)

    assert (
        "boxed, with manual"
        in logged_in.get(reverse("games:list_library")).content.decode()
    )


def test_game_detail_shows_a_copys_note(logged_in, owned_library, graph):
    record_entry(owned_library, graph.release, note="boxed, with manual")

    html = logged_in.get(graph.game.get_absolute_url()).content.decode()

    assert "data-summary-detail" in html
    assert "boxed, with manual" in html
