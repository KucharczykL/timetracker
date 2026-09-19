"""The stats page's day figures: days played, first and last play."""

from datetime import UTC, date, datetime, timedelta

import pytest
from historical_playtime_rows import record_row
from session_rows import duration_only_row, timed_row, tracked_run

from games.models import Game
from games.reads.play_figures import distinct_days, first_play, last_play

pytestmark = pytest.mark.django_db

ZONE = "UTC"


def at(day: date, hour: int) -> datetime:
    return datetime(day.year, day.month, day.day, hour, tzinfo=UTC)


def timed(run, day: date, hour: int, hours: int):
    return timed_row(
        run, at(day, hour), at(day, hour) + timedelta(hours=hours), day_zone=ZONE
    )


@pytest.fixture
def games(owned_library):
    """Two games whose sort names order Beta before Alpha."""
    beta = Game.objects.create(library=owned_library, name="Beta", sort_name="a beta")
    alpha = Game.objects.create(
        library=owned_library, name="Alpha", sort_name="b alpha"
    )
    return beta, alpha


def test_a_year_scope_counts_that_year_s_days(owned_library, games):
    beta, alpha = games
    timed(tracked_run(owned_library, alpha), date(2023, 12, 31), 10, 5)
    timed(tracked_run(owned_library, beta), date(2024, 1, 1), 10, 1)

    assert distinct_days(owned_library, 2024) == 1
    assert distinct_days(owned_library, None) == 2


def test_a_shared_day_answers_by_sort_name_at_each_end(owned_library, games):
    beta, alpha = games
    day = date(2024, 1, 1)
    duration_only_row(tracked_run(owned_library, alpha), day, timedelta(hours=1))
    timed(tracked_run(owned_library, beta), day, 8, 1)

    earliest = first_play(owned_library, None)
    latest = last_play(owned_library, None)

    assert earliest is not None and latest is not None
    assert (earliest.day, earliest.game) == (day, beta)
    assert (latest.day, latest.game) == (day, alpha)


def test_an_empty_library_answers_none_and_zero(owned_library):
    assert distinct_days(owned_library, None) == 0
    assert first_play(owned_library, None) is None
    assert last_play(owned_library, None) is None


@pytest.mark.parametrize(
    "when",
    ["2024-03-05", "2024-03-05~", "2024-03-05?", "2024-03-05/2024-03-05"],
)
def test_a_record_naming_one_day_raises_the_day_count(owned_library, games, when):
    beta, _alpha = games
    record_row([tracked_run(owned_library, beta)], when=when)

    assert distinct_days(owned_library, 2024) == 1
    assert distinct_days(owned_library, None) == 1


@pytest.mark.parametrize(
    "when", ["2024", "2024-03", "2024-03-05/2024-03-06", "2024-03-05/..", None]
)
def test_a_record_naming_no_single_day_raises_nothing(owned_library, games, when):
    beta, _alpha = games
    record_row([tracked_run(owned_library, beta)], when=when)

    assert distinct_days(owned_library, 2024) == 0
    assert distinct_days(owned_library, None) == 0


def test_a_record_on_a_day_a_session_holds_counts_once(owned_library, games):
    beta, _alpha = games
    run = tracked_run(owned_library, beta)
    day = date(2024, 3, 5)
    timed(run, day, 10, 1)
    record_row([run], when="2024-03-05")

    assert distinct_days(owned_library, 2024) == 1


def test_a_day_outside_the_year_leaves_that_year(owned_library, games):
    beta, _alpha = games
    record_row([tracked_run(owned_library, beta)], when="2023-12-31")

    assert distinct_days(owned_library, 2024) == 0
    assert distinct_days(owned_library, None) == 1
