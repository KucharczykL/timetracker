"""Statistics parity across a reclassification: the rules, the command."""

import uuid
from datetime import UTC, date, datetime, timedelta
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from games.commands.playergame import TrackGame
from games.commands.playersession import CreateSession, DurationOnlyTiming, TimedTiming
from games.events.dispatch import dispatch
from games.models import (
    Game,
    HistoricalPlaytime,
    HistoricalPlaytimeRun,
    LibraryEvent,
    PlayerSession,
    Playthrough,
)
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


# ── The command ─────────────────────────────────────────────────────────────

MARCH_5 = date(2025, 3, 5)
MIDDAY = datetime(2025, 3, 7, 12, tzinfo=UTC)


@pytest.fixture
def prague_calendar(owned_user, set_user_setting):
    set_user_setting(owned_user, "DISPLAY_TIME_ZONE", "Europe/Prague")


def tracked_run(library, actor, name: str) -> Playthrough:
    game = Game.objects.create(library=library, name=name)
    dispatch(
        TrackGame(game_id=game.pk),
        actor=actor,
        library=library,
        idempotency_key=f"track-{name}",
    )
    return Playthrough.objects.get(player_game__game=game)


def a_session(library, actor, run, timing) -> None:
    dispatch(
        CreateSession(playthrough_id=run.pk, timing=timing),
        actor=actor,
        library=library,
        idempotency_key=str(uuid.uuid7()),
    )


@pytest.fixture
def review_population(owned_user, owned_library, prague_calendar):
    """Two rows the review offers, two it leaves alone."""
    alpha = tracked_run(owned_library, owned_user, "Alpha")
    beta = tracked_run(owned_library, owned_user, "Beta")
    gamma = tracked_run(owned_library, owned_user, "Gamma")
    delta = tracked_run(owned_library, owned_user, "Delta")
    a_session(
        owned_library,
        owned_user,
        alpha,
        DurationOnlyTiming(day=MARCH_5, duration=timedelta(hours=9)),
    )
    a_session(
        owned_library,
        owned_user,
        beta,
        DurationOnlyTiming(day=date(2025, 3, 6), duration=timedelta(hours=10)),
    )
    a_session(
        owned_library,
        owned_user,
        beta,
        TimedTiming(
            started_at=MIDDAY,
            ended_at=MIDDAY + timedelta(hours=1),
            day_zone="Europe/Prague",
        ),
    )
    a_session(
        owned_library,
        owned_user,
        gamma,
        TimedTiming(
            started_at=MIDDAY + timedelta(days=1),
            ended_at=MIDDAY + timedelta(days=1, hours=2),
            day_zone="Europe/Prague",
        ),
    )
    a_session(
        owned_library,
        owned_user,
        delta,
        DurationOnlyTiming(day=date(2025, 3, 9), duration=timedelta(hours=3)),
    )


def run_parity(**options) -> str:
    output = StringIO()
    call_command("verify_reclassification_parity", stdout=output, **options)
    return output.getvalue()


def lines_naming(output: str, key: str) -> list[str]:
    return [line for line in output.splitlines() if f": {key} " in line]


@pytest.mark.untracked_games
@pytest.mark.django_db(transaction=True)
def test_the_conversion_is_judged_clean(owned_user, owned_library, review_population):
    output = run_parity(user=owned_user.username, confirm=owned_user.username)

    assert "Review population: 2 session(s)" in output
    assert "0 unattributed of" in output
    assert "2 rows converted" in output
    assert lines_naming(output, "total_sessions") == [
        "all-time: total_sessions 5 -> 3 [2 row(s) converted]",
        "2025: total_sessions 5 -> 3 [2 row(s) converted]",
    ]
    assert "was converted" in lines_naming(output, "longest_session_time")[0]
    assert "19:00:00 moved" in lines_naming(output, "total_hours")[0]
    assert "was converted" in lines_naming(output, "first_play_from_record")[0]
    for key in ("total_games", "unique_days", "first_play_date", "last_play_date"):
        assert lines_naming(output, key) == []
    assert HistoricalPlaytime.objects.filter(library=owned_library).count() == 2
    assert PlayerSession.objects.alive().filter(library=owned_library).count() == 3


@pytest.mark.untracked_games
@pytest.mark.django_db(transaction=True)
def test_the_conversion_leaves_statistics_on_the_record_tables(
    owned_user, review_population, monkeypatch
):
    analyzed: list[object] = []
    monkeypatch.setattr(
        "games.management.commands.verify_reclassification_parity.analyze_tables",
        analyzed.append,
    )

    run_parity(user=owned_user.username, confirm=owned_user.username)

    assert analyzed == [(HistoricalPlaytime, HistoricalPlaytimeRun)]


@pytest.mark.untracked_games
@pytest.mark.django_db(transaction=True)
def test_without_confirm_nothing_is_appended(
    owned_user, owned_library, review_population
):
    events = LibraryEvent.objects.filter(library=owned_library).count()

    output = run_parity(user=owned_user.username)

    assert "DRY RUN" in output
    assert "Review population: 2 session(s)" in output
    assert "2025:" in output
    assert LibraryEvent.objects.filter(library=owned_library).count() == events


@pytest.mark.untracked_games
@pytest.mark.django_db(transaction=True)
def test_a_mismatched_confirm_is_refused(owned_user, review_population):
    with pytest.raises(CommandError, match="--confirm must exactly match"):
        run_parity(user=owned_user.username, confirm="someone-else")


@pytest.mark.django_db(transaction=True)
def test_an_unknown_user_is_named():
    with pytest.raises(CommandError, match="does not exist"):
        run_parity(user="nobody")


@pytest.mark.untracked_games
@pytest.mark.django_db(transaction=True)
def test_a_second_run_converts_nothing_and_stays_clean(
    owned_user, owned_library, review_population
):
    run_parity(user=owned_user.username, confirm=owned_user.username)
    events = LibraryEvent.objects.filter(library=owned_library).count()

    output = run_parity(user=owned_user.username, confirm=owned_user.username)

    assert "Review population: 0 session(s)" in output
    assert "0 unattributed of 0 changed" in output
    assert LibraryEvent.objects.filter(library=owned_library).count() == events


@pytest.mark.untracked_games
@pytest.mark.django_db(transaction=True)
def test_an_unattributed_change_fails_the_run(
    owned_user, review_population, monkeypatch
):
    monkeypatch.setitem(RULES, "total_sessions", lambda comparison: None)
    output = StringIO()

    #: Once a scope: all-time and the year.
    with pytest.raises(CommandError, match="2 unattributed of"):
        call_command(
            "verify_reclassification_parity",
            user=owned_user.username,
            confirm=owned_user.username,
            stdout=output,
        )

    assert "total_sessions 5 -> 3 [UNATTRIBUTED]" in output.getvalue()
