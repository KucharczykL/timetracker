"""Filter-link builders for the stats page (issue #65).

Each function returns a filter object describing exactly the records behind a
stats row or count; `stats_content` wraps them with `filter_url()` to link to the
matching list view. Keeping these as pure functions (no HTTP, no rendering) lets
the parity tests assert each builder's queryset count equals the stat it links
from.

Scope: `year` is an int for a calendar year, or the "Alltime" sentinel (or any
non-int) for all-time — matching `StatsData["year"]`. For all-time the date
bounds are omitted, so the links cover every record.
"""

from calendar import monthrange

from common.criteria import (
    BoolCriterion,
    ChoiceCriterion,
    DateCriterion,
    IntCriterion,
    Modifier,
    MultiCriterion,
)
from games.filters import (
    GameFilter,
    PlayEventFilter,
    PurchaseFilter,
    SessionFilter,
)
from games.models import Game, Purchase


def _is_year(year) -> bool:
    return isinstance(year, int)


def _year_range(year: int) -> tuple[str, str]:
    return (f"{year}-01-01", f"{year}-12-31")


def _session_bounds(year) -> dict:
    """`where()` kwargs scoping sessions to the year (empty for all-time)."""
    if not _is_year(year):
        return {}
    return {"timestamp_start__between": _year_range(year)}


def _purchase_bounds(year) -> dict:
    if not _is_year(year):
        return {}
    return {"date_purchased__between": _year_range(year)}


# ── Sessions ─────────────────────────────────────────────────────────────────


def all_sessions(year) -> SessionFilter:
    return SessionFilter.where(**_session_bounds(year))


def sessions_for_game(game_id: int, year, label: str = "") -> SessionFilter:
    # Carry the game name as a display label so the filter bar renders a named
    # pill on landing (#224); falls back to a bare id when no label is given.
    session_filter = SessionFilter.where(**_session_bounds(year))
    session_filter.game = MultiCriterion(
        value=[game_id], labels={game_id: label} if label else {}
    )
    return session_filter


def sessions_for_platform(
    platform_id: int | None, year, label: str = ""
) -> SessionFilter:
    # See sessions_for_game: the platform name rides along as a display label so
    # the session bar's (cross-entity) platform pill renders a name, not an id.
    session_filter = SessionFilter.where(**_session_bounds(year))
    if platform_id is None:
        # The stats "Unspecified" bucket groups by the game__platform LEFT JOIN,
        # so it holds both sessions of platformless games AND sessions with no
        # game at all. The cross-entity game_filter compiles to game_id__in
        # (subquery) — which a NULL game_id never matches — so the game-less
        # half needs its own IS_NULL arm, OR-composed under a single AND child
        # (OR at the top node would swallow the year bounds).
        session_filter.AND = [
            SessionFilter(
                OR=[
                    SessionFilter(game=MultiCriterion(modifier=Modifier.IS_NULL)),
                    SessionFilter(
                        game_filter=GameFilter(
                            platform=MultiCriterion(modifier=Modifier.IS_NULL)
                        )
                    ),
                ]
            )
        ]
        return session_filter
    session_filter.game_filter = GameFilter(
        platform=MultiCriterion(
            value=[platform_id], labels={platform_id: label} if label else {}
        )
    )
    return session_filter


def games_in_month(year: int, month: int) -> GameFilter:
    last_day = monthrange(year, month)[1]
    start = f"{year}-{month:02d}-01"
    end = f"{year}-{month:02d}-{last_day:02d}"
    return GameFilter(
        session_filter=all_sessions(year).where(timestamp_start__between=(start, end))
    )


# ── Games ────────────────────────────────────────────────────────────────────


def games_played(year) -> GameFilter:
    """Games with at least one session in scope (matches `total_games`)."""
    return GameFilter(session_filter=all_sessions(year))


# ── Purchases ────────────────────────────────────────────────────────────────


def purchases_total(year) -> PurchaseFilter:
    return PurchaseFilter.where(**_purchase_bounds(year))


def purchases_refunded(year) -> PurchaseFilter:
    return PurchaseFilter.where(is_refunded=True, **_purchase_bounds(year))


