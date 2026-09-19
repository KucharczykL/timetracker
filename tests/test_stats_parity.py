"""Statistics parity across a reclassification: the rules, the command."""

import uuid
from datetime import date, timedelta

import pytest

from games.models import Game
from games.reads.playtime import (
    GameByPlaytime,
    MonthPlaytime,
    PlatformPlaytime,
    PlaytimeBreakdown,
)
from games.stats_parity import (
    RULES,
    Converted,
    ConvertedRow,
    FigureChange,
    ScopeIdentities,
    judge_scope,
    unattributed,
)
from games.views.stats_data import STATS_SOURCES, StatsData

YEAR = 2025
A_DAY = date(YEAR, 3, 5)
NINE_HOURS = timedelta(hours=9)
ONE_HOUR = timedelta(hours=1)
ZERO = timedelta(0)

FIRST = Game(pk=uuid.uuid7(), name="Aa", sort_name="aa")
SECOND = Game(pk=uuid.uuid7(), name="Bb", sort_name="bb")
PLATFORM = uuid.uuid7()
LONGEST = uuid.uuid7()

NOBODY = ScopeIdentities(None, None, None)
NOTHING = Converted(())


def converted_row(
    *,
    session_id: uuid.UUID | None = None,
    day: date = A_DAY,
    game: Game = FIRST,
    platform_id: uuid.UUID | None = PLATFORM,
    duration: timedelta = NINE_HOURS,
) -> ConvertedRow:
    return ConvertedRow(session_id or uuid.uuid7(), day, game.pk, platform_id, duration)


def stats(**overrides: object) -> StatsData:
    """A full reading; every key stated."""
    breakdown = PlaytimeBreakdown(tracked=timedelta(hours=20), historical=ONE_HOUR)
    data: dict[str, object] = {
        "year": YEAR,
        "title": f"{YEAR} Stats",
        "total_hours": breakdown,
        "total_sessions": 4,
        "unique_days": 3,
        "unique_days_percent": 1,
        "total_year_games": 2,
        "this_year_finished_this_year_count": 0,
        "games_by_playtime": [
            GameByPlaytime(FIRST, PlaytimeBreakdown(NINE_HOURS, ZERO)),
            GameByPlaytime(SECOND, PlaytimeBreakdown(timedelta(hours=11), ONE_HOUR)),
        ],
        "games_by_playtime_count": 2,
        "total_playtime_per_platform": [
            PlatformPlaytime(PLATFORM, "PC", breakdown),
        ],
        "total_spent": 0,
        "total_spent_currency": "EUR",
        "spent_per_game": 0,
        "all_purchased_this_year_count": 0,
        "all_purchased_refunded_this_year": [],
        "all_purchased_refunded_this_year_count": 0,
        "refunded_percent": 0,
        "dropped_count": 0,
        "dropped_percentage": 0,
        "purchased_unfinished_count": 0,
        "unfinished_purchases_percent": 0,
        "backlog_decrease_count": 0,
        "longest_session_time": NINE_HOURS,
        "longest_session_game": FIRST,
        "highest_session_count": 3,
        "highest_session_count_game": SECOND,
        "highest_session_average": timedelta(hours=4),
        "highest_session_average_game": FIRST,
        "first_play_game": FIRST,
        "first_play_date": A_DAY,
        "first_play_from_record": False,
        "last_play_game": SECOND,
        "last_play_date": date(YEAR, 8, 1),
        "last_play_from_record": False,
        "stats_dropdown_year_range": range(2020, 2027),
        "total_games": 2,
        "month_playtimes": [
            MonthPlaytime(date(YEAR, 3, 1), PlaytimeBreakdown(NINE_HOURS, ZERO)),
            MonthPlaytime(
                date(YEAR, 8, 1), PlaytimeBreakdown(timedelta(hours=11), ONE_HOUR)
            ),
        ],
        "all_finished_this_year": [],
        "all_finished_this_year_count": 0,
        "this_year_finished_this_year": [],
        "purchased_this_year_finished_this_year": [],
        "purchased_unfinished": [],
        "all_purchased_this_year": [],
    }
    data.update(overrides)
    return data  # type: ignore[return-value]


def judged(
    before: StatsData,
    after: StatsData,
    identities: ScopeIdentities = NOBODY,
    converted: Converted = NOTHING,
) -> dict[str, FigureChange]:
    return {
        change.key: change
        for change in judge_scope(before, after, identities, converted)
    }


# ── The walk ────────────────────────────────────────────────────────────────


def test_every_stats_key_has_a_rule():
    assert set(RULES) == set(STATS_SOURCES)


def test_two_equal_readings_report_nothing():
    assert judge_scope(stats(), stats(), NOBODY, NOTHING) == ()


def test_a_key_present_in_one_reading_only_is_unattributed():
    before = stats()
    after = stats()
    del after["total_games"]  # type: ignore[misc]

    change = judged(before, after)["total_games"]

    assert change.attribution is None
    assert unattributed([change]) == (change,)


