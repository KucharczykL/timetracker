"""The statistics' copy figures.

Live copies on a full Edition. Each figure states one
`LibraryEntryFilter`, which its link carries too. An
acquired day is in a year by containment; a completion
keeps overlap.
"""

from dataclasses import replace
from typing import NamedTuple

from django.db.models import (
    Count,
    DecimalField,
    OuterRef,
    QuerySet,
    Subquery,
    Sum,
)

from common.criteria import RelationMatch
from games.end_ways import EndWay
from games.filters import (
    GameFilter,
    HistoricalPlaytimeFilter,
    LibraryEntryFilter,
    PlayerSessionFilter,
    filter_query_context_for_library,
    filter_queryset_for_library,
)
from games.models import (
    DONE_STATUSES,
    EditionKind,
    EntryAccess,
    LibraryEntry,
    PlayerGameStatus,
    UserLibrary,
)
from games.reads.days import YearScope, year_range
from games.reads.playthrough_completions import completed_in_scope
from games.reads.purchases import library_purchases


def _copies(year: YearScope = None, **lookups) -> LibraryEntryFilter:
    """Full-Edition copies, acquired in scope."""
    if year is not None:
        lookups["acquired__within"] = year_range(year)
    return LibraryEntryFilter.where(edition_kind=[EditionKind.FULL], **lookups)


def _owned(year: YearScope = None, **lookups) -> LibraryEntryFilter:
    return _copies(year, access=[EntryAccess.OWNED], **lookups)


def _completion_in_scope(year: YearScope) -> GameFilter:
    return GameFilter(playthrough_filter=completed_in_scope(year))


def _finished_game(year: YearScope) -> GameFilter:
    """Completed in scope; all-time, done too."""
    if year is not None:
        return _completion_in_scope(year)
    return GameFilter(
        OR=[
            GameFilter.where(status=list(DONE_STATUSES)),
            _completion_in_scope(None),
        ]
    )


def _both(*members: GameFilter) -> GameFilter:
    return GameFilter(AND=list(members))


def _not_finished_game(year: YearScope, *statuses: PlayerGameStatus) -> GameFilter:
    """No done status, no completion in scope."""
    return _both(
        GameFilter.where(status__exclude=[*DONE_STATUSES, *statuses]),
        GameFilter(
            playthrough_filter=replace(
                completed_in_scope(year), match=RelationMatch.NONE
            )
        ),
    )


def owned_held(year: YearScope) -> LibraryEntryFilter:
    """Unfinished's denominator."""
    return _owned(year, is_ended=False)


def owned(year: YearScope) -> LibraryEntryFilter:
    """Dropped's denominator."""
    return _owned(year)


def unfinished_copies(year: YearScope) -> LibraryEntryFilter:
    copies = owned_held(year)
    copies.game_filter = _both(
        _not_finished_game(year, PlayerGameStatus.ABANDONED),
        GameFilter.where(excluded_from_unfinished=False),
    )
    return copies


def dropped_copies(year: YearScope) -> LibraryEntryFilter:
    """Abandoned, or ended by a refund."""
    copies = owned(year)
    copies.game_filter = _both(
        _not_finished_game(year), GameFilter.where(excluded_from_dropped=False)
    )
    copies.AND = [
        LibraryEntryFilter(
            game_filter=GameFilter.where(status=[PlayerGameStatus.ABANDONED]),
            OR=[LibraryEntryFilter.where(access_end_way=[EndWay.REFUNDED])],
        )
    ]
    return copies


def backlog_decrease_copies(year: YearScope) -> LibraryEntryFilter:
    """Owned copies whose game was finished."""
    if year is None:
        copies = owned(None)
        copies.game_filter = _finished_game(None)
        return copies
    copies = _copies(None, access=[EntryAccess.OWNED], acquired__lt=f"{year}-01-01")
    copies.game_filter = _both(
        GameFilter.where(status=list(DONE_STATUSES)), _completion_in_scope(year)
    )
    return copies


def finished_copies(year: YearScope) -> LibraryEntryFilter:
    copies = _copies()
    copies.game_filter = _finished_game(year)
    return copies


def finished_released_copies(year: YearScope) -> LibraryEntryFilter:
    """Finished; for a year, released that year."""
    copies = finished_copies(year)
    if year is not None:
        copies.game_filter = _both(
            _finished_game(year), GameFilter.where(year_released=year)
        )
    return copies


def bought_and_finished_copies(year: YearScope) -> LibraryEntryFilter:
    """Acquired in scope, not refunded, finished."""
    copies = _copies(year)
    copies.game_filter = _completion_in_scope(year)
    copies.NOT = [LibraryEntryFilter.where(access_end_way=[EndWay.REFUNDED])]
    return copies


def played_copies(year: YearScope) -> LibraryEntryFilter:
    """A session or record in scope."""
    sessions = PlayerSessionFilter.where(
        **({} if year is None else {"day__between": year_range(year)})
    )
    records = HistoricalPlaytimeFilter.where(
        **({} if year is None else {"when__within": year_range(year)})
    )
    played = GameFilter(
        OR=[
            GameFilter(session_filter=sessions),
            GameFilter(historical_playtime_filter=records),
        ]
    )
    copies = _copies()
    copies.game_filter = (
        played if year is None else _both(played, GameFilter.where(year_released=year))
    )
    return copies


def copies_matching(
    library: UserLibrary, entry_filter: LibraryEntryFilter
) -> QuerySet[LibraryEntry]:
    """The Library tab's base, narrowed."""
    context = filter_query_context_for_library(library)
    return filter_queryset_for_library("libraryentry", library).filter(
        entry_filter.to_q(context)
    )


class CopyCounts(NamedTuple):
    """One scope's copy figures and denominators."""

    unfinished: int
    owned_held: int
    dropped: int
    owned: int
    backlog_decrease: int
    finished_released: int
    played: int


def copy_counts(library: UserLibrary, year: YearScope) -> CopyCounts:
    """Every count, one statement, one context."""
    context = filter_query_context_for_library(library)
    statements = {
        "unfinished": unfinished_copies(year),
        "owned_held": owned_held(year),
        "dropped": dropped_copies(year),
        "owned": owned(year),
        "backlog_decrease": backlog_decrease_copies(year),
        "finished_released": finished_released_copies(year),
        "played": played_copies(year),
    }
    counts = filter_queryset_for_library("libraryentry", library).aggregate(
        **{
            name: Count("pk", filter=statement.to_q(context))
            for name, statement in statements.items()
        }
    )
    return CopyCounts(**counts)


def paid_for_copy(library: UserLibrary) -> Subquery:
    """The copy's unrefunded valuations, summed."""
    return Subquery(
        library_purchases(library)
        .annotated_for_filtering(library)
        .filter(entry=OuterRef("pk"), refund_recorded_at__isnull=True)
        .order_by()
        .values("entry")
        .annotate(total=Sum("valuation_amount"))
        .values("total"),
        output_field=DecimalField(max_digits=26, decimal_places=2),
    )
