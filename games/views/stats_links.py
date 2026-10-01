"""Filter-link builders for the stats page (issue #65).

Each function returns a filter object describing exactly the records behind a
stats row or count; `stats_content` wraps them with `filter_url()` to link to the
matching list view. Keeping these as pure functions (no HTTP, no rendering) lets
the parity tests assert each builder's queryset count equals the stat it links
from.

Scope: `year` is an int for a calendar year, or the "Alltime" sentinel (or any
non-int) for all-time — matching `StatsData["year"]`. For all-time the date
bounds are omitted, so the links cover every record.

These objects carry row criteria, not authorization. List views must execute them
against a base queryset already scoped to ``request.user.library``; a stats link
must never restore a global model-manager fallback.
"""

from calendar import monthrange
from uuid import UUID

from common.criteria import (
    Modifier,
    UUIDMultiCriterion,
)
from games.filters import (
    GameFilter,
    HistoricalPlaytimeFilter,
    LibraryEntryFilter,
    PlayerSessionFilter,
    PurchaseFilter,
)
from games.reads import copy_figures, purchase_figures
from games.reads.days import YearScope


def _is_year(year) -> bool:
    return isinstance(year, int)


def _year_range(year: int) -> tuple[str, str]:
    return (f"{year}-01-01", f"{year}-12-31")


def _session_bounds(year) -> dict:
    """`where()` kwargs scoping sessions to the year (empty for all-time)."""
    if not _is_year(year):
        return {}
    return {"day__between": _year_range(year)}


def _record_bounds(year) -> dict:
    """`where()` kwargs scoping records by containment."""
    if not _is_year(year):
        return {}
    return {"when__within": _year_range(year)}


# ── Sessions ─────────────────────────────────────────────────────────────────


def all_sessions(year) -> PlayerSessionFilter:
    return PlayerSessionFilter.where(**_session_bounds(year))


def sessions_for_game(game_id: UUID, year, label: str = "") -> PlayerSessionFilter:
    # Carry the game name as a display label so the filter bar renders a named
    # pill on landing (#224); falls back to a bare id when no label is given.
    session_filter = PlayerSessionFilter.where(**_session_bounds(year))
    session_filter.game = UUIDMultiCriterion(
        value=[game_id], labels={game_id: label} if label else {}
    )
    return session_filter


def sessions_for_platform(
    platform_id: UUID | None, year, label: str = ""
) -> PlayerSessionFilter:
    # See sessions_for_game: the platform name rides along as a display label so
    # the session bar's (cross-entity) platform pill renders a name, not an id.
    session_filter = PlayerSessionFilter.where(**_session_bounds(year))
    if platform_id is None:
        # The stats "Unspecified" bucket groups by the game__platform LEFT JOIN,
        # which now means exactly sessions whose required Game is platformless.
        session_filter.game_filter = GameFilter(
            platform=UUIDMultiCriterion(modifier=Modifier.IS_NULL)
        )
        return session_filter
    session_filter.game_filter = GameFilter(
        platform=UUIDMultiCriterion(
            value=[platform_id], labels={platform_id: label} if label else {}
        )
    )
    return session_filter


def games_in_month(year: int, month: int) -> GameFilter:
    """A session or record that month."""
    last_day = monthrange(year, month)[1]
    start = f"{year}-{month:02d}-01"
    end = f"{year}-{month:02d}-{last_day:02d}"
    return GameFilter(
        OR=[
            GameFilter(
                session_filter=PlayerSessionFilter.where(day__between=(start, end))
            ).of_every_kind(),
            GameFilter(
                historical_playtime_filter=HistoricalPlaytimeFilter.where(
                    when__within=(start, end)
                )
            ).of_every_kind(),
        ]
    )


# ── Games ────────────────────────────────────────────────────────────────────


def all_records(year) -> HistoricalPlaytimeFilter:
    return HistoricalPlaytimeFilter.where(**_record_bounds(year))


def records_for_game(game_id: UUID, year, label: str = "") -> HistoricalPlaytimeFilter:
    """One game's records in scope, the game named as a pill."""
    record_filter = all_records(year)
    record_filter.game = UUIDMultiCriterion(
        value=[game_id], labels={game_id: label} if label else {}
    )
    return record_filter


def games_played(year) -> GameFilter:
    """A session or record in scope."""
    return GameFilter(
        OR=[
            GameFilter(session_filter=all_sessions(year)).of_every_kind(),
            GameFilter(historical_playtime_filter=all_records(year)).of_every_kind(),
        ]
    )


# ── Purchases ────────────────────────────────────────────────────────────────


def _scope(year) -> YearScope:
    return year if _is_year(year) else None


def purchases_total(year) -> PurchaseFilter:
    return purchase_figures.purchases_in_scope(_scope(year))


def purchases_refunded(year) -> PurchaseFilter:
    return purchase_figures.refunded_in_scope(_scope(year))


def purchases_unpriced(year) -> PurchaseFilter:
    return purchase_figures.unpriced_in_scope(_scope(year))


def purchases_unvalued(year) -> PurchaseFilter:
    return purchase_figures.unvalued_in_scope(_scope(year))


# ── Copies ───────────────────────────────────────────────────────────────────


def copies_unfinished(year) -> LibraryEntryFilter:
    return copy_figures.unfinished_copies(_scope(year))


def copies_dropped(year) -> LibraryEntryFilter:
    return copy_figures.dropped_copies(_scope(year))


def copies_backlog_decrease(year) -> LibraryEntryFilter:
    return copy_figures.backlog_decrease_copies(_scope(year))


def copies_finished(year) -> LibraryEntryFilter:
    return copy_figures.finished_copies(_scope(year))


def copies_finished_released(year) -> LibraryEntryFilter:
    return copy_figures.finished_released_copies(_scope(year))


def copies_bought_and_finished(year) -> LibraryEntryFilter:
    return copy_figures.bought_and_finished_copies(_scope(year))