def test_a_key_absent_from_both_is_skipped():
    before = stats()
    after = stats()
    del before["month_playtimes"]  # type: ignore[misc]
    del after["month_playtimes"]  # type: ignore[misc]

    assert "month_playtimes" not in judged(before, after)


# ── Playtime: the total holds ───────────────────────────────────────────────


def moved_nine_hours() -> tuple[StatsData, Converted]:
    after = stats(
        total_hours=PlaytimeBreakdown(timedelta(hours=11), timedelta(hours=10)),
        games_by_playtime=[
            GameByPlaytime(FIRST, PlaytimeBreakdown(ZERO, NINE_HOURS)),
            GameByPlaytime(SECOND, PlaytimeBreakdown(timedelta(hours=11), ONE_HOUR)),
        ],
        total_playtime_per_platform=[
            PlatformPlaytime(
                PLATFORM,
                "PC",
                PlaytimeBreakdown(timedelta(hours=11), timedelta(hours=10)),
            )
        ],
        month_playtimes=[
            MonthPlaytime(date(YEAR, 3, 1), PlaytimeBreakdown(ZERO, NINE_HOURS)),
            MonthPlaytime(
                date(YEAR, 8, 1), PlaytimeBreakdown(timedelta(hours=11), ONE_HOUR)
            ),
        ],
        total_sessions=3,
    )
    return after, Converted((converted_row(),))


@pytest.mark.parametrize(
    "key",
    [
        "total_hours",
        "games_by_playtime",
        "total_playtime_per_platform",
        "month_playtimes",
    ],
)
def test_hours_moving_between_the_halves_are_attributed(key):
    after, converted = moved_nine_hours()

    change = judged(stats(), after, converted=converted)[key]

    assert change.attribution == "9:00:00 moved from tracked to historical"


def test_a_total_moving_by_one_second_is_unattributed():
    after, converted = moved_nine_hours()
    after["total_hours"] = PlaytimeBreakdown(
        timedelta(hours=11), timedelta(hours=10, seconds=1)
    )

    assert (
        judged(stats(), after, converted=converted)["total_hours"].attribution is None
    )


def test_hours_moving_with_no_converted_row_are_unattributed():
    after, _ = moved_nine_hours()

    assert judged(stats(), after)["total_hours"].attribution is None


def test_a_converted_row_whose_hours_did_not_move_is_reported():
    converted = Converted((converted_row(),))

    change = judged(stats(), stats(), converted=converted)["total_hours"]

    assert change.attribution is None
    assert change.before == change.after


def test_equal_game_totals_in_another_order_are_unattributed():
    before = stats()
    after = stats(games_by_playtime=list(reversed(before["games_by_playtime"])))

    assert judged(before, after)["games_by_playtime"].attribution is None


def test_a_game_outside_the_listed_rows_moves_nothing_listed():
    third = Game(pk=uuid.uuid7(), name="Cc", sort_name="cc")
    converted = Converted((converted_row(game=third, platform_id=None),))
    after = stats(
        total_hours=PlaytimeBreakdown(timedelta(hours=11), timedelta(hours=10)),
        total_sessions=3,
    )

    changes = judged(stats(), after, converted=converted)

    assert changes["total_hours"].attribution is not None
    assert "games_by_playtime" not in changes


# ── Counts and days: equal, or the read disagrees with the charter ──────────


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("unique_days", 2),
        ("unique_days_percent", 0),
        ("games_by_playtime_count", 1),
        ("total_games", 1),
        ("total_year_games", 1),
        ("first_play_date", date(YEAR, 3, 6)),
        ("first_play_game", SECOND),
        ("last_play_date", date(YEAR, 7, 31)),
        ("last_play_game", FIRST),
        ("total_spent", 5),
        ("title", "other"),
    ],
)
def test_a_count_or_day_that_moves_is_unattributed(key, value):
    converted = Converted((converted_row(),))

    change = judged(stats(), stats(**{key: value}), converted=converted)[key]

    assert change.attribution is None
    assert (change.before, change.after) == (stats()[key], value)  # type: ignore[literal-required]


# ── Sessions ────────────────────────────────────────────────────────────────


def test_the_session_count_falls_by_the_converted_rows():
    converted = Converted((converted_row(), converted_row(game=SECOND)))

    change = judged(stats(), stats(total_sessions=2), converted=converted)[
        "total_sessions"
    ]

    assert change.attribution == "2 row(s) converted"


def test_the_session_count_falling_by_more_is_unattributed():
    converted = Converted((converted_row(),))

    assert (
        judged(stats(), stats(total_sessions=2), converted=converted)[
            "total_sessions"
        ].attribution
        is None
    )


def test_the_session_count_holding_beside_a_converted_row_is_reported():
    converted = Converted((converted_row(),))

    assert (
        judged(stats(), stats(), converted=converted)["total_sessions"].attribution
        is None
    )


