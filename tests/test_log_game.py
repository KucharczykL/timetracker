"""The write a Log a game press makes, step by step."""

import datetime
from typing import Any

import pytest
from entries import record_entry
from graphs import default_graph

from games.commands.endpoint import ActStatement
from games.models import (
    Game,
    HistoricalPlaytime,
    HistoricalPlaytimeRun,
    LibraryEntry,
    LibraryEvent,
    Platform,
    PlayerGame,
    PlayerGameStatus,
    PlayerSession,
    Playthrough,
)
from games.reads.playthrough_endpoints import stated_start
from games.writes.endpoint import KEEP
from games.writes.log_game import (
    HistoricalHours,
    LogRefused,
    LogStatement,
    SessionTiming,
    log_game,
)
from games.writes.playergame import new_correlation_id, track_game
from games.writes.playthrough import start_run
from timetracker.temporal import TemporalValue

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.untracked_games]

DAY = datetime.date(2026, 9, 1)
LATER = datetime.date(2026, 9, 9)


@pytest.fixture
def user(owned_user):
    return owned_user


@pytest.fixture
def game(owned_library):
    return Game.objects.create(library=owned_library, name="Outer Wilds")


@pytest.fixture
def pc(owned_library):
    return Platform.objects.create(library=owned_library, name="PC")


@pytest.fixture
def console(owned_library):
    return Platform.objects.create(library=owned_library, name="Xbox")


def _day(day: datetime.date) -> ActStatement:
    return ActStatement(TemporalValue.from_day(day), "")


def _statement(game, **fields: Any) -> LogStatement:
    """A press that states nothing but what `fields` names."""
    defaults: dict[str, Any] = {
        "platform_id": None,
        "platform_changed": False,
        "run_id": None,
        "started": KEEP,
        "completed": KEEP,
        "note": KEEP,
        "playtime": None,
        "attempt": 0,
        "mastered": KEEP,
        "status": KEEP,
        "seen_status": None,
    }
    return LogStatement(game=game, **(defaults | fields))


def _press(user, statement: LogStatement, token=None, correlation_id=None):
    return log_game(
        user,
        statement,
        correlation_id=correlation_id or new_correlation_id(),
        token=token or new_correlation_id(),
    )


def _tracked(user, game) -> Playthrough:
    track_game(user, game, correlation_id=new_correlation_id())
    return Playthrough.objects.get(library=user.library, player_game__game=game)


def _player_game(user, game) -> PlayerGame:
    return PlayerGame.objects.get(library=user.library, game=game)


def _session_timing(day: datetime.date = DAY) -> SessionTiming:
    return SessionTiming(day=day, duration=datetime.timedelta(hours=2), device_id=None)


def test_a_copy_alone_records_an_unknown_copy_on_a_created_release(user, game, pc):
    logged = _press(
        user,
        _statement(game, platform_id=pc.pk, platform_changed=True),
    )

    entry = LibraryEntry.objects.get(library=user.library)
    assert logged.written == frozenset({"copy"})
    assert logged.tracked_the_game is True
    assert (entry.access, entry.format) == ("unknown", "unknown")
    assert entry.release.platform == pc


def test_an_unchanged_platform_records_no_copy(user, game, pc):
    _tracked(user, game)

    _press(user, _statement(game, platform_id=pc.pk, platform_changed=False))

    assert not LibraryEntry.objects.filter(library=user.library).exists()


def test_a_held_platform_records_no_copy_and_the_session_names_its_release(
    user, game, pc, owned_library
):
    held = default_graph(game, owned_library, platform=pc).release
    record_entry(owned_library, held)

    _press(
        user,
        _statement(
            game,
            platform_id=pc.pk,
            platform_changed=True,
            playtime=_session_timing(),
        ),
    )

    assert LibraryEntry.objects.filter(library=user.library).count() == 1
    assert PlayerSession.objects.get(library=user.library).release == held


def test_an_unheld_platform_on_a_standing_release_records_an_unknown_copy(
    user, game, pc, owned_library
):
    standing = default_graph(game, owned_library, platform=pc).release

    _press(user, _statement(game, platform_id=pc.pk, platform_changed=True))

    entry = LibraryEntry.objects.get(library=user.library)
    assert entry.release == standing
    assert entry.access == "unknown"


