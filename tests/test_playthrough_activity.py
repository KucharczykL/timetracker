"""The clock behind Playing and Dormant."""

import uuid
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone as django_timezone
from session_rows import duration_only_row, timed_row, tracked_run

from games.commands.playthrough import CompletePlaythrough, StartPlaythrough
from games.events.dispatch import dispatch
from games.models import (
    Game,
    PlayerGame,
    PlayerSession,
    Playthrough,
    PlaythroughKind,
)
from games.reads.playthrough_activity import (
    ActivityClock,
    RunActivity,
    activity_clock,
    recency_phrase,
)
from games.reads.playthrough_runs import (
    library_runs,
    live_ordinary_runs,
    runs_with_condition,
)
from games.writes.playergame import new_correlation_id, track_game
from timetracker.temporal import TemporalValue

#: Every test wants the run #679 states.
pytestmark = pytest.mark.untracked_games


@pytest.fixture
def game(owned_library):
    return Game.objects.create(library=owned_library, name="Outer Wilds")


def a_tracked_game(owned_user, game) -> PlayerGame:
    """Track the game as a request does."""
    track_game(owned_user, game, correlation_id=new_correlation_id())
    return PlayerGame.objects.get(library=owned_user.library, game=game)


def annotated_run(library, tracked) -> Playthrough:
    """The one run, with its aliases."""
    return runs_with_condition(library).filter(player_game=tracked).get()


def annotated(library, run: Playthrough) -> Playthrough:
    """That run, with its aliases."""
    return runs_with_condition(library).get(pk=run.pk)


def a_session(
    library, game, *, days_ago: int, run: Playthrough | None = None
) -> PlayerSession:
    """A Timed row on the game's run, its day in the library's calendar."""
    started_at = django_timezone.now() - timedelta(days=days_ago)
    return timed_row(
        run or tracked_run(library, game),
        started_at,
        started_at + timedelta(hours=1),
        day_zone=activity_clock(library).zone.key,
    )


def a_session_starting(library, game, started_at: datetime) -> PlayerSession:
    return timed_row(
        tracked_run(library, game),
        started_at,
        None,
        day_zone=activity_clock(library).zone.key,
    )


def remove_session(session: PlayerSession) -> None:
    """The mark the projector would leave."""
    PlayerSession.objects.filter(pk=session.pk).update(removed_at=django_timezone.now())


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
def test_a_personal_threshold_moves_the_boundary(
    owned_user, owned_library, set_user_setting
):
    set_user_setting(owned_user, "DORMANT_AFTER_DAYS", 7)

    clock = activity_clock(owned_library)

    assert clock.threshold_days == 7
    assert clock.boundary_day == _today_in(clock.zone) - timedelta(days=7)


@pytest.mark.django_db
def test_the_clock_reads_the_viewers_zone(owned_user, owned_library, set_user_setting):
    set_user_setting(owned_user, "DISPLAY_TIME_ZONE", "Pacific/Kiritimati")

    assert activity_clock(owned_library).zone == ZoneInfo("Pacific/Kiritimati")


@pytest.mark.django_db(transaction=True)
def test_the_clock_reads_the_calendar(owned_user, owned_library, set_user_setting):
    from games.commands.calendar import SetCalendarDayZone

    set_user_setting(owned_user, "DISPLAY_TIME_ZONE", "UTC")
    dispatch(
        SetCalendarDayZone(day_zone="Pacific/Kiritimati"),
        actor=owned_user,
        library=owned_library,
        idempotency_key="calendar",
    )

    clock = activity_clock(owned_library)

    assert clock.zone == ZoneInfo("Pacific/Kiritimati")
    assert clock.boundary_day == _today_in(clock.zone) - timedelta(
        days=clock.threshold_days
    )


@pytest.mark.django_db
def test_a_read_naming_the_condition_without_a_clock_is_refused(owned_library):
    from games.reads.playthrough_activity import UnscopedActivityRead

    unscoped = Playthrough.objects.annotated_for_filtering()

    with pytest.raises(UnscopedActivityRead):
        list(unscoped.filter(activity=RunActivity.PLAYING))
    with pytest.raises(UnscopedActivityRead):
        list(unscoped.order_by("activity_day"))


@pytest.mark.django_db
def test_a_read_naming_no_alias_executes_without_a_clock(owned_library):
    assert list(Playthrough.objects.annotated_for_filtering()) == []


