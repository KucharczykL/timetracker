"""The stats page's session figures, one row each."""

from datetime import UTC, date, datetime, timedelta

import pytest
from django.utils import timezone
from session_rows import duration_only_row, timed_row, tracked_run

from games.models import Game, PlayerSession
from games.reads.session_figures import (
    has_sessions,
    highest_average_game,
    longest_session,
    most_sessions_game,
    session_count,
)

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


def test_an_equal_longest_duration_picks_the_lower_sort_name(owned_library, games):
    beta, alpha = games
    timed(tracked_run(owned_library, alpha), date(2024, 1, 1), 10, 2)
    timed(tracked_run(owned_library, beta), date(2024, 1, 2), 10, 2)

    longest = longest_session(owned_library, None)

    assert longest is not None
    assert longest.game == beta
    assert longest.session.effective_duration == timedelta(hours=2)


def test_an_equal_session_count_picks_the_lower_sort_name(owned_library, games):
    beta, alpha = games
    alpha_run = tracked_run(owned_library, alpha)
    beta_run = tracked_run(owned_library, beta)
    timed(alpha_run, date(2024, 1, 1), 10, 1)
    timed(alpha_run, date(2024, 1, 2), 10, 1)
    timed(beta_run, date(2024, 1, 3), 10, 1)
    timed(beta_run, date(2024, 1, 4), 10, 1)

    most = most_sessions_game(owned_library, None)

    assert most is not None
    assert (most.game, most.sessions) == (beta, 2)


def test_the_highest_average_reads_a_stated_duration_whole(owned_library, games):
    beta, alpha = games
    timed(tracked_run(owned_library, alpha), date(2024, 1, 1), 10, 1)
    duration_only_row(
        tracked_run(owned_library, beta), date(2024, 1, 2), timedelta(hours=3)
    )

    highest = highest_average_game(owned_library, None)

    assert highest is not None
    assert (highest.game, highest.average) == (beta, timedelta(hours=3))


def test_a_year_scope_excludes_the_other_year(owned_library, games):
    beta, alpha = games
    timed(tracked_run(owned_library, alpha), date(2023, 12, 31), 10, 5)
    timed(tracked_run(owned_library, beta), date(2024, 1, 1), 10, 1)

    assert session_count(owned_library, 2024) == 1
    longest = longest_session(owned_library, 2024)
    assert longest is not None and longest.game == beta
    assert session_count(owned_library, None) == 2


def test_an_empty_library_answers_none_and_zero(owned_library):
    assert session_count(owned_library, None) == 0
    assert longest_session(owned_library, None) is None
    assert most_sessions_game(owned_library, None) is None
    assert highest_average_game(owned_library, None) is None
    assert has_sessions(owned_library) is False


def test_a_removed_session_leaves_every_figure(owned_library, games):
    beta, _alpha = games
    row = timed(tracked_run(owned_library, beta), date(2024, 1, 1), 10, 1)
    assert has_sessions(owned_library) is True

    #: The projector's mark, stated here as a row.
    PlayerSession.objects.filter(pk=row.pk).update(removed_at=timezone.now())

    assert has_sessions(owned_library) is False
    assert most_sessions_game(owned_library, None) is None
