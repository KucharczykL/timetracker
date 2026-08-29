"""A game's history off the event stream."""

from datetime import timedelta

import pytest
from django.utils import timezone

from games.backfill.playergame import backfill_game
from games.models import Game, GameStatusChange, PlayerGame, PlayerGameStatus
from games.reads.playergame_history import StatusEntry, status_history
from games.writes.playergame import new_correlation_id, record_facts, track_game

pytestmark = pytest.mark.untracked_games


def backdate(game, created_at):
    """created_at is auto_now_add: move it with UPDATE."""
    Game.objects.filter(pk=game.pk).update(created_at=created_at)
    game.refresh_from_db()
    return game


def state(actor, game, status):
    """The live write path a user reaches."""
    record_facts(actor, game, status=status, correlation_id=new_correlation_id())


@pytest.mark.django_db(transaction=True)
def test_an_untracked_game_has_no_history(owned_user, owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")

    assert status_history(owned_library, game) == []


@pytest.mark.django_db(transaction=True)
def test_a_tracked_game_with_no_transition_has_no_history(owned_user, owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    track_game(owned_user, game, correlation_id=new_correlation_id())

    assert PlayerGame.objects.filter(library=owned_library, game=game).exists()
    assert status_history(owned_library, game) == []


@pytest.mark.django_db(transaction=True)
def test_each_entry_follows_the_one_before_it(owned_user, owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    track_game(owned_user, game, correlation_id=new_correlation_id())
    state(owned_user, game, PlayerGameStatus.PLAYED)
    state(owned_user, game, PlayerGameStatus.ABANDONED)
    state(owned_user, game, PlayerGameStatus.COMPLETED)

    entries = status_history(owned_library, game)

    #: Newest first, as the page shows them.
    assert [(entry.previous, entry.current) for entry in entries] == [
        (PlayerGameStatus.ABANDONED, PlayerGameStatus.COMPLETED),
        (PlayerGameStatus.PLAYED, PlayerGameStatus.ABANDONED),
        (PlayerGameStatus.UNPLAYED, PlayerGameStatus.PLAYED),
    ]


@pytest.mark.django_db(transaction=True)
def test_the_first_transition_follows_unplayed(owned_user, owned_library):
    #: The creation event states no status.
    game = Game.objects.create(
        library=owned_library, name="Outer Wilds", status=Game.Status.FINISHED
    )
    track_game(owned_user, game, correlation_id=new_correlation_id())
    state(owned_user, game, PlayerGameStatus.COMPLETED)

    entry = status_history(owned_library, game)[0]
    assert (entry.previous, entry.current) == (
        PlayerGameStatus.UNPLAYED,
        PlayerGameStatus.COMPLETED,
    )


@pytest.mark.django_db(transaction=True)
def test_a_live_transition_shows_when_it_was_recorded(owned_user, owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    track_game(owned_user, game, correlation_id=new_correlation_id())
    before = timezone.now()
    state(owned_user, game, PlayerGameStatus.PLAYED)
    after = timezone.now()

    entry = status_history(owned_library, game)[0]

    assert entry.recorded_at is not None
    assert before <= entry.recorded_at <= after


@pytest.mark.django_db(transaction=True)
def test_a_dated_legacy_transition_keeps_its_time_of_day(owned_user, owned_library):
    #: effective_time stops at a day.
    added = timezone.now() - timedelta(days=500)
    changed = added + timedelta(days=9, hours=14, minutes=37)
    game = backdate(
        Game.objects.create(
            library=owned_library, name="Braid", status=Game.Status.PLAYED
        ),
        added,
    )
    GameStatusChange.objects.create(
        game=game, old_status="u", new_status="p", timestamp=changed
    )

    backfill_game(
        game, library=owned_library, actor=owned_user, run_time=timezone.now()
    )

    entry = status_history(owned_library, game)[0]
    assert entry.recorded_at == changed


@pytest.mark.django_db(transaction=True)
def test_an_undated_legacy_transition_shows_no_time(owned_user, owned_library):
    added = timezone.now() - timedelta(days=500)
    game = backdate(
        Game.objects.create(
            library=owned_library, name="Braid", status=Game.Status.PLAYED
        ),
        added,
    )
    GameStatusChange.objects.create(
        game=game, old_status="u", new_status="p", timestamp=None
    )

    backfill_game(
        game, library=owned_library, actor=owned_user, run_time=timezone.now()
    )

    assert status_history(owned_library, game) == [
        StatusEntry(
            recorded_at=None,
            previous=PlayerGameStatus.UNPLAYED,
            current=PlayerGameStatus.PLAYED,
        )
    ]


@pytest.mark.django_db(transaction=True)
def test_the_chain_follows_the_stream_not_the_clock(owned_user, owned_library):
    #: recorded_at runs backwards through a mixed stream.
    added = timezone.now() - timedelta(days=500)
    game = backdate(
        Game.objects.create(
            library=owned_library, name="Hollow Knight", status=Game.Status.FINISHED
        ),
        added,
    )
    GameStatusChange.objects.create(
        game=game, old_status="p", new_status="f", timestamp=added + timedelta(days=9)
    )
    GameStatusChange.objects.create(
        game=game, old_status="u", new_status="p", timestamp=None
    )

    backfill_game(
        game, library=owned_library, actor=owned_user, run_time=timezone.now()
    )

    entries = status_history(owned_library, game)
    assert [(entry.previous, entry.current) for entry in entries] == [
        (PlayerGameStatus.PLAYED, PlayerGameStatus.COMPLETED),
        (PlayerGameStatus.UNPLAYED, PlayerGameStatus.PLAYED),
    ]
    #: The undated one is older, and undated.
    assert [entry.recorded_at is None for entry in entries] == [False, True]


@pytest.mark.django_db(transaction=True)
def test_the_backfills_corrective_transition_shows_no_time(owned_user, owned_library):
    #: The corrective event carries no status_change_id, so
    #: reading source_metadata would show the run time.
    added = timezone.now() - timedelta(days=500)
    game = backdate(
        Game.objects.create(
            library=owned_library, name="Braid", status=Game.Status.FINISHED
        ),
        added,
    )

    counts = backfill_game(
        game, library=owned_library, actor=owned_user, run_time=timezone.now()
    )

    assert counts.corrective_events == 1
    assert status_history(owned_library, game) == [
        StatusEntry(
            recorded_at=None,
            previous=PlayerGameStatus.UNPLAYED,
            current=PlayerGameStatus.COMPLETED,
        )
    ]


@pytest.mark.django_db(transaction=True)
def test_a_library_reads_only_its_own_transitions(
    owned_user, owned_library, django_user_model
):
    #: A shared game both libraries track.
    game = Game.objects.create(name="Outer Wilds")
    other_user = django_user_model.objects.create_user(
        username="other-owner", password="p"
    )
    other_library = other_user.library
    track_game(owned_user, game, correlation_id=new_correlation_id())
    track_game(other_user, game, correlation_id=new_correlation_id())
    state(owned_user, game, PlayerGameStatus.PLAYED)
    state(other_user, game, PlayerGameStatus.ABANDONED)
    state(other_user, game, PlayerGameStatus.COMPLETED)

    assert [entry.current for entry in status_history(owned_library, game)] == [
        PlayerGameStatus.PLAYED
    ]
    assert [entry.current for entry in status_history(other_library, game)] == [
        PlayerGameStatus.COMPLETED,
        PlayerGameStatus.ABANDONED,
    ]
