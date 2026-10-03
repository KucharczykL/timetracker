"""The status a moved run implies on its new game."""

import uuid

import pytest
from django.contrib.messages import get_messages
from django.urls import reverse

from games.commands.playergame import TrackGame
from games.commands.playthrough import ActStatement, CreatePlaythrough
from games.events.append import StreamSequenceMismatch
from games.events.dispatch import dispatch
from games.models import (
    Game,
    LibraryEvent,
    PlayerGame,
    PlayerGameStatus,
    Playthrough,
    PlaythroughKind,
)
from games.writes.answers import CONFLICT_STATUS, CommandFailed
from games.writes.implied_status import StatusStated
from games.writes.playergame import new_correlation_id, record_facts
from games.writes.playthrough import MovedThenFailed, RunDraft, restate_run
from timetracker.temporal import TemporalValue

pytestmark = [
    pytest.mark.untracked_games,
    pytest.mark.django_db(transaction=True),
]

STATUS_CHANGED = "library.playergame.status_changed"
MOVED = "library.playthrough.moved"


def _dispatch(user, command):
    return dispatch(
        command,
        actor=user,
        library=user.library,
        idempotency_key=str(uuid.uuid7()),
    )


def _game(user, name, *, tracked=True):
    game = Game.objects.create(library=user.library, name=name)
    if tracked:
        _dispatch(user, TrackGame(game_id=game.pk))
    return game


@pytest.fixture
def base(owned_user):
    return _game(owned_user, "Resident Evil 4")


@pytest.fixture
def dlc(owned_user):
    return _game(owned_user, "Separate Ways")


def _act(day):
    return ActStatement(TemporalValue.parse(day))


def _run_at(user, game, *, started=None, completed=None):
    """A second run, so the source keeps one."""
    held = set(
        Playthrough.objects.filter(player_game__game=game).values_list("pk", flat=True)
    )
    _dispatch(
        user,
        CreatePlaythrough(
            game_id=game.pk,
            started=None if started is None else _act(started),
            completed=None if completed is None else _act(completed),
            note="",
        ),
    )
    return Playthrough.objects.exclude(pk__in=held).get(
        player_game__game=game, kind=PlaythroughKind.ORDINARY
    )


def _move(user, run, game):
    return restate_run(
        user,
        run,
        RunDraft(started=None, completed=None, note=run.note, game_id=game.pk),
        correlation_id=new_correlation_id(),
    )


def _status(user, game):
    return PlayerGame.objects.get(library=user.library, game=game).status


def _status_events(game):
    return LibraryEvent.objects.filter(
        event_type=STATUS_CHANGED,
        aggregate_id=PlayerGame.objects.get(game=game).pk,
    )


def _refuse_the_status(monkeypatch):
    """A collision, as the status write answers one."""

    def refuse(*arguments, **facts):
        raise CommandFailed(
            "Another change reached this game first.", CONFLICT_STATUS
        ) from StreamSequenceMismatch(expected=1, actual=2)

    monkeypatch.setattr("games.writes.implied_status.record_facts", refuse)


def _toasts(response):
    return [str(message) for message in get_messages(response.wsgi_request)]


def _set_status(user, game, status):
    record_facts(user, game, status=status, correlation_id=new_correlation_id())


def test_a_completed_run_completes_the_target(owned_user, base, dlc):
    run = _run_at(owned_user, base, started="2024-01-02", completed="2024-02-03")

    moved = _move(owned_user, run, dlc)

    assert _status(owned_user, dlc) == PlayerGameStatus.COMPLETED
    assert moved is not None
    assert moved.status == StatusStated(PlayerGameStatus.COMPLETED)


def test_the_source_keeps_its_status(owned_user, base, dlc):
    run = _run_at(owned_user, base, completed="2024-02-03")
    _set_status(owned_user, base, PlayerGameStatus.COMPLETED)

    _move(owned_user, run, dlc)

    assert _status(owned_user, base) == PlayerGameStatus.COMPLETED


def test_a_started_run_plays_an_unplayed_target(owned_user, base, dlc):
    run = _run_at(owned_user, base, started="2024-01-02")

    moved = _move(owned_user, run, dlc)

    assert _status(owned_user, dlc) == PlayerGameStatus.PLAYED
    assert moved is not None
    assert moved.status == StatusStated(PlayerGameStatus.PLAYED)


