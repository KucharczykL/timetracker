"""Every playtime figure: sessions plus historical records."""

from collections.abc import Iterable, Sequence
from datetime import date, timedelta
from typing import NamedTuple
from uuid import UUID

from django.db.models import DurationField, OuterRef, Q, Subquery, Sum
from django.db.models.functions import Coalesce, NullIf, TruncMonth

from games.filters import PlayerSessionFilter, filter_query_context_for_library
from games.models import Game, GameQuerySet, PlayerSessionQuerySet, UserLibrary
from games.reads.days import DayInterval
from games.reads.historical_playtime import (
    game_historical_playtime,
    historical_by_month,
    historical_by_platform,
    historical_summed_by_game,
    historical_total,
    historical_totals,
    historical_years,
)
from games.reads.player_sessions import GAME, library_sessions
from games.reads.playthrough_completions import YearScope
from games.reads.sums import (
    ZERO,
    Playtime,
    PlaytimeBreakdown,
    PlaytimeSum,
    UnscopedPlaytimeRead,
    UnscopedSum,
    zero_when_null,
)

__all__ = [
    "GameByPlaytime",
    "MonthPlaytime",
    "PlatformPlaytime",
    "PlaytimeBreakdown",
    "UnscopedPlaytimeRead",
    "game_playtime",
    "game_playtime_between",
    "game_tracked_between",
    "games_by_playtime",
    "games_by_playtime_queryset",
    "played_years",
    "playtime_between",
    "playtime_between_each",
    "playtime_by_game",
    "playtime_by_month",
    "playtime_by_platform",
    "playtime_matching",
    "playtime_sort_key",
    "total_playtime",
    "tracked_summed_by_game",
    "tracked_summed_by_game_matching",
]

PLATFORM = f"{GAME}__platform"

#: None is the unspecified-platform bucket.
type PlatformId = UUID | None
type PlatformName = str | None
type KeyedPlaytime[Key] = tuple[Key, timedelta]
#: Total down, then name, id; None last.
type PlatformOrder = tuple[timedelta, bool, str, bool, UUID]


class PlatformPlaytime(NamedTuple):
    platform_id: PlatformId
    platform_name: PlatformName
    playtime: PlaytimeBreakdown


class MonthPlaytime(NamedTuple):
    #: The first day of the month.
    month: date
    playtime: PlaytimeBreakdown


class GameByPlaytime(NamedTuple):
    game: Game
    playtime: PlaytimeBreakdown


def _year_days(year: YearScope) -> DayInterval | None:
    return None if year is None else DayInterval.year(year)


def _on_days(days: DayInterval) -> Q:
    return Q(effective_day__range=(days.first, days.last))


def _sessions(
    library: UserLibrary, within: DayInterval | None = None
) -> PlayerSessionQuerySet:
    """Counted sessions, narrowed to days."""
    sessions = library_sessions(library)
    return sessions if within is None else sessions.filter(_on_days(within))


def _total(sessions: PlayerSessionQuerySet) -> timedelta:
    return sessions.aggregate(total=Coalesce(Sum("effective_duration"), ZERO))["total"]


def _summed(sessions: PlayerSessionQuerySet) -> PlaytimeSum:
    return Subquery(
        sessions.filter(**{GAME: OuterRef("pk")})
        .values(GAME)
        .annotate(total=Sum("effective_duration"))
        .values("total"),
        output_field=DurationField(),
    )


def game_playtime(library: UserLibrary, game: Game) -> PlaytimeBreakdown:
    return PlaytimeBreakdown(
        tracked=_total(_sessions(library).filter(**{GAME: game})),
        historical=game_historical_playtime(library, game),
    )


def game_tracked_between(
    library: UserLibrary, game: Game, days: DayInterval
) -> timedelta:
    """One game's sessions over inclusive days."""
    return _total(_sessions(library, days).filter(**{GAME: game}))


