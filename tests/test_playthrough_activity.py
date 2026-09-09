"""The clock that says whether a run is being played."""

import uuid
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone as django_timezone

from games.commands.playthrough import CompletePlaythrough, StartPlaythrough
from games.events.dispatch import dispatch
from games.models import (
    USER_PREFERENCE_FIELD_BY_KEY,
    Game,
    PlayerGame,
    Playthrough,
    Session,
    UserPreferences,
)
from games.reads.playthrough_activity import (
    RunActivity,
    activity_clock,
    recency_phrase,
)
from games.reads.playthrough_runs import library_runs
from games.writes.playergame import new_correlation_id, track_game
from timetracker import settings_resolver
from timetracker.temporal import TemporalValue

#: Every test wants the run #679 states,
#: so none starts from the fixture's bare row.
pytestmark = pytest.mark.untracked_games


@pytest.fixture
def game(owned_library):
    return Game.objects.create(library=owned_library, name="Outer Wilds")


def set_user_setting(user, key: str, value: object) -> None:
    """State one personal preference, as the write path stores it."""
    field = USER_PREFERENCE_FIELD_BY_KEY.get(key)
    if field is not None:
        UserPreferences.objects.filter(user=user).update(**{field: value})
    else:
        row = UserPreferences.objects.get(user=user)
        UserPreferences.objects.filter(user=user).update(
            extra_preferences={**(row.extra_preferences or {}), key: value}
        )
    settings_resolver.clear_cache()


def a_tracked_game(owned_user, game) -> PlayerGame:
    """Track the game as a request does."""
    track_game(owned_user, game, correlation_id=new_correlation_id())
    return PlayerGame.objects.get(library=owned_user.library, game=game)


def annotated_run(library, tracked) -> Playthrough:
    """The one run, with its aliases."""
    return library_runs(library).filter(player_game=tracked).get()


def a_session(game, *, days_ago: int) -> Session:
    return Session.objects.create(
        game=game,
        timestamp_start=django_timezone.now() - timedelta(days=days_ago),
    )


def start_the_run(owned_user, owned_library, tracked, *, day: date) -> None:
    dispatch(
        StartPlaythrough(
            playthrough_id=annotated_run(owned_library, tracked).pk,
            when=TemporalValue.from_day(day),
            note="",
        ),
        actor=owned_user,
        library=owned_library,
        idempotency_key=str(uuid.uuid7()),
    )


def complete_the_run(owned_user, owned_library, tracked, *, day: date) -> None:
    dispatch(
        CompletePlaythrough(
            playthrough_id=annotated_run(owned_library, tracked).pk,
            when=TemporalValue.from_day(day),
            note="",
        ),
        actor=owned_user,
        library=owned_library,
        idempotency_key=str(uuid.uuid7()),
    )


def _today_in(zone: ZoneInfo) -> date:
    return django_timezone.now().astimezone(zone).date()


@pytest.mark.django_db
def test_the_clock_reads_thirty_days_by_default(owned_library):
    clock = activity_clock(owned_library)

    assert clock.threshold_days == 30
    assert clock.boundary_day == _today_in(clock.zone) - timedelta(days=30)


@pytest.mark.django_db
def test_a_personal_threshold_moves_the_boundary(owned_user, owned_library):
    set_user_setting(owned_user, "DORMANT_AFTER_DAYS", 7)

    clock = activity_clock(owned_library)

    assert clock.threshold_days == 7
    assert clock.boundary_day == _today_in(clock.zone) - timedelta(days=7)


@pytest.mark.django_db
def test_the_clock_reads_the_viewers_zone(owned_user, owned_library):
    set_user_setting(owned_user, "DISPLAY_TIME_ZONE", "Pacific/Kiritimati")

    assert activity_clock(owned_library).zone == ZoneInfo("Pacific/Kiritimati")


@pytest.mark.parametrize(
    ("day", "expected"),
    [
        (date(2026, 9, 9), "today"),
        (date(2026, 9, 8), "yesterday"),
        (date(2026, 9, 5), "4 days ago"),
        (date(2026, 8, 9), "1 month ago"),
        (date(2026, 6, 9), "3 months ago"),
        (date(2025, 9, 9), "1 year ago"),
        (date(2023, 9, 9), "3 years ago"),
    ],
)
def test_the_recency_phrase_reads_the_distance(day: date, expected: str):
    assert recency_phrase(day, date(2026, 9, 9)) == expected


def test_a_day_in_the_future_reads_today():
    assert recency_phrase(date(2026, 9, 10), date(2026, 9, 9)) == "today"


@pytest.mark.django_db(transaction=True)
def test_a_run_with_a_recent_session_is_playing(owned_user, owned_library, game):
    tracked = a_tracked_game(owned_user, game)
    a_session(game, days_ago=3)

    run = annotated_run(owned_library, tracked)

    assert run.activity == RunActivity.PLAYING
    assert run.activity_day == _today_in(
        activity_clock(owned_library).zone
    ) - timedelta(days=3)


