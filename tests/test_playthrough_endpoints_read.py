"""#687: the endpoints a day-shaped form can restate."""

from datetime import date

import pytest

from games.models import Game, Playthrough
from games.reads.playthrough_endpoints import days_to_finish, restatable_days
from games.writes.playergame import new_correlation_id, track_game
from timetracker.temporal import TemporalQualifier, TemporalValue

#: Every test wants the run #679 states.
pytestmark = pytest.mark.untracked_games


@pytest.fixture
def user(owned_user):
    return owned_user


@pytest.fixture
def run(owned_user, owned_library) -> Playthrough:
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    track_game(owned_user, game, correlation_id=new_correlation_id())
    return Playthrough.objects.get(player_game__game=game)


def _state(run: Playthrough, **values) -> Playthrough:
    """Put values on the row a command would state."""
    Playthrough.objects.filter(pk=run.pk).update(**values)
    run.refresh_from_db()
    return run


@pytest.mark.django_db(transaction=True)
def test_two_bare_days_read_as_days(run):
    _state(
        run,
        started=TemporalValue.from_day(date(2026, 1, 2)),
        start_recorded_at=run.created_at,
        completed=TemporalValue.from_day(date(2026, 3, 4)),
        completion_recorded_at=run.created_at,
    )

    days = restatable_days(run)

    assert days == (date(2026, 1, 2), date(2026, 3, 4))


@pytest.mark.django_db(transaction=True)
def test_an_endpoint_that_never_happened_reads_as_no_day(run):
    """The marker is null, so the act never happened."""
    days = restatable_days(run)

    assert days == (None, None)


@pytest.mark.django_db(transaction=True)
def test_a_stated_act_with_no_day_reads_as_no_day(run):
    """The act happened; the day is unknown."""
    _state(run, started=None, start_recorded_at=run.created_at)

    days = restatable_days(run)

    assert days == (None, None)


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    "value",
    [
        TemporalValue.from_month(2026, 3),
        TemporalValue.from_year(2026),
        TemporalValue.from_decade(2020),
        TemporalValue.from_day(
            date(2026, 1, 2), qualifier=TemporalQualifier.APPROXIMATE
        ),
    ],
)
def test_a_value_richer_than_a_day_reads_as_nothing(run, value):
    """A day field would flatten every one of these."""
    _state(run, started=value, start_recorded_at=run.created_at)

    assert restatable_days(run) is None


def _spanning(run: Playthrough, started, completed) -> Playthrough:
    """State both endpoints and read the row back."""
    return _state(
        run,
        started=started,
        start_recorded_at=run.created_at,
        completed=completed,
        completion_recorded_at=run.created_at,
    )


@pytest.mark.django_db(transaction=True)
def test_days_to_finish_reads_the_widest_span(run):
    """January 1 to March 31, inclusive."""
    spanning = _spanning(
        run,
        TemporalValue.from_day(date(2026, 1, 1)),
        TemporalValue.from_month(2026, 3),
    )

    assert days_to_finish(spanning) == 90


@pytest.mark.django_db(transaction=True)
def test_days_to_finish_reads_one_for_a_run_begun_and_finished_on_a_day(run):
    day = TemporalValue.from_day(date(2026, 1, 1))
    spanning = _spanning(run, day, day)

    assert days_to_finish(spanning) == 1


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    "started,completed,expected",
    [
        (date(2026, 3, 1), date(2026, 3, 1), 1),
        (date(2026, 3, 1), date(2026, 3, 2), 2),
        (date(2026, 3, 1), date(2026, 3, 30), 30),
        (date(2026, 3, 2), date(2026, 3, 1), None),
    ],
)
def test_the_count_includes_both_ends(run, started, completed, expected):
    """A same-day run touched one day."""
    spanning = _spanning(
        run,
        TemporalValue.from_day(started),
        TemporalValue.from_day(completed),
    )

    assert days_to_finish(spanning) == expected


@pytest.mark.django_db(transaction=True)
def test_a_month_at_both_ends_counts_the_whole_month(run):
    """The widest span the two values allow."""
    month = TemporalValue.from_month(2026, 3)
    spanning = _spanning(run, month, month)

    assert days_to_finish(spanning) == 31


@pytest.mark.django_db(transaction=True)
def test_days_to_finish_states_nothing_where_a_bound_is_absent(run):
    """The completion happened; nobody knows the day."""
    _state(
        run,
        started=TemporalValue.from_day(date(2026, 1, 1)),
        start_recorded_at=run.created_at,
        completed=None,
        completion_recorded_at=run.created_at,
    )

    assert days_to_finish(run) is None


@pytest.mark.django_db(transaction=True)
def test_days_to_finish_states_nothing_for_a_completion_before_the_start(run):
    """A backwards pair is not a length."""
    spanning = _spanning(
        run,
        TemporalValue.from_day(date(2026, 3, 1)),
        TemporalValue.from_day(date(2026, 1, 1)),
    )

    assert days_to_finish(spanning) is None
