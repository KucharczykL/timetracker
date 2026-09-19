"""Judge every statistics figure across a reclassification.

One rule a key; None is unattributed.
"""

from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import date, timedelta
from typing import NamedTuple, cast
from uuid import UUID

from django.db.models import QuerySet

from games.models import Game
from games.reads.playtime import (
    GameByPlaytime,
    MonthPlaytime,
    PlatformPlaytime,
    PlaytimeBreakdown,
)
from games.views.stats_data import STATS_SOURCES, StatsData, StatsKey

#: A year, or None for all-time.
type ScopeKey = int | None


class ScopeIdentities(NamedTuple):
    """The rows behind the session superlatives, before."""

    longest_session_id: UUID | None
    highest_count_game_id: UUID | None
    highest_average_game_id: UUID | None


class ConvertedRow(NamedTuple):
    session_id: UUID
    day: date
    game_id: UUID
    platform_id: UUID | None
    duration: timedelta


class Converted(NamedTuple):
    """The rows a scope saw converted."""

    rows: tuple[ConvertedRow, ...]

    def in_scope(self, year: ScopeKey) -> Converted:
        if year is None:
            return self
        return Converted(tuple(row for row in self.rows if row.day.year == year))

    @property
    def session_ids(self) -> frozenset[UUID]:
        return frozenset(row.session_id for row in self.rows)

    @property
    def game_ids(self) -> frozenset[UUID]:
        return frozenset(row.game_id for row in self.rows)


class Comparison(NamedTuple):
    """One key, both readings, the conversion."""

    key: StatsKey
    before: Mapping[StatsKey, object]
    after: Mapping[StatsKey, object]
    identities: ScopeIdentities
    converted: Converted

    @property
    def values(self) -> tuple[object, object]:
        return self.before[self.key], self.after[self.key]


class FigureChange(NamedTuple):
    key: StatsKey
    before: object
    after: object
    #: None: the read disagrees with the charter.
    attribution: str | None


#: The attribution, or None.
type Rule = Callable[[Comparison], str | None]

ZERO_DURATION = timedelta(0)
UNCHANGED = "unchanged"


def comparable(value: object) -> object:
    """A queryset compares as its ordered keys."""
    if isinstance(value, QuerySet):
        return list(value.values_list("pk", flat=True))
    return value


def _game_key(value: object) -> UUID | None:
    return None if value is None else cast("Game", value).pk


def _unchanged(comparison: Comparison) -> str | None:
    before, after = comparison.values
    return UNCHANGED if comparable(before) == comparable(after) else None


# ── Playtime: totals hold, halves move ──────────────────────────────────────

type BreakdownKey = object
type KeyedBreakdown = tuple[BreakdownKey, PlaytimeBreakdown]
type Breakdowns = Callable[[object], list[KeyedBreakdown]]
type RowKey = Callable[[ConvertedRow], BreakdownKey]


def _shifts(
    rows: Iterable[ConvertedRow], key_of: RowKey
) -> dict[BreakdownKey, timedelta]:
    shifted: dict[BreakdownKey, timedelta] = {}
    for row in rows:
        key = key_of(row)
        shifted[key] = shifted.get(key, ZERO_DURATION) + row.duration
    return shifted


def _breakdown_rule(breakdowns: Breakdowns, key_of: RowKey) -> Rule:
    def rule(comparison: Comparison) -> str | None:
        before, after = (breakdowns(value) for value in comparison.values)
        if [key for key, _ in before] != [key for key, _ in after]:
            return None
        shifted = _shifts(comparison.converted.rows, key_of)
        moved = ZERO_DURATION
        for (key, was), (_, now) in zip(before, after, strict=True):
            shift = shifted.get(key, ZERO_DURATION)
            if now.total != was.total or was.tracked - now.tracked != shift:
                return None
            moved += shift
        if moved == ZERO_DURATION:
            return UNCHANGED
        return f"{moved} moved from tracked to historical"

    return rule


def _one_total(value: object) -> list[KeyedBreakdown]:
    return [(None, cast("PlaytimeBreakdown", value))]


def _by_game(value: object) -> list[KeyedBreakdown]:
    return [(row.game.pk, row.playtime) for row in cast("list[GameByPlaytime]", value)]


def _by_platform(value: object) -> list[KeyedBreakdown]:
    return [
        (row.platform_id, row.playtime) for row in cast("list[PlatformPlaytime]", value)
    ]


def _by_month(value: object) -> list[KeyedBreakdown]:
    return [(row.month, row.playtime) for row in cast("list[MonthPlaytime]", value)]


def _month_of(row: ConvertedRow) -> date:
    return row.day.replace(day=1)


# ── Sessions: a record is no sitting ────────────────────────────────────────


def _session_count(comparison: Comparison) -> str | None:
    before, after = comparison.values
    fallen = cast("int", before) - cast("int", after)
    converted = len(comparison.converted.rows)
    if fallen != converted:
        return None
    return UNCHANGED if converted == 0 else f"{converted} row(s) converted"


