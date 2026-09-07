"""#687: the endpoints a day-shaped form can restate."""

from datetime import date

import pytest

from games.models import Game, Playthrough
from games.reads.playthrough_endpoints import restatable_days
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
