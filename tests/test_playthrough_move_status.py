"""The status a moved run implies on its new game."""

import uuid

import pytest
from django.contrib.messages import get_messages
from django.urls import reverse

from games.commands.playergame import TrackGame
from games.commands.playthrough import ActStatement, CreatePlaythrough
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
from games.writes.playergame import new_correlation_id, record_facts
from games.writes.playthrough import RunDraft, restate_run
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


def _set_status(user, game, status):
    record_facts(user, game, status=status, correlation_id=new_correlation_id())


def test_a_completed_run_completes_the_target(owned_user, base, dlc):
    run = _run_at(owned_user, base, started="2024-01-02", completed="2024-02-03")

    moved = _move(owned_user, run, dlc)

    assert _status(owned_user, dlc) == PlayerGameStatus.COMPLETED
    assert moved is not None
    assert moved.stated_status == PlayerGameStatus.COMPLETED
    assert moved.status_refusal is None


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
    assert moved.stated_status == PlayerGameStatus.PLAYED


def test_a_started_run_leaves_a_stronger_status(owned_user, base, dlc):
    _set_status(owned_user, dlc, PlayerGameStatus.ABANDONED)
    run = _run_at(owned_user, base, started="2024-01-02")

    moved = _move(owned_user, run, dlc)

    assert _status(owned_user, dlc) == PlayerGameStatus.ABANDONED
    assert moved is not None
    assert moved.stated_status is None


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
    assert moved.stated_status is None
    assert not LibraryEvent.objects.filter(event_type=STATUS_CHANGED).exists()


def test_a_target_already_completed_states_nothing(owned_user, base, dlc):
    _set_status(owned_user, dlc, PlayerGameStatus.COMPLETED)
    run = _run_at(owned_user, base, completed="2024-02-03")

    moved = _move(owned_user, run, dlc)

    assert moved is not None
    assert moved.stated_status is None


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
    status_event = LibraryEvent.objects.get(
        event_type=STATUS_CHANGED,
        aggregate_id=PlayerGame.objects.get(game=dlc).pk,
    )
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

    assert [str(message) for message in get_messages(response.wsgi_request)] == [
        (
            "Moved to Separate Ways. Its empty playthrough was removed. "
            "Separate Ways is now Played."
        )
    ]


def test_a_refused_status_keeps_the_move_and_toasts(
    client, owned_user, base, dlc, monkeypatch
):
    run = _run_at(owned_user, base, completed="2024-02-03")
    refusal = CommandFailed("Restore the game first.", CONFLICT_STATUS)

    def refuse(*arguments, **facts):
        raise refusal

    monkeypatch.setattr("games.writes.implied_status.record_facts", refuse)
    client.force_login(owned_user)

    response = client.post(
        reverse("games:edit_playthrough", args=[run.pk]),
        {"game": str(dlc.pk), "started": "", "ended": "2024-02-03", "note": ""},
    )

    run.refresh_from_db()
    assert run.player_game.game == dlc
    assert response.status_code == 302
    assert [str(message) for message in get_messages(response.wsgi_request)] == [
        "Moved to Separate Ways. Its empty playthrough was removed.",
        "Restore the game first.",
    ]
