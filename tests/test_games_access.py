"""The Games tab reads copies: access and format facets, a count, a relation."""

import json

import pytest
from django.urls import reverse
from entries import end_entry_access, record_entry
from tracked_games import create_tracked_game

from common.components.quick_filter import QUICK_FACETS, is_quick_editable
from common.criteria import field_metadata
from common.filter_execution import execute_filter
from games.commands.playergame import TrackGame
from games.end_ways import EndWay
from games.events.dispatch import dispatch
from games.filters import GameFilter, filter_query_context_for_library
from games.list_columns import state_shown_columns
from games.models import Game
from games.views.game import game_list_columns

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def games(owned_library, stated_graph):
    """Owned: an owned digital copy and a sold physical one. Borrowed: one
    borrowed physical copy. Former: its one copy ended. Both: an owned and a
    borrowed copy. Bare: tracked, no copy."""

    def graph(name):
        return stated_graph(Game(name=name, library=owned_library), owned_library)

    owned, borrowed, former, both = (
        graph(name) for name in ("Owned", "Borrowed", "Former", "Both")
    )
    record_entry(owned_library, owned.release)
    end_entry_access(
        record_entry(owned_library, owned.release, format="physical"),
        way=EndWay.SOLD,
    )
    record_entry(owned_library, borrowed.release, access="borrowed", format="physical")
    end_entry_access(record_entry(owned_library, former.release))
    record_entry(owned_library, both.release)
    record_entry(owned_library, both.release, access="borrowed")
    bare = create_tracked_game(owned_library, "Bare")
    return {
        "Owned": owned.game,
        "Borrowed": borrowed.game,
        "Former": former.game,
        "Both": both.game,
        "Bare": bare,
    }


def _matching(library, criteria: dict) -> set[str]:
    game_filter = GameFilter.from_json(criteria)
    assert game_filter is not None
    context = filter_query_context_for_library(library)
    return {
        game.name
        for game in execute_filter(
            game_filter, Game.objects.tracked_by(library), context
        )
    }


@pytest.mark.parametrize(
    ("criterion", "expected"),
    [
        ({"value": ["owned"], "modifier": "INCLUDES"}, {"Owned", "Both"}),
        (
            {"value": ["owned"], "modifier": "EXCLUDES"},
            {"Borrowed", "Former", "Bare"},
        ),
        ({"value": ["owned"], "modifier": "INCLUDES_ONLY"}, {"Owned"}),
        ({"value": ["owned", "borrowed"], "modifier": "INCLUDES_ALL"}, {"Both"}),
        ({"modifier": "IS_NULL"}, {"Former", "Bare"}),
        ({"modifier": "NOT_NULL"}, {"Owned", "Borrowed", "Both"}),
        (
            {"value": ["owned", "borrowed"], "excludes": ["borrowed"]},
            {"Owned"},
        ),
        (
            {"value": [], "excludes": ["owned"]},
            {"Borrowed", "Former", "Bare"},
        ),
    ],
    ids=[
        "includes",
        "excludes",
        "includes-only",
        "includes-all",
        "is-null",
        "not-null",
        "includes-beside-excludes",
        "excludes-alone",
    ],
)
def test_access_reads_held_copies_alone(owned_library, games, criterion, expected):
    assert _matching(owned_library, {"access": criterion}) == expected


def test_format_ignores_an_ended_copy(owned_library, games):
    physical = {"format": {"value": ["physical"], "modifier": "INCLUDES"}}

    assert _matching(owned_library, physical) == {"Borrowed"}


def test_entry_count_counts_ended_copies_too(owned_library, games):
    two = {"entry_count": {"value": 2, "modifier": "EQUALS"}}

    assert _matching(owned_library, two) == {"Owned", "Both"}


def test_entry_filter_narrows_by_a_copy(owned_library, games):
    sold = {
        "entry_filter": {"access_end_way": {"value": ["sold"], "modifier": "INCLUDES"}}
    }

    assert _matching(owned_library, sold) == {"Owned"}


def test_a_shared_game_counts_one_librarys_copies(
    owned_library, django_user_model, stated_graph
):
    graph = stated_graph(Game(name="Hades", library=owned_library), owned_library)
    record_entry(owned_library, graph.release)
    Game.objects.filter(pk=graph.game.pk).update(library=None)
    second = django_user_model.objects.create_user("second").library
    dispatch(
        TrackGame(game_id=graph.game.pk),
        actor=second.user,
        library=second,
        idempotency_key="track-hades",
    )

    held = {"access": {"modifier": "NOT_NULL"}}
    counted = {"entry_count": {"value": 0, "modifier": "GREATER_THAN"}}

    assert _matching(owned_library, held) == {"Hades"}
    assert _matching(second, held) == set()
    assert _matching(second, counted) == set()


@pytest.mark.parametrize("facet", ["access", "format"])
def test_the_bars_output_stays_editable(facet):
    criterion = {"value": ["owned"], "excludes": ["pirated"], "modifier": "INCLUDES"}
    if facet == "format":
        criterion = {"value": ["digital"], "modifier": "INCLUDES"}

    assert facet in {quick.field for quick in QUICK_FACETS["games"]}
    assert is_quick_editable(
        {facet: criterion},
        {quick.field for quick in QUICK_FACETS["games"]},
        filter_cls=GameFilter,
    )


# ── The column ──────────────────────────────────────────────────────────────


@pytest.fixture
def logged_in(client, owned_user):
    client.force_login(owned_user)
    return client


def test_the_column_is_hidden_by_default(logged_in, games):
    html = logged_in.get(reverse("games:list_games")).content.decode()

    assert "Owned · Digital" not in html


def test_the_column_shows_each_badge_once_chosen(logged_in, owned_user, games):
    state_shown_columns(
        owned_user,
        "games",
        ["name", "access"],
        game_list_columns("Playtime"),
    )

    html = logged_in.get(reverse("games:list_games")).content.decode()

    assert '<span class="sr-only">You have 1 version, and had 1</span>' in html
    assert '<span class="sr-only">You have a physical version</span>' in html
    assert '<span class="sr-only">You have 2 versions</span>' in html
    assert '<span class="sr-only">You had a digital version, returned</span>' in html


def test_the_facets_render_on_the_games_list(logged_in):
    response = logged_in.get(
        reverse("games:list_games"),
        {"filter": json.dumps({"access": {"value": ["owned"]}})},
    )

    html = response.content.decode()
    assert 'id="quick-access-dropdown"' in html
    assert 'id="quick-format-dropdown"' in html


def test_the_builder_names_the_count_copies():
    labels = {meta["name"]: meta["label"] for meta in field_metadata(GameFilter)}

    assert labels["entry_count"] == "Copies"