def test_a_started_run_leaves_a_stronger_status(owned_user, base, dlc):
    _set_status(owned_user, dlc, PlayerGameStatus.ABANDONED)
    run = _run_at(owned_user, base, started="2024-01-02")

    moved = _move(owned_user, run, dlc)

    assert _status(owned_user, dlc) == PlayerGameStatus.ABANDONED
    assert moved is not None
    assert moved.status is None


def test_a_completed_run_completes_over_a_stronger_status(owned_user, base, dlc):
    """The completion states Completed every time."""
    _set_status(owned_user, dlc, PlayerGameStatus.ABANDONED)
    run = _run_at(owned_user, base, completed="2024-02-03")

    _move(owned_user, run, dlc)

    assert _status(owned_user, dlc) == PlayerGameStatus.COMPLETED


def test_a_run_without_endpoints_implies_nothing(owned_user, base, dlc):
    run = _run_at(owned_user, base)

    moved = _move(owned_user, run, dlc)

    assert _status(owned_user, dlc) == PlayerGameStatus.UNPLAYED
    assert moved is not None
    assert moved.status is None
    assert not LibraryEvent.objects.filter(event_type=STATUS_CHANGED).exists()


def test_a_target_already_completed_states_nothing(owned_user, base, dlc):
    _set_status(owned_user, dlc, PlayerGameStatus.COMPLETED)
    run = _run_at(owned_user, base, completed="2024-02-03")

    moved = _move(owned_user, run, dlc)

    assert moved is not None
    assert moved.status is None
    assert _status_events(dlc).count() == 1


def test_an_untracked_target_is_tracked_then_played(owned_user, base):
    target = _game(owned_user, "Echoes of the Eye", tracked=False)
    run = _run_at(owned_user, base, started="2024-01-02")

    moved = _move(owned_user, run, target)

    assert moved is not None
    assert moved.tracked_the_target
    assert _status(owned_user, target) == PlayerGameStatus.PLAYED


def test_the_status_is_keyed_and_correlated_from_the_move(owned_user, base, dlc):
    run = _run_at(owned_user, base, completed="2024-02-03")

    _move(owned_user, run, dlc)

    moved_event = LibraryEvent.objects.get(event_type=MOVED, aggregate_id=run.pk)
    status_event = _status_events(dlc).get()
    assert status_event.correlation_id == moved_event.correlation_id
    assert status_event.idempotency_key == f"{moved_event.idempotency_key}-status"


def test_a_patch_moving_a_completed_run_completes_the_target(
    client, owned_user, base, dlc
):
    run = _run_at(owned_user, base, completed="2024-02-03")
    client.force_login(owned_user)

    response = client.patch(
        f"/api/playthrough/{run.pk}",
        {"game_id": str(dlc.pk)},
        content_type="application/json",
    )

    assert response.status_code == 204
    assert _status(owned_user, dlc) == PlayerGameStatus.COMPLETED
    assert _status(owned_user, base) == PlayerGameStatus.UNPLAYED


def test_the_edit_toast_names_the_status(client, owned_user, base, dlc):
    run = _run_at(owned_user, base, started="2024-01-02")
    client.force_login(owned_user)

    response = client.post(
        reverse("games:edit_playthrough", args=[run.pk]),
        {"game": str(dlc.pk), "started": "2024-01-02", "ended": "", "note": ""},
    )

    assert _toasts(response) == [
        (
            "Moved to Separate Ways. Its empty playthrough was removed. "
            "Separate Ways is now Played."
        )
    ]


def test_a_target_already_played_states_nothing(owned_user, base, dlc):
    _set_status(owned_user, dlc, PlayerGameStatus.PLAYED)
    run = _run_at(owned_user, base, started="2024-01-02")

    moved = _move(owned_user, run, dlc)

    assert moved is not None
    assert moved.status is None
    assert _status_events(dlc).count() == 1


def test_a_second_post_moves_and_states_once(owned_user, base, dlc):
    run = _run_at(owned_user, base, completed="2024-02-03")
    draft = RunDraft(started=None, completed=None, note="", game_id=dlc.pk)

    restate_run(owned_user, run, draft, correlation_id=new_correlation_id())
    again = restate_run(owned_user, run, draft, correlation_id=new_correlation_id())

    assert again is None
    assert LibraryEvent.objects.filter(event_type=MOVED).count() == 1
    assert _status_events(dlc).count() == 1


