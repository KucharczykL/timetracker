import uuid
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest
from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from django.utils import timezone
from entries import record_entry
from game_display_order import tied_games
from historical_playtime_rows import record_row
from session_rows import timed_row

from games.api import search_games
from games.bulk_entries import entry_resolution
from games.bulk_game_edit import game_edit_resolution
from games.bulk_removal import game_resolution
from games.bulk_runs import run_resolution
from games.filters import FindFilter
from games.forms import _game_options
from games.models import (
    Game,
    HistoricalPlaytime,
    LegacyPurchase,
    LibraryEntry,
    PlayerSession,
    Playthrough,
    PlaythroughKind,
    game_display_key,
    game_display_order_through,
)
from games.sorting import (
    ENTRY_SORTS,
    GAME_SORTS,
    HISTORICAL_PLAYTIME_SORTS,
    PLAYTHROUGH_SORTS,
    SESSION_SORTS,
    apply_sort,
)


class GameDisplayOrderTest(SimpleTestCase):
    def test_fields_are_local_non_null_columns_ending_in_the_key(self):
        """Python sorts on them too, so no path, no null, a total order."""
        fields = [Game._meta.get_field(name) for name in Game.DISPLAY_ORDER_FIELDS]
        for field in fields:
            self.assertFalse(field.is_relation, field.name)
            self.assertFalse(field.null, field.name)
        self.assertTrue(fields[-1].primary_key)

    def test_key_breaks_a_full_tie_on_the_id(self):
        earlier = Game(name="Doom", sort_name="doom")
        later = Game(name="Doom", sort_name="doom")
        self.assertLess(earlier.id, later.id)
        self.assertEqual(
            sorted([later, earlier], key=game_display_key), [earlier, later]
        )


class GameDisplayOrderReadsTest(TestCase):
    def setUp(self):
        self.library = User.objects.create_user(username="order").library

    def test_related_manager_reads_in_display_order(self):
        games = tied_games(self.library)
        purchase = LegacyPurchase.objects.create(
            library=self.library, date_purchased="2025-01-01", price_currency="USD"
        )
        purchase.games.set(games)
        self.assertEqual(list(purchase.games.in_display_order()), games)

    def test_order_through_a_relation(self):
        self.assertEqual(
            game_display_order_through("player_game__game"),
            (
                "player_game__game__sort_name",
                "player_game__game__name",
                "player_game__game__id",
            ),
        )


class GameQuerysetsReadInDisplayOrderTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser("order", "o@e.com", "pw")
        self.client.force_login(self.user)
        self.library = self.user.library
        self.games = tied_games(self.library)
        self.expected = [game.id for game in self.games]

    def _bundle(self):
        bundle = LegacyPurchase.objects.create(
            library=self.library,
            price=70,
            price_currency="USD",
            date_purchased=date(2025, 1, 1),
            ownership_type=LegacyPurchase.DIGITAL,
            type=LegacyPurchase.GAME,
        )
        bundle.games.set(reversed(self.games))
        return bundle

    def test_search_answers_in_display_order(self):
        request = SimpleNamespace(user=self.user)
        self.assertEqual(
            [row["value"] for row in search_games(request, limit=100)], self.expected
        )
        #: Five cuts between the two tied on sort_name.
        self.assertEqual(
            [row["value"] for row in search_games(request, limit=5)],
            self.expected[:5],
        )

    def test_picker_resolves_selected_games_in_display_order(self):
        options = _game_options(list(reversed(self.expected)), library=self.library)
        self.assertEqual([option["value"] for option in options], self.expected)

    def test_first_game_leads_the_display_order(self):
        self.assertEqual(self._bundle().first_game, self.games[0])

    def test_first_game_reads_prefetched_games(self):
        bundle = LegacyPurchase.objects.prefetch_related("games").get(
            pk=self._bundle().pk
        )
        with self.assertNumQueries(0):
            self.assertEqual(bundle.first_game, self.games[0])

    def test_game_resolutions_answer_in_display_order(self):
        for resolution in (game_resolution, game_edit_resolution):
            rows = resolution(self.library, list(reversed(self.expected))).rows
            self.assertEqual([row.id for row in rows], self.expected)


