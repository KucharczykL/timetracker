"""The runs a stated count may take."""

import uuid
from datetime import date, timedelta

import pytest
from django.utils import timezone
from historical_playtime_rows import record_row
from session_rows import timed_row

from games.models import Game, PlayerGame, Playthrough
from games.reads.playthrough_count import bare_runs, dateless_runs
from games.writes.playergame import new_correlation_id, track_game
from timetracker.temporal import TemporalValue

DAY = TemporalValue.from_day(date(2020, 1, 2))

pytestmark = pytest.mark.untracked_games


@pytest.fixture
def game(owned_library):
    return Game.objects.create(library=owned_library, name="Outer Wilds")


@pytest.fixture
def tracked(owned_user, game) -> PlayerGame:
    track_game(owned_user, game, correlation_id=new_correlation_id())
    return PlayerGame.objects.get(game=game)


@pytest.fixture
def run(tracked) -> Playthrough:
    return Playthrough.objects.get(player_game=tracked)


def _played_through(run: Playthrough, **columns: object) -> Playthrough:
    """Both acts, no day, written by hand."""
    stamp = timezone.now()
    Playthrough.objects.filter(pk=run.pk).update(
        start_recorded_at=stamp, completion_recorded_at=stamp, **columns
    )
    run.refresh_from_db()
    return run


def _dateless(owned_library, tracked) -> list[Playthrough]:
    return list(dateless_runs(owned_library, tracked))


@pytest.mark.django_db(transaction=True)
def test_a_run_played_through_on_no_day_is_dateless(owned_library, tracked, run):
    _played_through(run)

    assert _dateless(owned_library, tracked) == [run]


@pytest.mark.parametrize(
    "columns",
    [
        {"started": DAY},
        {"completed": DAY},
        {"name": "Hard mode"},
        {"note": "With a friend"},
        {"start_note": "Again"},
        {"completion_note": "At last"},
    ],
    ids=["dated start", "dated completion", "named", "noted", "start note", "end"],
)
@pytest.mark.django_db(transaction=True)
def test_a_run_stating_anything_else_is_not_dateless(
    owned_library, tracked, run, columns
):
    _played_through(run, **columns)

    assert _dateless(owned_library, tracked) == []


@pytest.mark.django_db(transaction=True)
def test_a_run_with_one_act_is_not_dateless(owned_library, tracked, run):
    Playthrough.objects.filter(pk=run.pk).update(start_recorded_at=timezone.now())

    assert _dateless(owned_library, tracked) == []


@pytest.mark.parametrize("removed", [False, True], ids=["live", "removed"])
@pytest.mark.django_db(transaction=True)
def test_a_run_a_session_names_is_not_dateless(owned_library, tracked, run, removed):
    _played_through(run)
    session = timed_row(run, timezone.now(), None)
    if removed:
        type(session).objects.filter(pk=session.pk).update(removed_at=timezone.now())

    assert _dateless(owned_library, tracked) == []


@pytest.mark.parametrize("removed", [False, True], ids=["live", "removed"])
@pytest.mark.django_db(transaction=True)
def test_a_run_a_record_names_is_not_dateless(owned_library, tracked, run, removed):
    _played_through(run)
    record = record_row([run])
    if removed:
        type(record).objects.filter(pk=record.pk).update(removed_at=timezone.now())

    assert _dateless(owned_library, tracked) == []


@pytest.mark.django_db(transaction=True)
def test_dateless_runs_read_newest_first(owned_library, tracked, run):
    _played_through(run)
    newer = Playthrough.objects.create(
        id=uuid.uuid7(),
        library=owned_library,
        player_game=tracked,
        kind=run.kind,
        created_at=run.created_at + timedelta(seconds=1),
    )
    _played_through(newer)

    assert _dateless(owned_library, tracked) == [newer, run]


@pytest.mark.django_db(transaction=True)
def test_the_run_tracking_states_is_bare(owned_library, tracked, run):
    assert list(bare_runs(owned_library, tracked)) == [run]


@pytest.mark.parametrize(
    "columns",
    [{"note": "Saved"}, {"name": "First"}],
    ids=["noted", "named"],
)
@pytest.mark.django_db(transaction=True)
def test_a_described_run_is_not_bare(owned_library, tracked, run, columns):
    Playthrough.objects.filter(pk=run.pk).update(**columns)

    assert list(bare_runs(owned_library, tracked)) == []


@pytest.mark.parametrize("removed", [False, True], ids=["live", "removed"])
@pytest.mark.django_db(transaction=True)
def test_a_run_a_session_names_is_not_bare(owned_library, tracked, run, removed):
    session = timed_row(run, timezone.now(), None)
    if removed:
        type(session).objects.filter(pk=session.pk).update(removed_at=timezone.now())

    assert list(bare_runs(owned_library, tracked)) == []


@pytest.mark.django_db(transaction=True)
def test_a_foreign_row_leaves_the_run_for_the_command(
    owned_library, tracked, run, django_user_model
):
    """The command refuses it as a defect."""
    _played_through(run)
    stranger = django_user_model.objects.create_user(username="stranger")
    timed_row(run, timezone.now(), None, library=stranger.library)

    assert _dateless(owned_library, tracked) == [run]


@pytest.mark.django_db(transaction=True)
def test_a_removed_run_is_neither(owned_library, tracked, run):
    _played_through(run)
    Playthrough.objects.filter(pk=run.pk).update(removed_at=timezone.now())

    assert _dateless(owned_library, tracked) == []
    assert list(bare_runs(owned_library, tracked)) == []