# ── Tier 2: finished / dropped / unfinished / backlog (uses #67) ─────────────
#
# These mirror the M2M-traversing queries in `stats_data.py`. The project models
# multi-item orders as separate single-game purchases, so on that (dominant) data
# the filter system's id-set semantics match the stats queries exactly; the only
# divergence is unsplittable multi-game bundles, which the stats queries
# themselves count inconsistently. Parity is verified per category in tests.


def _ended_in_scope(year) -> PlayEventFilter:
    """A game's finish: a playevent whose `ended` falls in scope (any, all-time)."""
    if _is_year(year):
        return PlayEventFilter.where(ended__between=_year_range(year))
    return PlayEventFilter.where(ended__notnull=True)


def _not_finished_game(year, excluded_statuses: list) -> GameFilter:
    """Games that are not finished in scope: status not in `excluded_statuses`
    (always includes FINISHED) and no finishing playevent in scope.

    Mirrors `not_finished_q = ~Q(status=FINISHED) & ~ended_q` plus the extra
    status exclusions some categories add."""
    game_filter = GameFilter(
        status=ChoiceCriterion(value=excluded_statuses, modifier=Modifier.EXCLUDES)
    )
    game_filter.NOT = [GameFilter(playevent_filter=_ended_in_scope(year))]
    return game_filter


def purchases_finished(year) -> PurchaseFilter:
    """Purchases whose game is finished (in scope)."""
    if _is_year(year):
        return PurchaseFilter(
            game_filter=GameFilter(playevent_filter=_ended_in_scope(year))
        )
    # All-time `.finished()`: game status FINISHED *or* any ended playevent.
    game_filter = GameFilter(status=ChoiceCriterion(value=[Game.Status.FINISHED]))
    game_filter.OR = [GameFilter(playevent_filter=_ended_in_scope(year))]
    return PurchaseFilter(game_filter=game_filter)


def purchases_finished_released(year) -> PurchaseFilter:
    """Finished-in-scope purchases whose game was released that year."""
    if not _is_year(year):
        return purchases_finished(year)
    game_filter = GameFilter(
        year_released=IntCriterion(value=year, modifier=Modifier.EQUALS),
        playevent_filter=_ended_in_scope(year),
    )
    return PurchaseFilter(game_filter=game_filter)


def purchases_bought_and_finished(year) -> PurchaseFilter:
    """Not-refunded purchases bought in scope whose game finished in scope."""
    purchase_filter = PurchaseFilter.where(is_refunded=False, **_purchase_bounds(year))
    purchase_filter.game_filter = GameFilter(playevent_filter=_ended_in_scope(year))
    return purchase_filter


def _abandoned_or_refunded() -> PurchaseFilter:
    purchase_filter = PurchaseFilter(
        game_filter=GameFilter(status=ChoiceCriterion(value=[Game.Status.ABANDONED]))
    )
    purchase_filter.OR = [PurchaseFilter(is_refunded=BoolCriterion(value=True))]
    return purchase_filter


def purchases_dropped(year) -> PurchaseFilter:
    purchase_filter = PurchaseFilter.where(
        infinite=False,
        type=[Purchase.GAME, Purchase.DLC],
        **_purchase_bounds(year),
    )
    purchase_filter.game_filter = _not_finished_game(year, [Game.Status.FINISHED])
    purchase_filter.AND = [_abandoned_or_refunded()]
    return purchase_filter


def purchases_unfinished(year) -> PurchaseFilter:
    purchase_filter = PurchaseFilter.where(
        is_refunded=False,
        infinite=False,
        type=[Purchase.GAME, Purchase.DLC],
        **_purchase_bounds(year),
    )
    purchase_filter.game_filter = _not_finished_game(
        year,
        [Game.Status.FINISHED, Game.Status.RETIRED, Game.Status.ABANDONED],
    )
    return purchase_filter


def purchases_backlog_decrease(year) -> PurchaseFilter:
    """Per-year: bought before the year, game finished in the year. All-time:
    equals the all-time finished count (matches `stats_data.py`)."""
    if not _is_year(year):
        return purchases_finished(year)
    purchase_filter = PurchaseFilter(
        date_purchased=DateCriterion(value=f"{year}-01-01", modifier=Modifier.LESS_THAN)
    )
    purchase_filter.game_filter = GameFilter(
        status=ChoiceCriterion(value=[Game.Status.FINISHED]),
        playevent_filter=_ended_in_scope(year),
    )
    return purchase_filter