def _runs_of(library, games):
    """Two runs a game; seconds made last."""
    firsts = [
        Playthrough.objects.get(library=library, player_game__game=game)
        for game in games
    ]
    seconds = [
        Playthrough.objects.create(
            pk=uuid.uuid7(),
            library=library,
            player_game=run.player_game,
            kind=PlaythroughKind.ORDINARY,
            created_at=timezone.now(),
        )
        for run in firsts
    ]
    return [run for pair in zip(firsts, seconds, strict=True) for run in pair]


def _sorted_column(queryset, sort, sort_map, path):
    ordered = apply_sort(queryset, FindFilter(sort=sort), sort_map, sort).queryset
    return list(ordered.values_list(path, flat=True))


def _directed(expected, sort):
    return expected[::-1] if sort.startswith("-") else expected


@pytest.fixture
def games(owned_library):
    return tied_games(owned_library)


@pytest.mark.parametrize("sort", ["name", "playthrough"])
def test_run_sorts_group_runs_by_game_in_display_order(owned_library, games, sort):
    runs = _runs_of(owned_library, games)
    queryset = Playthrough.objects.filter(library=owned_library)
    assert _sorted_column(queryset, sort, PLAYTHROUGH_SORTS, "id") == [
        run.id for run in runs
    ]
    assert _sorted_column(queryset, f"-{sort}", PLAYTHROUGH_SORTS, "player_game__game")[
        ::2
    ] == [game.id for game in reversed(games)]


@pytest.mark.parametrize("sort", ["name", "-name", "playthrough", "-playthrough"])
def test_session_sorts_group_sessions_by_game_in_display_order(
    owned_library, games, sort
):
    runs = _runs_of(owned_library, games)
    started = datetime(2025, 1, 1, 12, tzinfo=UTC)
    for run in reversed(runs):
        timed_row(run, started, started + timedelta(hours=1))
    queryset = PlayerSession.objects.filter(library=owned_library)
    expected = [run.player_game.game_id for run in runs]
    assert _sorted_column(
        queryset, sort, SESSION_SORTS, "playthrough__player_game__game"
    ) == _directed(expected, sort)


@pytest.mark.parametrize("sort", ["name", "-name"])
def test_record_name_sort_reads_display_order(owned_library, games, sort):
    for game in reversed(games):
        record_row(
            [Playthrough.objects.get(library=owned_library, player_game__game=game)]
        )
    queryset = HistoricalPlaytime.objects.filter(library=owned_library)
    assert _sorted_column(
        queryset, sort, HISTORICAL_PLAYTIME_SORTS, "player_game__game"
    ) == _directed([game.id for game in games], sort)


@pytest.mark.parametrize("sort", ["sort_name", "-sort_name", "kind", "-kind"])
def test_game_sort_name_sort_reads_display_order(owned_library, games, sort):
    queryset = Game.objects.filter(library=owned_library)
    assert _sorted_column(queryset, sort, GAME_SORTS, "id") == _directed(
        [game.id for game in games], sort
    )


@pytest.mark.parametrize("sort", ["name", "-name"])
def test_entries_resolve_and_sort_in_display_order(
    owned_library, games, stated_graph, sort
):
    entries = [
        record_entry(owned_library, stated_graph(game, owned_library).release)
        for game in reversed(games)
    ]
    expected = [game.id for game in games]
    resolved = entry_resolution(owned_library, [entry.id for entry in entries]).rows
    assert [entry.player_game.game_id for entry in resolved] == expected
    queryset = LibraryEntry.objects.filter(library=owned_library)
    assert _sorted_column(
        queryset, sort, ENTRY_SORTS, "player_game__game"
    ) == _directed(expected, sort)


def test_runs_resolve_grouped_by_game_in_display_order(owned_library, games):
    runs = _runs_of(owned_library, games)
    resolved = run_resolution(owned_library, [run.id for run in reversed(runs)]).rows
    assert [run.id for run in resolved] == [run.id for run in runs]
