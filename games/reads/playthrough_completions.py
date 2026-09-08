"""What a completion answers, for the statistics.

One object per scope, so a statistic and the link it carries
compile one predicate. The interval handler states three
parts, and restating two of them would answer differently
for an open bound.
"""

from django.db.models import Exists, Max, Min, OuterRef, QuerySet, Subquery

from games.filters import PlaythroughFilter, filter_query_context_for_library
from games.models import Playthrough, UserLibrary
from games.reads.playthrough_runs import library_runs

#: A calendar year, or None for every year at once.
type YearScope = int | None


def completed_in_scope(year: YearScope) -> PlaythroughFilter:
    """The filter a scope states.

    All-time reads the act, not the day. A year reads the
    interval the endpoint states, which overlaps.
    """
    if year is None:
        return PlaythroughFilter.where(is_completed=True)
    return PlaythroughFilter.where(
        completed__between=(f"{year}-01-01", f"{year}-12-31")
    )


def completed_runs(library: UserLibrary, year: YearScope) -> QuerySet[Playthrough]:
    """The live ordinary runs a completion in scope names."""
    context = filter_query_context_for_library(library)
    return library_runs(library).filter(completed_in_scope(year).to_q(context))


def _runs_of_the_purchase(
    library: UserLibrary, year: YearScope
) -> QuerySet[Playthrough]:
    """Those runs, correlated to the Purchase being read."""
    return completed_runs(library, year).filter(
        player_game__game__purchases=OuterRef("pk")
    )


def completion_exists(library: UserLibrary, year: YearScope) -> Exists:
    """Whether a Purchase names a game completed in scope."""
    return Exists(_runs_of_the_purchase(library, year))


def completion_day(library: UserLibrary, year: YearScope) -> Subquery:
    """The day a Purchase reports for its completion in scope.

    A year reports its earliest completion and all-time its
    latest, so each table reports the finish its own order
    leads with. The day is the earliest one the value names.
    """
    reducer = Max("completed_lower") if year is None else Min("completed_lower")
    return Subquery(
        _runs_of_the_purchase(library, year)
        .values("player_game__game__purchases")
        .annotate(day=reducer)
        .values("day")[:1]
    )
