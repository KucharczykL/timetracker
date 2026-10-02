"""The reads that grow with the library, named for the budget.

Each executes the function the page calls, to a list, so the timed
plan is the served one. One threshold for every read; the spec
names materialisation of exactly a breaching cell as the remedy.
"""

from collections.abc import Callable
from typing import Final, NamedTuple

from games.filters import (
    FindFilter,
    GameFilter,
    filter_query_context_for_library,
    filter_queryset_for_library,
)
from games.models import UserLibrary
from games.reads.calendar import calendar_today
from games.reads.copy_figures import copy_counts
from games.reads.play_figures import (
    distinct_days,
    first_play,
    last_play,
)
from games.reads.player_sessions import readable_sessions
from games.reads.playtime import (
    played_years,
    playtime_by_month,
    playtime_by_platform,
    total_playtime,
)
from games.reads.purchase_figures import purchase_figures
from games.reads.purchases import purchase_list_rows
from games.reads.session_figures import (
    highest_average_game,
    longest_session,
    most_sessions_game,
    session_count,
)
from games.sorting import PURCHASE_DEFAULT_SORT, PURCHASE_SORTS, apply_sort
from games.views.game import games_for_list

type ReadName = str

#: The list's page, at the default page size.
PAGE_ROWS = 25


class NamedRead(NamedTuple):
    name: ReadName
    execute: Callable[[UserLibrary], object]


def _session_page(library: UserLibrary) -> object:
    return list(readable_sessions(library).order_by("-sort_instant", "-id")[:PAGE_ROWS])


def _game_playtime_sort(library: UserLibrary) -> object:
    sort = games_for_list(
        library, game_filter=None, find=FindFilter(sort="playtime")
    ).sort
    return list(sort.queryset[:PAGE_ROWS])


def _stats_totals(library: UserLibrary) -> object:
    return (
        total_playtime(library).total,
        session_count(library, None),
        distinct_days(library, None),
    )


def _stats_by_platform(library: UserLibrary) -> object:
    return playtime_by_platform(library)


def _stats_by_month(library: UserLibrary) -> object:
    """The latest played year; this year where none was."""
    years = played_years(library)
    year = max(years) if years else calendar_today(library).year
    return playtime_by_month(library, year=year)


def _stats_superlatives(library: UserLibrary) -> object:
    return (
        longest_session(library, None),
        most_sessions_game(library, None),
        highest_average_game(library, None),
        first_play(library, None),
        last_play(library, None),
    )


def _purchase_page(library: UserLibrary) -> object:
    sort = apply_sort(
        purchase_list_rows(library),
        FindFilter(),
        PURCHASE_SORTS,
        PURCHASE_DEFAULT_SORT,
    )
    return list(sort.queryset[:PAGE_ROWS])


def _stats_purchases(library: UserLibrary) -> object:
    return purchase_figures(library, None)


def _stats_copies(library: UserLibrary) -> object:
    return copy_counts(library, None)


def _game_price_total(library: UserLibrary) -> object:
    games = filter_queryset_for_library("game", library)
    over = GameFilter.where(purchase_price_total__gt=0)
    context = filter_query_context_for_library(library)
    return list(games.filter(over.to_q(context))[:PAGE_ROWS])


READS: Final[tuple[NamedRead, ...]] = (
    NamedRead("session_page", _session_page),
    NamedRead("game_playtime_sort", _game_playtime_sort),
    NamedRead("stats_totals", _stats_totals),
    NamedRead("stats_by_platform", _stats_by_platform),
    NamedRead("stats_by_month", _stats_by_month),
    NamedRead("stats_superlatives", _stats_superlatives),
    NamedRead("purchase_page", _purchase_page),
    NamedRead("stats_purchases", _stats_purchases),
    NamedRead("stats_copies", _stats_copies),
    NamedRead("game_price_total", _game_price_total),
)
