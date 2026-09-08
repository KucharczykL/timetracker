"""What a completion answers, for the statistics.

One object per scope, so a statistic and the link it carries
compile one predicate. The interval handler states three
parts, and two of them answer differently for an open
bound.
"""

from django.db.models import Exists, Max, Min, OuterRef, QuerySet, Subquery

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
