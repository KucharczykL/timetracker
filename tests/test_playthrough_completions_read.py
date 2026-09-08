"""#1014: what a completion answers, for the statistics."""

import uuid
from datetime import date

import pytest
from django.utils import timezone

from games.models import Game, Playthrough, PlaythroughKind, Purchase
from games.reads.playthrough_completions import (
    completed_runs,
    completion_day,
    completion_exists,
)
from games.removal import remove
from games.writes.playergame import new_correlation_id, track_game
from timetracker.temporal import TemporalValue

#: track_game states the first run, which every test reads.
pytestmark = pytest.mark.untracked_games

YEAR = 2024


def _run_for(user, library, name: str) -> Playthrough:
    game = Game.objects.create(library=library, name=name)
    track_game(user, game, correlation_id=new_correlation_id())
    return Playthrough.objects.get(player_game__game=game)


def _complete(run: Playthrough, value: TemporalValue | None) -> Playthrough:
    """State the completion a command would state."""
    Playthrough.objects.filter(pk=run.pk).update(
        completed=value, completion_recorded_at=run.created_at
    )
    run.refresh_from_db()
    return run


def _second_run(run: Playthrough) -> Playthrough:
    """A second ordinary run at the same tracked game."""
    return Playthrough.objects.create(
        id=uuid.uuid7(),
        library=run.library,
        player_game=run.player_game,
        kind=PlaythroughKind.ORDINARY,
        created_at=timezone.now(),
    )


def _purchase_of(library, game) -> Purchase:
    purchase = Purchase.objects.create(
        library=library,
        price_currency="CZK",
        type=Purchase.GAME,
        date_purchased=date(YEAR, 1, 5),
    )
    purchase.games.set([game])
    return purchase


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    "day", [date(YEAR, 1, 1), date(YEAR, 6, 1), date(YEAR, 12, 31)]
)
def test_a_day_answers_its_own_year(owned_user, owned_library, day):
    run = _complete(
        _run_for(owned_user, owned_library, "Inside"), TemporalValue.from_day(day)
    )

    assert set(completed_runs(owned_library, YEAR)) == {run}
    assert set(completed_runs(owned_library, YEAR + 1)) == set()


@pytest.mark.django_db(transaction=True)
def test_a_whole_year_answers_that_year(owned_user, owned_library):
    run = _complete(
        _run_for(owned_user, owned_library, "Coarse"), TemporalValue.from_year(YEAR)
    )

    assert set(completed_runs(owned_library, YEAR)) == {run}
    assert set(completed_runs(owned_library, YEAR - 1)) == set()


@pytest.mark.django_db(transaction=True)
def test_a_range_across_new_year_answers_both_years(owned_user, owned_library):
    run = _complete(
        _run_for(owned_user, owned_library, "Spanning"),
        TemporalValue.parse(f"{YEAR}-12-20/{YEAR + 1}-01-10"),
    )

    assert set(completed_runs(owned_library, YEAR)) == {run}
    assert set(completed_runs(owned_library, YEAR + 1)) == {run}


@pytest.mark.django_db(transaction=True)
def test_a_completion_with_no_known_day_answers_all_time_only(
    owned_user, owned_library
):
    run = _complete(_run_for(owned_user, owned_library, "Dayless"), None)

    assert set(completed_runs(owned_library, None)) == {run}
    assert set(completed_runs(owned_library, YEAR)) == set()


@pytest.mark.django_db(transaction=True)
def test_an_open_bound_is_unbounded_on_its_own_side(owned_user, owned_library):
    """The interval handler's rule, which the statistics inherit."""
    run = _complete(
        _run_for(owned_user, owned_library, "Open"),
        TemporalValue.parse(f"../{YEAR}-05-01"),
    )

    assert set(completed_runs(owned_library, YEAR)) == {run}
    assert set(completed_runs(owned_library, YEAR - 25)) == {run}
    assert set(completed_runs(owned_library, YEAR + 1)) == set()


@pytest.mark.django_db(transaction=True)
def test_a_run_with_no_completion_answers_neither_scope(owned_user, owned_library):
    _run_for(owned_user, owned_library, "Started only")

    assert set(completed_runs(owned_library, None)) == set()
    assert set(completed_runs(owned_library, YEAR)) == set()


@pytest.mark.django_db(transaction=True)
def test_a_removed_run_answers_nothing(owned_user, owned_library):
    run = _complete(
        _run_for(owned_user, owned_library, "Removed"),
        TemporalValue.from_day(date(YEAR, 6, 1)),
    )
    Playthrough.objects.filter(pk=run.pk).update(removed_at=timezone.now())

    assert set(completed_runs(owned_library, YEAR)) == set()


@pytest.mark.django_db(transaction=True)
def test_a_run_of_a_removed_game_answers_nothing(owned_user, owned_library):
    run = _complete(
        _run_for(owned_user, owned_library, "Gone"),
        TemporalValue.from_day(date(YEAR, 6, 1)),
    )
    remove(run.player_game.game)

    assert set(completed_runs(owned_library, YEAR)) == set()


@pytest.mark.django_db(transaction=True)
def test_a_purchase_answers_the_completion_of_its_game(owned_user, owned_library):
    run = _complete(
        _run_for(owned_user, owned_library, "Bought"),
        TemporalValue.from_day(date(YEAR, 6, 1)),
    )
    purchase = _purchase_of(owned_library, run.player_game.game)

    answered = Purchase.objects.filter(completion_exists(owned_library, YEAR))

    assert list(answered) == [purchase]
    assert not Purchase.objects.filter(completion_exists(owned_library, YEAR + 1))


@pytest.mark.django_db(transaction=True)
def test_a_year_reports_the_earliest_day_and_all_time_the_latest(
    owned_user, owned_library
):
    run = _complete(
        _run_for(owned_user, owned_library, "Twice"),
        TemporalValue.from_day(date(YEAR, 2, 1)),
    )
    _complete(_second_run(run), TemporalValue.from_day(date(YEAR, 11, 1)))
    _purchase_of(owned_library, run.player_game.game)

    in_year = Purchase.objects.annotate(day=completion_day(owned_library, YEAR)).get()
    all_time = Purchase.objects.annotate(day=completion_day(owned_library, None)).get()

    assert in_year.day == date(YEAR, 2, 1)
    assert all_time.day == date(YEAR, 11, 1)


@pytest.mark.django_db(transaction=True)
def test_a_purchase_with_no_completion_reports_no_day(owned_user, owned_library):
    run = _run_for(owned_user, owned_library, "Unfinished")
    _purchase_of(owned_library, run.player_game.game)

    assert (
        Purchase.objects.annotate(day=completion_day(owned_library, YEAR)).get().day
        is None
    )
