"""What the empty runs come to state. Issue #1038."""

import uuid
from datetime import UTC, date, datetime

import pytest

from games.backfill.playergame import backfill_library
from games.backfill.playthrough import convert_library
from games.backfill.playthrough_start import (
    Evidence,
    StartSource,
    evidence_for,
    runs_in_scope,
    session_days,
    status_days,
)
from games.models import (
    Game,
    GameStatusChange,
    PlayerGame,
    Playthrough,
    Session,
)
from games.removal import remove
from games.writes.playthrough import RunDraft, record_run

#: backfill_library() and the conftest fixture write the
#: same row, so the two collide on the unique key.
pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.untracked_games,
]


def _game(library, name="Chrono Trigger"):
    return Game.objects.create(library=library, name=name)


def _converted(library):
    """The state #684 leaves: tracked, and one empty run each."""
    backfill_library(library)
    convert_library(library)


def test_a_default_run_is_in_scope(owned_library):
    game = _game(owned_library)
    _converted(owned_library)

    scope = runs_in_scope(owned_library)

    assert len(scope) == 1
    assert scope[0].game_id == game.pk


def test_a_blank_run_a_person_created_is_left_alone(owned_library):
    game = _game(owned_library)
    _converted(owned_library)
    Playthrough.objects.filter(library=owned_library).update(
        removed_at=datetime(2026, 1, 1, tzinfo=UTC)
    )
    record_run(
        owned_library.user,
        game,
        RunDraft(started=None, completed=None, note=""),
        correlation_id=uuid.uuid7(),
    )

    scope = runs_in_scope(owned_library)

    assert scope == []


def test_a_run_stating_either_act_is_left_alone(owned_library):
    _game(owned_library)
    _converted(owned_library)
    Playthrough.objects.filter(library=owned_library).update(
        start_recorded_at=datetime(2026, 1, 1, tzinfo=UTC)
    )

    assert runs_in_scope(owned_library) == []


def test_a_removed_run_is_left_alone(owned_library):
    _game(owned_library)
    _converted(owned_library)
    Playthrough.objects.filter(library=owned_library).update(
        removed_at=datetime(2026, 1, 1, tzinfo=UTC)
    )

    assert runs_in_scope(owned_library) == []


def test_a_run_at_a_removed_game_is_left_alone(owned_library):
    game = _game(owned_library)
    _converted(owned_library)
    remove(game)

    assert runs_in_scope(owned_library) == []


def test_a_session_states_the_viewers_day_not_the_servers(
    owned_user, owned_library, set_user_setting
):
    game = _game(owned_library)
    _converted(owned_library)
    set_user_setting(owned_user, "DISPLAY_TIME_ZONE", "Pacific/Kiritimati")
    #: Late enough in UTC that Kiritimati reads tomorrow.
    Session.objects.create(
        game=game,
        timestamp_start=datetime(2026, 1, 5, 23, 30, tzinfo=UTC),
        timestamp_end=datetime(2026, 1, 6, 0, 30, tzinfo=UTC),
    )

    assert session_days(owned_library)[game.pk] == date(2026, 1, 6)


def test_a_removed_session_states_no_day(owned_library):
    game = _game(owned_library)
    _converted(owned_library)
    session = Session.objects.create(
        game=game,
        timestamp_start=datetime(2026, 1, 5, 10, 0, tzinfo=UTC),
        timestamp_end=datetime(2026, 1, 5, 11, 0, tzinfo=UTC),
    )
    remove(session)

    assert session_days(owned_library) == {}


def test_a_session_on_a_removed_game_states_no_day(owned_library):
    game = _game(owned_library)
    _converted(owned_library)
    Session.objects.create(
        game=game,
        timestamp_start=datetime(2026, 1, 5, 10, 0, tzinfo=UTC),
        timestamp_end=datetime(2026, 1, 5, 11, 0, tzinfo=UTC),
    )
    remove(game)

    assert session_days(owned_library) == {}


def test_the_earliest_session_wins(owned_library):
    game = _game(owned_library)
    _converted(owned_library)
    for day in (7, 3, 9):
        Session.objects.create(
            game=game,
            timestamp_start=datetime(2026, 1, day, 10, 0, tzinfo=UTC),
            timestamp_end=datetime(2026, 1, day, 11, 0, tzinfo=UTC),
        )

    assert session_days(owned_library)[game.pk] == date(2026, 1, 3)


def test_a_status_change_states_its_day(owned_library):
    game = _game(owned_library)
    GameStatusChange.objects.create(
        game=game,
        old_status="u",
        new_status="p",
        timestamp=datetime(2026, 1, 4, 9, 0, tzinfo=UTC),
    )
    _converted(owned_library)
    tracked = PlayerGame.objects.get(library=owned_library, game=game)

    assert status_days(owned_library)[tracked.pk] == date(2026, 1, 4)


def test_the_earlier_of_the_two_wins_and_names_its_source(owned_library):
    game = _game(owned_library)
    GameStatusChange.objects.create(
        game=game,
        old_status="u",
        new_status="p",
        timestamp=datetime(2026, 1, 9, 9, 0, tzinfo=UTC),
    )
    _converted(owned_library)
    Session.objects.create(
        game=game,
        timestamp_start=datetime(2026, 1, 4, 10, 0, tzinfo=UTC),
        timestamp_end=datetime(2026, 1, 4, 11, 0, tzinfo=UTC),
    )
    run = runs_in_scope(owned_library)[0]

    found = evidence_for(
        run,
        status=status_days(owned_library),
        session=session_days(owned_library),
    )

    assert found == Evidence(date(2026, 1, 4), StartSource.SESSION)


def test_a_run_holding_neither_reads_nothing(owned_library):
    _game(owned_library)
    _converted(owned_library)
    run = runs_in_scope(owned_library)[0]

    assert evidence_for(run, status={}, session={}) is None