def game_playtime_between(
    library: UserLibrary, game: Game, days: DayInterval
) -> PlaytimeBreakdown:
    """One game's playtime over inclusive days."""
    return PlaytimeBreakdown(
        tracked=game_tracked_between(library, game, days),
        historical=game_historical_playtime(library, game, within=days),
    )


def tracked_summed_by_game(
    library: UserLibrary | None, *, year: YearScope = None
) -> PlaytimeSum:
    """No library compiles, then refuses to execute."""
    if library is None:
        return UnscopedSum()
    return _summed(_sessions(library, _year_days(year)))


def tracked_summed_by_game_matching(
    library: UserLibrary,
    session_filter: PlayerSessionFilter,
    *,
    year: YearScope = None,
) -> PlaytimeSum:
    context = filter_query_context_for_library(library)
    return _summed(
        _sessions(library, _year_days(year)).filter(session_filter.to_q(context))
    )


def playtime_by_game(
    library: UserLibrary | None, *, year: YearScope = None
) -> Playtime:
    """Each game's playtime, zero when unplayed."""
    tracked = zero_when_null(tracked_summed_by_game(library, year=year))
    historical = zero_when_null(
        historical_summed_by_game(library, within=_year_days(year))
    )
    return Playtime(tracked + historical)


def games_by_playtime_queryset(
    library: UserLibrary, *, year: YearScope = None
) -> GameQuerySet:
    """Every visible game that was played, most played first.

    Unexecuted, so a test reads its plan: each half compiles twice, once in
    the select list and once in the filter naming the annotation.
    """
    return (
        Game.objects.visible_to(library)
        .annotate(total_playtime=playtime_by_game(library, year=year))
        .filter(total_playtime__gt=timedelta(0))
        #: Ties need an order, or rows reshuffle.
        .order_by("-total_playtime", "sort_name", "name", "pk")
    )


def games_by_playtime(
    library: UserLibrary, *, year: YearScope = None, limit: int
) -> list[GameByPlaytime]:
    """The most played games, each beside the two sources that made it.

    The halves are a second query over the keys the ranking answers, not two
    more subqueries on the query ranking every played game. Each row carries
    the game that second query read, so no row states its total twice.

    The caller states the cap, and counting the rest is a third query that
    ranks every played game again.
    """
    ranked = list(games_by_playtime_queryset(library, year=year)[:limit])
    if not ranked:
        return []
    halves = {
        game.pk: game
        for game in Game.objects.visible_to(library)
        .filter(pk__in=[game.pk for game in ranked])
        .annotate(
            tracked=zero_when_null(tracked_summed_by_game(library, year=year)),
            historical=zero_when_null(
                historical_summed_by_game(library, within=_year_days(year))
            ),
        )
    }
    rows = []
    for game in ranked:
        counted = halves.get(game.pk)
        #: A game removed between the two reads left the library, so it
        #: leaves the card. The ranking states the order, the halves the row.
        if counted is None:
            continue
        rows.append(
            GameByPlaytime(
                counted,
                PlaytimeBreakdown(
                    tracked=counted.tracked, historical=counted.historical
                ),
            )
        )
    return rows


def playtime_sort_key(library: UserLibrary) -> PlaytimeSum:
    """NULL without playtime; `apply_sort` orders it last.

    A running session alone sorts as unplayed.
    Telling the two apart runs each subquery twice.
    """
    return NullIf(playtime_by_game(library), ZERO, output_field=DurationField())


def playtime_matching(
    library: UserLibrary, session_filter: PlayerSessionFilter
) -> PlaytimeSum:
    """Matching sessions' sum; NULL when none match."""
    return tracked_summed_by_game_matching(library, session_filter)


def total_playtime(
    library: UserLibrary, *, year: YearScope = None
) -> PlaytimeBreakdown:
    within = _year_days(year)
    return PlaytimeBreakdown(
        tracked=_total(_sessions(library, within)),
        historical=historical_total(library, within=within),
    )