@pytest.mark.django_db
def test_an_unscoped_alias_cannot_take_a_clock_later(owned_library):
    #: Annotate once, at the read that states the scope.
    unscoped = Playthrough.objects.annotated_for_filtering()

    with pytest.raises(ValueError, match="annotate once"):
        unscoped.annotated_for_filtering(activity_clock(owned_library))


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
    a_session(owned_library, game, days_ago=3)

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
    a_session(owned_library, game, days_ago=100)

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
    """Sessions win over the run's start day."""
    tracked = a_tracked_game(owned_user, game)
    today = _today_in(activity_clock(owned_library).zone)
    start_the_run(owned_user, owned_library, tracked, day=today)
    a_session(owned_library, game, days_ago=100)

    run = annotated_run(owned_library, tracked)

    assert run.activity_day == today - timedelta(days=100)
    assert run.activity == RunActivity.DORMANT


@pytest.mark.django_db(transaction=True)
def test_a_completed_run_carries_no_word(owned_user, owned_library, game):
    tracked = a_tracked_game(owned_user, game)
    a_session(owned_library, game, days_ago=3)
    complete_the_run(
        owned_user,
        owned_library,
        tracked,
        day=_today_in(activity_clock(owned_library).zone),
    )

    assert annotated_run(owned_library, tracked).activity is None


@pytest.mark.django_db(transaction=True)
def test_a_personal_threshold_moves_a_run_from_playing_to_dormant(
    owned_user, owned_library, game, set_user_setting
):
    tracked = a_tracked_game(owned_user, game)
    a_session(owned_library, game, days_ago=10)
    assert annotated_run(owned_library, tracked).activity == RunActivity.PLAYING

    set_user_setting(owned_user, "DORMANT_AFTER_DAYS", 7)

    assert annotated_run(owned_library, tracked).activity == RunActivity.DORMANT


@pytest.mark.django_db(transaction=True)
def test_another_librarys_sessions_at_a_shared_game_move_no_word(
    owned_user, owned_library, django_user_model
):
    """Another library's run at the shared game reads nothing here."""
    shared = Game.objects.create(library=None, name="Shared")
    tracked = a_tracked_game(owned_user, shared)
    stranger = django_user_model.objects.create_user(username="stranger", password="p")
    a_session(stranger.library, shared, days_ago=3)

    run = annotated_run(owned_library, tracked)

    assert run.activity_day is None
    assert run.activity == RunActivity.NEVER_PLAYED


@pytest.mark.django_db(transaction=True)
def test_a_sibling_runs_session_moves_no_word(owned_user, owned_library, game):
    """The clock asks the run, not the game."""
    tracked = a_tracked_game(owned_user, game)
    own = tracked_run(owned_library, game)
    sibling = Playthrough.objects.create(
        pk=uuid.uuid7(),
        library=owned_library,
        player_game=tracked,
        kind=PlaythroughKind.ORDINARY,
        created_at=django_timezone.now(),
    )
    a_session(owned_library, game, days_ago=3, run=sibling)

    assert annotated(owned_library, own).activity == RunActivity.NEVER_PLAYED
    assert annotated(owned_library, sibling).activity == RunActivity.PLAYING


@pytest.mark.django_db(transaction=True)
def test_a_session_in_the_bucket_moves_no_word(owned_user, owned_library, game):
    tracked = a_tracked_game(owned_user, game)
    bucket = Playthrough.objects.create(
        pk=uuid.uuid7(),
        library=owned_library,
        player_game=tracked,
        kind=PlaythroughKind.IMPORTED_HISTORY,
        created_at=django_timezone.now(),
    )
    a_session(owned_library, game, days_ago=3, run=bucket)

    run = annotated_run(owned_library, tracked)

    assert run.activity_day is None
    assert run.activity == RunActivity.NEVER_PLAYED


@pytest.mark.django_db(transaction=True)
def test_a_duration_only_sessions_written_day_counts(owned_user, owned_library, game):
    tracked = a_tracked_game(owned_user, game)
    day = _today_in(activity_clock(owned_library).zone) - timedelta(days=3)
    duration_only_row(tracked_run(owned_library, game), day, timedelta(hours=1))

    run = annotated_run(owned_library, tracked)

    assert run.activity_day == day
    assert run.activity == RunActivity.PLAYING


@pytest.mark.django_db(transaction=True)
def test_a_late_session_and_a_start_on_that_day_read_alike(
    owned_user, owned_library, game, set_user_setting
):
    """One comparison space: both sides answer days."""
    set_user_setting(owned_user, "DISPLAY_TIME_ZONE", "America/Santiago")
    set_user_setting(owned_user, "DORMANT_AFTER_DAYS", 7)
    clock = activity_clock(owned_library)
    late = datetime.combine(clock.boundary_day, time(23, 30), tzinfo=clock.zone)

    by_session = a_tracked_game(owned_user, game)
    a_session_starting(owned_library, game, late)
    other = Game.objects.create(library=owned_library, name="Other")
    by_start = a_tracked_game(owned_user, other)
    start_the_run(owned_user, owned_library, by_start, day=clock.boundary_day)

    assert annotated_run(owned_library, by_session).activity == RunActivity.PLAYING
    assert annotated_run(owned_library, by_start).activity == RunActivity.PLAYING