def test_a_cleared_platform_records_no_copy(user, game):
    _press(user, _statement(game, platform_id=None, platform_changed=True))

    assert not LibraryEntry.objects.filter(library=user.library).exists()


def test_playtime_on_an_untracked_game_names_the_run_track_made(user, game):
    _press(
        user,
        _statement(
            game,
            playtime=HistoricalHours(
                duration=datetime.timedelta(hours=3), device_id=None
            ),
        ),
    )

    run = Playthrough.objects.get(library=user.library, player_game__game=game)
    record = HistoricalPlaytime.objects.get(library=user.library)
    assert HistoricalPlaytimeRun.objects.filter(record=record, playthrough=run).exists()


def test_an_untracked_game_with_every_field_writes_under_one_correlation_id(
    user, game, pc
):
    correlation_id = new_correlation_id()

    logged = _press(
        user,
        _statement(
            game,
            platform_id=pc.pk,
            platform_changed=True,
            started=_day(DAY),
            note="Saved the crew",
            playtime=_session_timing(),
            mastered=True,
            status=PlayerGameStatus.SHELVED,
        ),
        correlation_id=correlation_id,
    )

    player_game = _player_game(user, game)
    assert logged.written == frozenset({"copy", "dates", "playtime", "more", "status"})
    assert player_game.status == PlayerGameStatus.SHELVED
    assert player_game.mastered is True
    assert (
        LibraryEvent.objects.filter(
            library=user.library, correlation_id=correlation_id
        ).count()
        > 1
    )


def test_an_unchanged_status_keeps_the_status_a_session_implies(user, game):
    _tracked(user, game)

    _press(user, _statement(game, playtime=_session_timing()))

    assert _player_game(user, game).status == PlayerGameStatus.PLAYED


def test_a_status_alone_records_it(user, game):
    _tracked(user, game)

    _press(user, _statement(game, status=PlayerGameStatus.SHELVED))

    assert _player_game(user, game).status == PlayerGameStatus.SHELVED


def test_a_changed_day_corrects_the_endpoint(user, game):
    run = _tracked(user, game)
    start_run(
        user,
        run,
        TemporalValue.from_day(DAY),
        implies_status=False,
        correlation_id=new_correlation_id(),
    )

    _press(user, _statement(game, started=_day(LATER)))

    run.refresh_from_db()
    assert stated_start(run).when == TemporalValue.from_day(LATER)


def test_a_cleared_day_voids_the_act_and_keeps_the_status(user, game):
    run = _tracked(user, game)
    start_run(
        user,
        run,
        TemporalValue.from_day(DAY),
        implies_status=True,
        correlation_id=new_correlation_id(),
    )

    _press(user, _statement(game, started=None))

    run.refresh_from_db()
    assert stated_start(run) is None
    assert _player_game(user, game).status == PlayerGameStatus.PLAYED


def test_a_dayless_act_survives_an_untouched_press(user, game):
    run = _tracked(user, game)
    start_run(
        user,
        run,
        None,
        implies_status=False,
        correlation_id=new_correlation_id(),
    )

    _press(user, _statement(game, note="Something else"))

    run.refresh_from_db()
    assert stated_start(run) is not None
    assert stated_start(run).when is None


def test_a_note_alone_restates_the_run_note(user, game):
    run = _tracked(user, game)

    logged = _press(user, _statement(game, note="Left at the bridge"))

    run.refresh_from_db()
    assert run.note == "Left at the bridge"
    assert logged.written == frozenset({"more"})


def test_a_double_press_writes_once(user, game, pc):
    token = new_correlation_id()
    statement = _statement(
        game,
        platform_id=pc.pk,
        platform_changed=True,
        playtime=_session_timing(),
    )

    _press(user, statement, token=token)
    _press(user, statement, token=token)

    assert LibraryEntry.objects.filter(library=user.library).count() == 1
    assert PlayerSession.objects.filter(library=user.library).count() == 1


def test_a_refused_platform_on_a_shared_game_stops_at_platform(user, pc):
    shared = Game.objects.create(library=None, name="Shared Game")

    with pytest.raises(LogRefused) as refused:
        _press(
            user,
            _statement(shared, platform_id=pc.pk, platform_changed=True),
        )

    assert refused.value.step == "platform"
