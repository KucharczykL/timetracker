"""What a completion answers, for the statistics and the lists.

One object per scope, so a statistic and the link it carries
compile one predicate. The interval handler states three
parts, and two of them answer differently for an open
bound.
"""

from django.db.models import Exists, F, Max, Min, OuterRef, QuerySet, Subquery

from games.filters import PlaythroughFilter, filter_query_context_for_library
from games.models import Playthrough, UserLibrary
from games.reads.playthrough_runs import library_runs

#: A year, or None for all-time.
type YearScope = int | None


def completed_in_scope(year: YearScope) -> PlaythroughFilter:
    """The filter a scope states."""
    if year is None:
        return PlaythroughFilter.where(is_completed=True)
    return PlaythroughFilter.where(
        completed__between=(f"{year}-01-01", f"{year}-12-31")
    )


def completed_runs(library: UserLibrary, year: YearScope) -> QuerySet[Playthrough]:
    """The live ordinary runs a completion names."""
    context = filter_query_context_for_library(library)
    return library_runs(library).filter(completed_in_scope(year).to_q(context))


def _runs_of_the_purchase(
    library: UserLibrary, year: YearScope
) -> QuerySet[Playthrough]:
    """Those runs, correlated to the Purchase."""
    return completed_runs(library, year).filter(
        player_game__game__purchases=OuterRef("pk")
    )


def completion_exists(library: UserLibrary, year: YearScope) -> Exists:
    """Whether a Purchase names a completed game."""
    return Exists(_runs_of_the_purchase(library, year))


def completion_day(library: UserLibrary, year: YearScope) -> Subquery:
    """The day a Purchase reports in scope.

    A year reports its earliest completion, so the table
    leads with the day it prints. All-time reports the
    latest; no all-time table shows it today.
    """
    reducer = Max("completed_lower") if year is None else Min("completed_lower")
    return Subquery(
        _runs_of_the_purchase(library, year)
        .values("player_game__game__purchases")
        .annotate(day=reducer)
        .values("day")[:1]
    )


#: A lookup path from the outer row to its runs.
type RunPath = str

PURCHASE_RUNS: RunPath = "player_game__game__purchases"
GAME_RUNS: RunPath = "player_game__game"


def ranked_completions(library: UserLibrary, path: RunPath) -> QuerySet[Playthrough]:
    """The row's completed runs, reported one first.

    The latest finish leads. A tie on the lower bound goes to
    the narrower interval, so the more precise of two values
    that start on one day is reported. The last key is the
    identity, so the answer never varies.
    """
    return (
        completed_runs(library, None)
        .filter(**{path: OuterRef("pk")})
        .order_by(
            F("completed_lower").desc(nulls_last=True),
            F("completed_upper").asc(nulls_last=True),
            "-pk",
        )
    )


def reported_completion(library: UserLibrary, path: RunPath) -> Subquery:
    """The value the reported run states."""
    return Subquery(ranked_completions(library, path).values("completed")[:1])


def reported_completion_day(library: UserLibrary, path: RunPath) -> Subquery:
    """The day the reported run is ordered by."""
    return Subquery(ranked_completions(library, path).values("completed_lower")[:1])