def test_the_edit_toast_names_completed(client, owned_user, base, dlc):
    run = _run_at(owned_user, base, completed="2024-02-03")
    client.force_login(owned_user)

    response = client.post(
        reverse("games:edit_playthrough", args=[run.pk]),
        {"game": str(dlc.pk), "started": "", "ended": "2024-02-03", "note": ""},
    )

    assert _toasts(response) == [
        (
            "Moved to Separate Ways. Its empty playthrough was removed. "
            "Separate Ways is now Completed."
        )
    ]


def test_the_played_box_never_undoes_a_moved_completion(client, owned_user, base, dlc):
    """The box was offered before the move stated Completed."""
    run = _run_at(owned_user, base, completed="2024-02-03")
    client.force_login(owned_user)

    client.post(
        reverse("games:edit_playthrough", args=[run.pk]),
        {
            "game": str(dlc.pk),
            "started": "2024-01-02",
            "ended": "2024-02-03",
            "note": "",
            "also_mark_played": "on",
        },
    )

    assert _status(owned_user, dlc) == PlayerGameStatus.COMPLETED


def test_a_refused_status_keeps_the_move_and_toasts(
    client, owned_user, base, dlc, monkeypatch
):
    run = _run_at(owned_user, base, completed="2024-02-03")
    _refuse_the_status(monkeypatch)
    client.force_login(owned_user)

    response = client.post(
        reverse("games:edit_playthrough", args=[run.pk]),
        {"game": str(dlc.pk), "started": "", "ended": "2024-02-03", "note": ""},
    )

    run.refresh_from_db()
    assert run.player_game.game == dlc
    assert response.status_code == 302
    assert _toasts(response) == [
        "Moved to Separate Ways. Its empty playthrough was removed.",
        (
            "Separate Ways could not be marked Completed. Set its status on "
            "the game's page."
        ),
    ]


def test_a_patch_logs_a_refused_status(
    client, owned_user, base, dlc, monkeypatch, capture_games_logger
):
    run = _run_at(owned_user, base, completed="2024-02-03")
    _refuse_the_status(monkeypatch)
    client.force_login(owned_user)

    with capture_games_logger() as caplog:
        response = client.patch(
            f"/api/playthrough/{run.pk}",
            {"game_id": str(dlc.pk)},
            content_type="application/json",
        )

    assert response.status_code == 204
    run.refresh_from_db()
    assert run.player_game.game == dlc
    (record,) = [
        record for record in caplog.records if "was not marked" in record.message
    ]
    assert str(run.pk) in record.message
    assert "completed" in record.message
    assert record.exc_info is not None


def test_a_status_defect_after_the_move_names_the_move(
    client, owned_user, base, dlc, monkeypatch
):
    run = _run_at(owned_user, base, completed="2024-02-03")

    def fail(*arguments, **facts):
        raise CommandFailed("The database refused the statement.", 500)

    monkeypatch.setattr("games.writes.implied_status.record_facts", fail)
    client.force_login(owned_user)

    response = client.post(
        reverse("games:edit_playthrough", args=[run.pk]),
        {"game": str(dlc.pk), "started": "", "ended": "2024-02-03", "note": ""},
    )

    assert response.status_code == 500
    run.refresh_from_db()
    assert run.player_game.game == dlc
    assert _toasts(response) == [
        "Moved to Separate Ways. Its empty playthrough was removed.",
        "The database refused the statement.",
    ]


def test_a_refused_restatement_after_the_move_carries_it(owned_user, base, dlc):
    """The draft's start is refused: the run already states one."""
    run = _run_at(owned_user, base, started="2024-01-02")

    with pytest.raises(MovedThenFailed) as refused:
        restate_run(
            owned_user,
            run,
            RunDraft(
                started=None,
                completed=_act("2023-01-01"),
                note="",
                game_id=dlc.pk,
            ),
            correlation_id=new_correlation_id(),
        )

    assert refused.value.moved.target == dlc
    assert refused.value.moved.status == StatusStated(PlayerGameStatus.PLAYED)