@pytest.mark.django_db(transaction=True)
def test_the_plain_scope_carries_no_word(owned_user, owned_library, game):
    """Three subqueries a row: readers opt in."""
    tracked = a_tracked_game(owned_user, game)

    scoped = library_runs(owned_library).filter(player_game=tracked).get()
    own = live_ordinary_runs(owned_library, tracked).get()

    for run in (scoped, own):
        assert not hasattr(run, "activity")
        assert not hasattr(run, "activity_day")


@pytest.mark.django_db(transaction=True)
def test_annotating_twice_with_one_clock_states_it_once(
    owned_user, owned_library, game
):
    tracked = a_tracked_game(owned_user, game)
    a_session(owned_library, game, days_ago=10)
    clock = activity_clock(owned_library)

    once = runs_with_condition(owned_library).filter(player_game=tracked)
    twice = once.annotated_for_filtering(clock)

    assert twice.get().activity == once.get().activity


@pytest.mark.django_db(transaction=True)
def test_a_second_clock_is_refused(owned_user, owned_library, game):
    """`add_annotation` would swap one for the other."""
    a_tracked_game(owned_user, game)
    annotated = runs_with_condition(owned_library)
    another = ActivityClock(
        threshold_days=7,
        boundary_day=date(2020, 1, 1),
        zone=activity_clock(owned_library).zone,
    )

    with pytest.raises(ValueError, match="annotate once"):
        annotated.annotated_for_filtering(another)


@pytest.mark.django_db(transaction=True)
def test_a_removed_session_moves_no_word(owned_user, owned_library, game):
    """A removed session moves the day back."""
    tracked = a_tracked_game(owned_user, game)
    a_session(owned_library, game, days_ago=100)
    recent = a_session(owned_library, game, days_ago=2)
    assert annotated_run(owned_library, tracked).activity == RunActivity.PLAYING

    remove_session(recent)

    run = annotated_run(owned_library, tracked)
    assert run.activity == RunActivity.DORMANT
    assert run.activity_day == _today_in(
        activity_clock(owned_library).zone
    ) - timedelta(days=100)


@pytest.mark.django_db(transaction=True)
def test_a_run_whose_only_session_is_removed_was_never_played(
    owned_user, owned_library, game
):
    tracked = a_tracked_game(owned_user, game)
    remove_session(a_session(owned_library, game, days_ago=2))

    run = annotated_run(owned_library, tracked)

    assert run.activity == RunActivity.NEVER_PLAYED
    assert run.activity_day is None


@pytest.mark.django_db(transaction=True)
def test_the_boundary_day_itself_still_reads_playing(
    owned_user, owned_library, game, set_user_setting
):
    """`>=`, so the boundary day still counts."""
    set_user_setting(owned_user, "DORMANT_AFTER_DAYS", 30)
    tracked = a_tracked_game(owned_user, game)
    a_session(owned_library, game, days_ago=30)

    assert annotated_run(owned_library, tracked).activity == RunActivity.PLAYING


@pytest.mark.django_db(transaction=True)
def test_the_day_after_the_boundary_reads_dormant(
    owned_user, owned_library, game, set_user_setting
):
    set_user_setting(owned_user, "DORMANT_AFTER_DAYS", 30)
    tracked = a_tracked_game(owned_user, game)
    a_session(owned_library, game, days_ago=31)

    assert annotated_run(owned_library, tracked).activity == RunActivity.DORMANT


@pytest.mark.django_db(transaction=True)
def test_the_viewers_day_is_read_not_the_servers(
    owned_user, owned_library, game, set_user_setting
):
    """One instant, two calendars: the library's wins."""
    set_user_setting(owned_user, "DISPLAY_TIME_ZONE", "Pacific/Kiritimati")
    set_user_setting(owned_user, "DORMANT_AFTER_DAYS", 30)
    clock = activity_clock(owned_library)
    tracked = a_tracked_game(owned_user, game)
    #: Late enough that UTC still reads yesterday.
    a_session_starting(
        owned_library,
        game,
        datetime.combine(clock.boundary_day, time(0, 30), tzinfo=clock.zone),
    )

    run = annotated_run(owned_library, tracked)

    assert run.activity_day == clock.boundary_day
    assert run.activity == RunActivity.PLAYING