@pytest.mark.django_db(transaction=True)
def test_a_run_whose_last_session_is_older_than_the_threshold_is_dormant(
    owned_user, owned_library, game
):
    tracked = a_tracked_game(owned_user, game)
    a_session(game, days_ago=100)

    assert annotated_run(owned_library, tracked).activity == RunActivity.DORMANT


@pytest.mark.django_db(transaction=True)
def test_a_run_with_no_session_and_no_start_day_was_never_played(
    owned_user, owned_library, game
):
    tracked = a_tracked_game(owned_user, game)

    run = annotated_run(owned_library, tracked)

    assert run.activity == RunActivity.NEVER_PLAYED
    assert run.activity_day is None


@pytest.mark.django_db(transaction=True)
def test_a_run_with_no_session_reads_its_own_start_day(owned_user, owned_library, game):
    tracked = a_tracked_game(owned_user, game)
    today = _today_in(activity_clock(owned_library).zone)
    start_the_run(owned_user, owned_library, tracked, day=today)

    run = annotated_run(owned_library, tracked)

    assert run.activity == RunActivity.PLAYING
    assert run.activity_day == today


@pytest.mark.django_db(transaction=True)
def test_a_session_beats_a_later_start_day(owned_user, owned_library, game):
    """The order is a preference, not a maximum."""
    tracked = a_tracked_game(owned_user, game)
    today = _today_in(activity_clock(owned_library).zone)
    start_the_run(owned_user, owned_library, tracked, day=today)
    a_session(game, days_ago=100)

    run = annotated_run(owned_library, tracked)

    assert run.activity_day == today - timedelta(days=100)
    assert run.activity == RunActivity.DORMANT


@pytest.mark.django_db(transaction=True)
def test_a_completed_run_carries_no_word(owned_user, owned_library, game):
    tracked = a_tracked_game(owned_user, game)
    a_session(game, days_ago=3)
    complete_the_run(
        owned_user,
        owned_library,
        tracked,
        day=_today_in(activity_clock(owned_library).zone),
    )

    assert annotated_run(owned_library, tracked).activity is None


@pytest.mark.django_db(transaction=True)
def test_a_personal_threshold_moves_a_run_from_playing_to_dormant(
    owned_user, owned_library, game
):
    tracked = a_tracked_game(owned_user, game)
    a_session(game, days_ago=10)
    assert annotated_run(owned_library, tracked).activity == RunActivity.PLAYING

    set_user_setting(owned_user, "DORMANT_AFTER_DAYS", 7)

    assert annotated_run(owned_library, tracked).activity == RunActivity.DORMANT


@pytest.mark.django_db(transaction=True)
def test_another_librarys_sessions_at_a_shared_game_move_no_word(
    owned_user, owned_library
):
    """A shared catalog game reads no session at all."""
    shared = Game.objects.create(library=None, name="Shared")
    tracked = a_tracked_game(owned_user, shared)
    a_session(shared, days_ago=3)

    run = annotated_run(owned_library, tracked)

    assert run.activity_day is None
    assert run.activity == RunActivity.NEVER_PLAYED


@pytest.mark.django_db(transaction=True)
def test_a_late_session_and_a_start_on_that_day_read_alike(
    owned_user, owned_library, game
):
    """One comparison space: both sides answer a day.

    A session at 23:30 local on the boundary day and a run
    started on that same date must give the same word, in a
    zone whose offset moves that week.
    """
    set_user_setting(owned_user, "DISPLAY_TIME_ZONE", "America/Santiago")
    set_user_setting(owned_user, "DORMANT_AFTER_DAYS", 7)
    clock = activity_clock(owned_library)
    late = datetime.combine(clock.boundary_day, time(23, 30), tzinfo=clock.zone)

    by_session = a_tracked_game(owned_user, game)
    Session.objects.create(game=game, timestamp_start=late)
    other = Game.objects.create(library=owned_library, name="Other")
    by_start = a_tracked_game(owned_user, other)
    start_the_run(owned_user, owned_library, by_start, day=clock.boundary_day)

    assert annotated_run(owned_library, by_session).activity == RunActivity.PLAYING
    assert annotated_run(owned_library, by_start).activity == RunActivity.PLAYING


@pytest.mark.django_db(transaction=True)
def test_annotating_twice_states_one_clock(owned_user, owned_library, game):
    tracked = a_tracked_game(owned_user, game)
    a_session(game, days_ago=10)
    clock = activity_clock(owned_library)

    once = library_runs(owned_library).filter(player_game=tracked)
    twice = once.annotated_for_filtering(clock)

    assert twice.get().activity == once.get().activity
