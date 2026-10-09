"""Writes one Log a game press makes."""

import datetime
from typing import Any

import pytest
from django.http import Http404
from django.utils import timezone
from entries import record_entry
from graphs import default_graph
from stated_runs import another_run

from games.commands.endpoint import ActStatement
from games.events.dispatch import RowNotHeld
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
from games.reads.playthrough_endpoints import stated_completion, stated_start
from games.writes import log_game as log_game_writes
from games.writes.answers import CommandFailed
from games.writes.endpoint import KEEP
from games.writes.log_game import (
    GAME_GONE,
    PICKED_RUN_GONE,
    HistoricalHours,
    LogRefused,
    LogStatement,
    SessionTiming,
    log_game,
)
from games.writes.playergame import new_correlation_id, track_game
from games.writes.playthrough import complete_run, remove_run, start_run
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
    """Press stating only `fields`."""
    defaults: dict[str, Any] = {
        "platform": KEEP,
        "run_id": None,
        "started": KEEP,
        "completed": KEEP,
        "note": KEEP,
        "playtime": None,
        "attempt": 0,
        "mastered": KEEP,
        "status": KEEP,
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
        _statement(game, platform=pc.pk),
    )

    entry = LibraryEntry.objects.get(library=user.library)
    assert logged.written == frozenset({"copy"})
    assert logged.tracked_the_game is True
    assert (entry.access, entry.format) == ("unknown", "unknown")
    assert entry.release.platform == pc


def test_an_unchanged_platform_records_no_copy(user, game, pc):
    _tracked(user, game)

    _press(user, _statement(game, platform=KEEP))

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
            platform=pc.pk,
            playtime=_session_timing(),
        ),
    )

    assert LibraryEntry.objects.filter(library=user.library).count() == 1
    assert PlayerSession.objects.get(library=user.library).release == held


def test_an_unheld_platform_on_a_standing_release_records_an_unknown_copy(
    user, game, pc, owned_library
):
    standing = default_graph(game, owned_library, platform=pc).release

    _press(user, _statement(game, platform=pc.pk))

    entry = LibraryEntry.objects.get(library=user.library)
    assert entry.release == standing
    assert entry.access == "unknown"


def test_a_cleared_platform_records_no_copy(user, game):
    _press(user, _statement(game, platform=None))

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
            platform=pc.pk,
            started=_day(DAY),
            note="Saved the crew",
            playtime=_session_timing(),
            mastered=True,
            status=PlayerGameStatus.SHELVED,
        ),
        correlation_id=correlation_id,
    )

    player_game = _player_game(user, game)
    assert logged.written == frozenset(
        {"copy", "dates", "playtime", "mastered", "status"}
    )
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
    assert logged.written == frozenset({"note"})


def test_a_double_press_writes_once(user, game, pc):
    token = new_correlation_id()
    statement = _statement(
        game,
        platform=pc.pk,
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
            _statement(shared, platform=pc.pk),
        )

    assert refused.value.step == "platform"


AFTER = datetime.date(2026, 9, 12)


def _historical(hours: int = 3) -> HistoricalHours:
    return HistoricalHours(duration=datetime.timedelta(hours=hours), device_id=None)


def test_historical_hours_on_an_unplayed_game_end_played(user, game):
    _tracked(user, game)

    _press(user, _statement(game, playtime=_historical()))

    assert _player_game(user, game).status == PlayerGameStatus.PLAYED


def test_historical_hours_with_a_finish_on_the_day_end_completed(user, game):
    _tracked(user, game)

    _press(user, _statement(game, completed=_day(DAY), playtime=_historical()))

    assert _player_game(user, game).status == PlayerGameStatus.COMPLETED


def test_historical_hours_keep_a_completed_game_completed(user, game):
    _tracked(user, game)
    _press(user, _statement(game, status=PlayerGameStatus.COMPLETED))

    _press(user, _statement(game, playtime=_historical()))

    assert _player_game(user, game).status == PlayerGameStatus.COMPLETED


def test_a_finish_on_alone_ends_completed(user, game):
    _tracked(user, game)

    _press(user, _statement(game, completed=_day(DAY)))

    assert _player_game(user, game).status == PlayerGameStatus.COMPLETED


def test_clearing_finished_on_voids_the_completion(user, game):
    run = _tracked(user, game)
    complete_run(
        user,
        run,
        TemporalValue.from_day(DAY),
        implies_status=True,
        correlation_id=new_correlation_id(),
    )

    _press(user, _statement(game, completed=None))

    run.refresh_from_db()
    assert stated_completion(run) is None


def test_clearing_started_and_moving_finished_before_the_old_start_is_accepted(
    user, game
):
    run = _tracked(user, game)
    start_run(
        user,
        run,
        TemporalValue.from_day(LATER),
        implies_status=False,
        correlation_id=new_correlation_id(),
    )

    _press(user, _statement(game, started=None, completed=_day(DAY)))

    run.refresh_from_db()
    assert stated_start(run) is None
    assert stated_completion(run).when == TemporalValue.from_day(DAY)


def test_clearing_finished_and_moving_started_past_the_old_finish_is_accepted(
    user, game
):
    run = _tracked(user, game)
    start_run(
        user,
        run,
        TemporalValue.from_day(DAY),
        implies_status=False,
        correlation_id=new_correlation_id(),
    )
    complete_run(
        user,
        run,
        TemporalValue.from_day(LATER),
        implies_status=False,
        correlation_id=new_correlation_id(),
    )

    _press(user, _statement(game, completed=None, started=_day(AFTER)))

    run.refresh_from_db()
    assert stated_completion(run) is None
    assert stated_start(run).when == TemporalValue.from_day(AFTER)