def _longest_session(comparison: Comparison) -> str | None:
    if _unchanged(comparison):
        return UNCHANGED
    longest = comparison.identities.longest_session_id
    if longest in comparison.converted.session_ids:
        return f"the longest session before, {longest}, was converted"
    return None


def _highest_count(comparison: Comparison) -> str | None:
    if _unchanged(comparison):
        return UNCHANGED
    game = comparison.identities.highest_count_game_id
    if game in comparison.converted.game_ids:
        return f"the game with most sessions before, {game}, held a converted row"
    return None


def _highest_average(comparison: Comparison) -> str | None:
    """Taking a short row away raises averages."""
    if _unchanged(comparison):
        return UNCHANGED
    before = comparison.identities.highest_average_game_id
    after = _game_key(comparison.after["highest_session_average_game"])
    converted = comparison.converted.game_ids
    if before in converted:
        return f"the highest-average game before, {before}, held a converted row"
    if after in converted:
        return f"the highest-average game after, {after}, held a converted row"
    return None


# ── The two play-source flags ───────────────────────────────────────────────


def _from_record_flag(date_key: StatsKey, game_key: StatsKey) -> Rule:
    """Flips only on the play it named."""

    def rule(comparison: Comparison) -> str | None:
        before, after = comparison.values
        if before == after:
            return UNCHANGED
        if before or not after:
            return None
        named = (
            comparison.before[date_key],
            _game_key(comparison.before[game_key]),
        )
        for row in comparison.converted.rows:
            if (row.day, row.game_id) == named:
                return f"the play it named, session {row.session_id}, was converted"
        return None

    return rule


RULES: Mapping[StatsKey, Rule] = {
    "total_hours": _breakdown_rule(_one_total, lambda row: None),
    "games_by_playtime": _breakdown_rule(_by_game, lambda row: row.game_id),
    "total_playtime_per_platform": _breakdown_rule(
        _by_platform, lambda row: row.platform_id
    ),
    "month_playtimes": _breakdown_rule(_by_month, _month_of),
    "games_by_playtime_count": _unchanged,
    "unique_days": _unchanged,
    "unique_days_percent": _unchanged,
    "first_play_game": _unchanged,
    "first_play_date": _unchanged,
    "last_play_game": _unchanged,
    "last_play_date": _unchanged,
    "total_games": _unchanged,
    "total_year_games": _unchanged,
    "total_sessions": _session_count,
    "longest_session_time": _longest_session,
    "longest_session_game": _longest_session,
    "highest_session_count": _highest_count,
    "highest_session_count_game": _highest_count,
    "highest_session_average": _highest_average,
    "highest_session_average_game": _highest_average,
    "this_year_finished_this_year_count": _unchanged,
    "total_spent": _unchanged,
    "total_spent_currency": _unchanged,
    "spent_per_game": _unchanged,
    "all_purchased_this_year_count": _unchanged,
    "all_purchased_refunded_this_year": _unchanged,
    "all_purchased_refunded_this_year_count": _unchanged,
    "refunded_percent": _unchanged,
    "dropped_count": _unchanged,
    "dropped_percentage": _unchanged,
    "purchased_unfinished_count": _unchanged,
    "unfinished_purchases_percent": _unchanged,
    "backlog_decrease_count": _unchanged,
    "all_finished_this_year": _unchanged,
    "all_finished_this_year_count": _unchanged,
    "this_year_finished_this_year": _unchanged,
    "purchased_this_year_finished_this_year": _unchanged,
    "purchased_unfinished": _unchanged,
    "all_purchased_this_year": _unchanged,
    "year": _unchanged,
    "title": _unchanged,
    "stats_dropdown_year_range": _unchanged,
    "first_play_from_record": _from_record_flag("first_play_date", "first_play_game"),
    "last_play_from_record": _from_record_flag("last_play_date", "last_play_game"),
}


def judge_scope(
    before: StatsData,
    after: StatsData,
    identities: ScopeIdentities,
    converted: Converted,
) -> tuple[FigureChange, ...]:
    """Every change, and every refusal.

    Absent from both: skipped. From one: unattributed.
    """
    was = cast("Mapping[StatsKey, object]", before)
    now = cast("Mapping[StatsKey, object]", after)
    changes: list[FigureChange] = []
    for key in STATS_SOURCES:
        if key not in was and key not in now:
            continue
        if key not in was or key not in now:
            changes.append(FigureChange(key, was.get(key), now.get(key), None))
            continue
        comparison = Comparison(key, was, now, identities, converted)
        attribution = RULES[key](comparison)
        changed = comparable(was[key]) != comparable(now[key])
        if changed or attribution is None:
            changes.append(FigureChange(key, was[key], now[key], attribution))
    return tuple(changes)


def unattributed(changes: Sequence[FigureChange]) -> tuple[FigureChange, ...]:
    return tuple(change for change in changes if change.attribution is None)
