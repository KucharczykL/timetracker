"""The populations the session organizer starts from.

A builder is public because the Library page gives the same
object to `filter_url`: the count and its link compile one
predicate. Counting through a private filter would let them drift.
"""

from typing import NamedTuple

from common.criteria import BoolCriterion, ChoiceCriterion, Modifier
from games.filters import PlayerSessionFilter, filter_query_context_for_library
from games.models import PlaythroughKind, UserLibrary
from games.reads.player_sessions import shown_sessions


class OrganizationCounts(NamedTuple):
    """How many sessions each question answers."""

    bucket: int
    before_start: int


def bucket_sessions_filter() -> PlayerSessionFilter:
    """The sessions the importer left in a game's bucket."""
    return PlayerSessionFilter(
        playthrough_kind=ChoiceCriterion(
            value=[PlaythroughKind.IMPORTED_HISTORY.value],
            modifier=Modifier.INCLUDES,
        )
    )


def before_start_filter() -> PlayerSessionFilter:
    """The sessions dated before their run's start."""
    return PlayerSessionFilter(before_playthrough_start=BoolCriterion(value=True))


def organization_counts(library: UserLibrary) -> OrganizationCounts:
    """Count both populations, each through its builder."""
    context = filter_query_context_for_library(library)
    sessions = shown_sessions(library)
    return OrganizationCounts(
        bucket=sessions.filter(bucket_sessions_filter().to_q(context)).count(),
        before_start=sessions.filter(before_start_filter().to_q(context)).count(),
    )