def test_a_refusal_after_a_committed_void_names_the_dates(user, game, monkeypatch):
    run = _tracked(user, game)
    start_run(
        user,
        run,
        TemporalValue.from_day(DAY),
        implies_status=False,
        correlation_id=new_correlation_id(),
    )

    def refuse(*args, **kwargs):
        raise CommandFailed("That run is removed.", 409)

    monkeypatch.setattr(log_game_writes, "restate_run", refuse)

    with pytest.raises(LogRefused) as refused:
        _press(user, _statement(game, started=None, note="Kept"))

    run.refresh_from_db()
    assert stated_start(run) is None
    assert refused.value.step == "dates"
    assert "dates" in refused.value.written


def test_a_run_of_another_game_is_refused(user, game):
    _tracked(user, game)
    other = Game.objects.create(library=user.library, name="Other")
    other_run = _tracked(user, other)

    with pytest.raises(LogRefused) as refused:
        _press(user, _statement(game, run_id=other_run.pk, started=_day(DAY)))

    assert refused.value.failure.message == PICKED_RUN_GONE


def test_a_run_removed_before_the_press_refuses_its_dates_and_no_copy(user, game, pc):
    run = _tracked(user, game)
    another_run(user, game)
    remove_run(user, run, correlation_id=new_correlation_id())

    with pytest.raises(LogRefused) as refused:
        _press(
            user,
            _statement(game, run_id=run.pk, platform=pc.pk, started=_day(DAY)),
        )

    assert refused.value.step == "dates"
    assert not LibraryEntry.objects.filter(library=user.library).exists()


def test_a_platform_removed_before_the_press_refuses_and_writes_nothing(user, game, pc):
    Platform.objects.filter(pk=pc.pk).update(removed_at=timezone.now())

    with pytest.raises(LogRefused) as refused:
        _press(user, _statement(game, platform=pc.pk))

    assert refused.value.step == "platform"
    assert not PlayerGame.objects.filter(library=user.library, game=game).exists()
    assert not LibraryEntry.objects.filter(library=user.library).exists()


def test_a_shared_game_with_a_standing_release_records_an_unknown_copy_on_it(
    user, pc, owned_library
):
    shared = Game.objects.create(library=owned_library, name="Shared Game")
    standing = default_graph(shared, owned_library, platform=pc).release
    Game.objects.filter(pk=shared.pk).update(library=None)
    shared.refresh_from_db()

    _press(user, _statement(shared, platform=pc.pk))

    entry = LibraryEntry.objects.get(library=user.library)
    assert entry.release == standing
    assert (entry.access, entry.format) == ("unknown", "unknown")


def test_a_correlation_id_marks_every_event_the_press_appended(user, game, pc):
    before = LibraryEvent.objects.filter(library=user.library).count()
    correlation_id = new_correlation_id()

    _press(
        user,
        _statement(
            game,
            platform=pc.pk,
            started=_day(DAY),
            note="Saved the crew",
            playtime=_session_timing(),
            mastered=True,
            status=PlayerGameStatus.SHELVED,
        ),
        correlation_id=correlation_id,
    )

    appended = LibraryEvent.objects.filter(library=user.library).count() - before
    marked = LibraryEvent.objects.filter(
        library=user.library, correlation_id=correlation_id
    ).count()
    assert appended > 1
    assert marked == appended


def test_a_refused_status_after_a_write_keeps_the_write(user, game, monkeypatch):
    _tracked(user, game)

    def refuse(*args, **kwargs):
        raise CommandFailed("That game is removed.", 409)

    monkeypatch.setattr(log_game_writes, "record_facts", refuse)

    with pytest.raises(LogRefused) as refused:
        _press(user, _statement(game, note="Kept", status=PlayerGameStatus.SHELVED))

    assert refused.value.step == "status"
    assert refused.value.written == frozenset({"note"})


def test_a_refused_mastered_names_mastered_and_a_note_names_the_note(
    user, game, monkeypatch
):
    _tracked(user, game)

    def refuse(*args, **kwargs):
        raise CommandFailed("That game is removed.", 409)

    monkeypatch.setattr(log_game_writes, "record_facts", refuse)
    with pytest.raises(LogRefused) as mastered:
        _press(user, _statement(game, mastered=True))
    assert mastered.value.step == "mastered"

    monkeypatch.setattr(log_game_writes, "restate_run", refuse)
    with pytest.raises(LogRefused) as note:
        _press(user, _statement(game, note="Kept"))
    assert note.value.step == "note"


def test_a_refused_platform_lookup_names_the_game_gone(user, game, pc, monkeypatch):
    _tracked(user, game)

    def gone(*args, **kwargs):
        raise Http404("No such game.")

    monkeypatch.setattr(log_game_writes, "release_on", gone)

    with pytest.raises(LogRefused) as refused:
        _press(user, _statement(game, platform=pc.pk))

    assert refused.value.step == "platform"
    assert refused.value.failure.message == GAME_GONE


def test_a_row_gone_at_the_lookup_names_the_game_gone(user, game, pc, monkeypatch):
    _tracked(user, game)

    def gone(*args, **kwargs):
        raise RowNotHeld("Game is gone.")

    monkeypatch.setattr(log_game_writes, "release_on", gone)

    with pytest.raises(LogRefused) as refused:
        _press(user, _statement(game, platform=pc.pk))

    assert refused.value.failure.message == GAME_GONE