def playtime_between_each(
    library: UserLibrary, windows: Sequence[DayInterval]
) -> list[PlaytimeBreakdown]:
    """One figure per window, in two queries."""
    if not windows:
        return []
    tracked = library_sessions(library).aggregate(
        **{
            f"window_{index}": Coalesce(
                Sum("effective_duration", filter=_on_days(days)), ZERO
            )
            for index, days in enumerate(windows)
        }
    )
    historical = historical_totals(library, windows)
    return [
        PlaytimeBreakdown(tracked[f"window_{index}"], historical[index])
        for index in range(len(windows))
    ]


def playtime_between(library: UserLibrary, days: DayInterval) -> PlaytimeBreakdown:
    return playtime_between_each(library, [days])[0]


def _merged[Key](
    tracked: Iterable[KeyedPlaytime[Key]],
    historical: Iterable[KeyedPlaytime[Key]],
) -> dict[Key, PlaytimeBreakdown]:
    """Both sources per key; repeats refuse."""
    tracked_by_key: dict[Key, timedelta] = {}
    historical_by_key: dict[Key, timedelta] = {}
    for by_key, rows in ((tracked_by_key, tracked), (historical_by_key, historical)):
        for key, playtime in rows:
            if key in by_key:
                raise ValueError(f"{key!r} was summed twice in one source")
            by_key[key] = playtime
    return {
        key: PlaytimeBreakdown(
            tracked_by_key.get(key, timedelta(0)),
            historical_by_key.get(key, timedelta(0)),
        )
        for key in tracked_by_key.keys() | historical_by_key.keys()
    }


def _platform_order(row: PlatformPlaytime) -> PlatformOrder:
    """PostgreSQL's order: total descending, None last."""
    return (
        -row.playtime.total,
        row.platform_name is None,
        row.platform_name or "",
        row.platform_id is None,
        row.platform_id or UUID(int=0),
    )


def playtime_by_platform(
    library: UserLibrary, *, year: YearScope = None
) -> list[PlatformPlaytime]:
    within = _year_days(year)
    #: By id: names may differ between reads.
    names: dict[PlatformId, PlatformName] = {}
    tracked: list[KeyedPlaytime[PlatformId]] = []
    for platform_id, name, playtime in (
        _sessions(library, within)
        .values(PLATFORM, f"{PLATFORM}__name")
        .annotate(playtime=Sum("effective_duration"))
        .order_by()
        .values_list(PLATFORM, f"{PLATFORM}__name", "playtime")
    ):
        names[platform_id] = name
        tracked.append((platform_id, playtime))
    historical: list[KeyedPlaytime[PlatformId]] = []
    for row in historical_by_platform(library, within=within):
        names.setdefault(row.platform_id, row.platform_name)
        historical.append((row.platform_id, row.playtime))
    rows = [
        PlatformPlaytime(platform_id, names[platform_id], playtime)
        for platform_id, playtime in _merged(tracked, historical).items()
    ]
    return sorted(rows, key=_platform_order)


def playtime_by_month(library: UserLibrary, *, year: int) -> list[MonthPlaytime]:
    tracked: Iterable[KeyedPlaytime[date]] = (
        _sessions(library, DayInterval.year(year))
        .annotate(month=TruncMonth("effective_day"))
        .values("month")
        .annotate(playtime=Sum("effective_duration"))
        .order_by()
        .values_list("month", "playtime")
    )
    merged = _merged(
        tracked,
        ((row.month, row.playtime) for row in historical_by_month(library, year=year)),
    )
    return [MonthPlaytime(month, merged[month]) for month in sorted(merged)]


def played_years(library: UserLibrary) -> list[int]:
    tracked = {day.year for day in _sessions(library).dates("effective_day", "year")}
    return sorted(tracked | set(historical_years(library)))
