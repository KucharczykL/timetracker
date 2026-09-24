"""What leaves the library with a game.

Each count is a correlated subquery scoped on the library, never a
join: a join over sessions and purchases multiplies one by the other.
A shared catalog game's reverse accessors reach every library that
ever wrote against it, which is why none of them is read here.
"""

from typing import NamedTuple

from django.db.models import (
    F,
    Func,
    IntegerField,
    OuterRef,
    QuerySet,
    Subquery,
    Value,
)
from django.db.models.functions import Coalesce

from games.models import Game, Purchase, UserLibrary
from games.reads.player_sessions import library_sessions
from games.reads.playthrough_runs import library_runs

#: The annotations `with_departures` adds.
SESSIONS = "departing_sessions"
PURCHASES = "departing_purchases"
RUNS = "departing_runs"


class Departures(NamedTuple):
    """One game's counts, as its confirmation states them."""

    sessions: int
    purchases: int
    runs: int


def counted(rows: QuerySet) -> Coalesce:
    """COUNT without GROUP BY: `Func` is no aggregate to Django."""
    return Coalesce(
        Subquery(
            rows.order_by()
            .annotate(count=Func(F("pk"), function="COUNT"))
            .values("count"),
            output_field=IntegerField(),
        ),
        Value(0),
    )


def with_departures(games: QuerySet[Game], library: UserLibrary) -> QuerySet[Game]:
    """Each game with what leaves beside it.

    Sessions through `library_sessions`, purchases as Game detail
    counts them, runs live and ordinary, all on the library.
    """
    return games.annotate(
        **{
            SESSIONS: counted(
                library_sessions(library).filter(
                    playthrough__player_game__game=OuterRef("pk")
                )
            ),
            PURCHASES: counted(
                Purchase.objects.for_library(library).filter(games=OuterRef("pk"))
            ),
            RUNS: counted(
                library_runs(library).filter(player_game__game=OuterRef("pk"))
            ),
        }
    )


def departures_of(game: Game) -> Departures:
    """The counts one annotated game carries."""
    return Departures(
        sessions=getattr(game, SESSIONS),
        purchases=getattr(game, PURCHASES),
        runs=getattr(game, RUNS),
    )


def game_departures(library: UserLibrary, game: Game) -> Departures:
    """One game's counts, read the way the batch reads them."""
    return departures_of(
        with_departures(Game.objects.filter(pk=game.pk), library).get()
    )