def test_the_longest_session_changes_where_it_was_converted():
    identities = ScopeIdentities(LONGEST, None, None)
    converted = Converted((converted_row(session_id=LONGEST),))
    after = stats(longest_session_time=timedelta(hours=5), longest_session_game=SECOND)

    changes = judged(stats(), after, identities, converted)

    assert changes["longest_session_time"].attribution == (
        f"the longest session before, {LONGEST}, was converted"
    )
    assert changes["longest_session_game"].attribution == (
        f"the longest session before, {LONGEST}, was converted"
    )


def test_the_longest_session_changing_without_its_conversion_is_unattributed():
    identities = ScopeIdentities(LONGEST, None, None)
    converted = Converted((converted_row(),))
    after = stats(longest_session_time=timedelta(hours=5))

    assert (
        judged(stats(), after, identities, converted)[
            "longest_session_time"
        ].attribution
        is None
    )


def test_the_most_sessions_game_changes_where_it_held_a_converted_row():
    identities = ScopeIdentities(None, SECOND.pk, None)
    converted = Converted((converted_row(game=SECOND),))
    after = stats(highest_session_count=2, highest_session_count_game=FIRST)

    changes = judged(stats(), after, identities, converted)

    assert changes["highest_session_count"].attribution == (
        f"the game with most sessions before, {SECOND.pk}, held a converted row"
    )
    assert changes["highest_session_count_game"].attribution is not None


def test_the_most_sessions_game_changing_elsewhere_is_unattributed():
    identities = ScopeIdentities(None, SECOND.pk, None)
    converted = Converted((converted_row(game=FIRST),))
    after = stats(highest_session_count=2)

    assert (
        judged(stats(), after, identities, converted)[
            "highest_session_count"
        ].attribution
        is None
    )


def test_the_highest_average_changes_where_the_game_before_held_a_converted_row():
    identities = ScopeIdentities(None, None, FIRST.pk)
    converted = Converted((converted_row(game=FIRST),))
    after = stats(
        highest_session_average=timedelta(hours=3), highest_session_average_game=SECOND
    )

    change = judged(stats(), after, identities, converted)["highest_session_average"]

    assert change.attribution == (
        f"the highest-average game before, {FIRST.pk}, held a converted row"
    )


def test_the_highest_average_changes_where_the_game_after_held_a_converted_row():
    identities = ScopeIdentities(None, None, FIRST.pk)
    converted = Converted((converted_row(game=SECOND, duration=timedelta(minutes=5)),))
    after = stats(
        highest_session_average=timedelta(hours=6), highest_session_average_game=SECOND
    )

    change = judged(stats(), after, identities, converted)[
        "highest_session_average_game"
    ]

    assert change.attribution == (
        f"the highest-average game after, {SECOND.pk}, held a converted row"
    )


def test_the_highest_average_changing_at_a_third_game_is_unattributed():
    third = Game(pk=uuid.uuid7(), name="Cc", sort_name="cc")
    identities = ScopeIdentities(None, None, FIRST.pk)
    converted = Converted((converted_row(game=third),))
    after = stats(
        highest_session_average=timedelta(hours=6), highest_session_average_game=SECOND
    )

    assert (
        judged(stats(), after, identities, converted)[
            "highest_session_average"
        ].attribution
        is None
    )


# ── The two play-source flags ───────────────────────────────────────────────


def test_the_first_play_flag_flips_where_its_play_was_converted():
    converted = Converted((converted_row(day=A_DAY, game=FIRST),))

    change = judged(stats(), stats(first_play_from_record=True), converted=converted)[
        "first_play_from_record"
    ]

    assert change.attribution is not None
    assert "was converted" in change.attribution


def test_the_first_play_flag_flipping_on_another_play_is_unattributed():
    converted = Converted((converted_row(day=A_DAY, game=SECOND),))

    assert (
        judged(stats(), stats(first_play_from_record=True), converted=converted)[
            "first_play_from_record"
        ].attribution
        is None
    )


def test_the_last_play_flag_flips_where_its_play_was_converted():
    converted = Converted((converted_row(day=date(YEAR, 8, 1), game=SECOND),))

    assert (
        judged(stats(), stats(last_play_from_record=True), converted=converted)[
            "last_play_from_record"
        ].attribution
        is not None
    )


def test_a_flag_falling_back_to_a_session_is_unattributed():
    converted = Converted((converted_row(day=A_DAY, game=FIRST),))

    assert (
        judged(stats(first_play_from_record=True), stats(), converted=converted)[
            "first_play_from_record"
        ].attribution
        is None
    )


# ── The scope narrows the rows ──────────────────────────────────────────────


def test_a_scope_keeps_the_rows_dated_in_its_year():
    in_year = converted_row(day=A_DAY)
    outside = converted_row(day=date(YEAR - 1, 12, 31))
    converted = Converted((in_year, outside))

    assert converted.in_scope(YEAR).rows == (in_year,)
    assert converted.in_scope(None).rows == (in_year, outside)
