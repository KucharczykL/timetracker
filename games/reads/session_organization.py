"""The populations the session organizer starts from.

A builder is public because the Library page gives the same
object to `filter_url`: the count and its link compile one
predicate. Counting through a private filter would let them drift.
"""

from typing import NamedTuple

from common.criteria import BoolCriterion, ChoiceCriterion, Modifier
from games.filters import PlayerSessionFilter, filter_query_context_for_library
from games.models import PlaythroughKind, UserLibrary
from games.reads.player_sessions import library_sessions


class OrganizationCounts(NamedTuple):
    """How many sessions each question answers."""

    bucket: int
    outside: int


def bucket_sessions_filter() -> PlayerSessionFilter:
    """The sessions the importer left in a game's bucket."""
    return PlayerSessionFilter(
        playthrough_kind=ChoiceCriterion(
            value=[PlaythroughKind.IMPORTED_HISTORY.value],
            modifier=Modifier.INCLUDES,
        )
    )


def outside_dates_filter() -> PlayerSessionFilter:
    """The sessions whose day their run's own dates do not cover."""
    return PlayerSessionFilter(outside_playthrough_dates=BoolCriterion(value=True))


def organization_counts(library: UserLibrary) -> OrganizationCounts:
    """Count both populations, each through its builder."""
    context = filter_query_context_for_library(library)
    sessions = library_sessions(library)
    return OrganizationCounts(
        bucket=sessions.filter(bucket_sessions_filter().to_q(context)).count(),
        outside=sessions.filter(outside_dates_filter().to_q(context)).count(),
    )
