"""What a completion answers, for every reader.

One object per scope, so a statistic and the link it carries
compile one predicate. The interval handler states three
parts, and two of them answer differently for an open
bound.
"""

from django.db.models import Exists, F, Max, Min, OuterRef, QuerySet, Subquery

from games.filters import PlaythroughFilter, filter_query_context_for_library
from games.models import Playthrough, UserLibrary
from games.reads.days import YearScope
from games.reads.playthrough_runs import library_runs

#: A row's path to its runs.
type RunPath = str

PURCHASE_RUNS: RunPath = "player_game__entries__purchases"
ENTRY_RUNS: RunPath = "player_game__entries"
GAME_RUNS: RunPath = "player_game__game"


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


def _runs_of_the_row(
    library: UserLibrary, year: YearScope, path: RunPath
) -> QuerySet[Playthrough]:
    """Those runs, correlated to the row."""
    return completed_runs(library, year).filter(**{path: OuterRef("pk")})


def completion_exists(library: UserLibrary, year: YearScope, path: RunPath) -> Exists:
    """Whether the row names a completed game."""
    return Exists(_runs_of_the_row(library, year, path))


def completion_day(library: UserLibrary, year: YearScope, path: RunPath) -> Subquery:
    """The day the row reports in scope.

    A year reports its earliest completion, so the table
    leads with the day it prints. All-time reports the
    latest; no all-time table shows it today.
    """
    reducer = Max("completed_lower") if year is None else Min("completed_lower")
    return Subquery(
        _runs_of_the_row(library, year, path)
        .values(path)
        .annotate(day=reducer)
        .values("day")[:1]
    )


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
    """The value the reported run states.

    Null states two facts: no run, and a completion nobody
    dated. Pair it with `completion_exists` to tell them
    apart.
    """
    return Subquery(ranked_completions(library, path).values("completed")[:1])


def reported_completion_day(library: UserLibrary, path: RunPath) -> Subquery:
    """The reported run's `completed_lower`.

    Null states three facts: no run, a completion nobody
    dated, and a value with no lower bound. All three sort
    last, which is what this is for.
    """
    return Subquery(ranked_completions(library, path).values("completed_lower")[:1])
