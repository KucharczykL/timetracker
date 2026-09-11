"""A game's history off the event stream."""

from datetime import timedelta

import pytest
from django.utils import timezone

from games.events.playergame import PLAYERGAME_STATUS_CHANGED
from games.models import Game, LibraryEvent, PlayerGame, PlayerGameStatus
from games.reads.playergame_history import StatusEntry, status_history
from games.writes.playergame import new_correlation_id, record_facts, track_game

pytestmark = pytest.mark.untracked_games


def state(actor, game, status):
    """The live write path a user reaches."""
    record_facts(actor, game, status=status, correlation_id=new_correlation_id())


def status_events(library):
    """This library's transition events, in stream order.

    A transition a data pass recorded states its own
    instant, and an unknown effective_time where nobody
    wrote the day down. Nothing appends such an event any
    more, so a test states one by coarsening a real one.
    """
    return LibraryEvent.objects.filter(
        library=library, event_type=PLAYERGAME_STATUS_CHANGED.event_type
    ).order_by("sequence")


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
def test_a_transition_recorded_out_of_band_keeps_its_own_time(
    owned_user, owned_library
):
    """The entry reads the event's instant, not the clock."""
    changed = timezone.now() - timedelta(days=491, hours=14, minutes=37)
    game = Game.objects.create(library=owned_library, name="Braid")
    track_game(owned_user, game, correlation_id=new_correlation_id())
    state(owned_user, game, PlayerGameStatus.PLAYED)
    status_events(owned_library).update(recorded_at=changed)

    entry = status_history(owned_library, game)[0]
    assert entry.recorded_at == changed


@pytest.mark.django_db(transaction=True)
def test_a_transition_stating_no_effective_time_shows_no_time(
    owned_user, owned_library
):
    """An unknown day is no day, not the append time."""
    game = Game.objects.create(library=owned_library, name="Braid")
    track_game(owned_user, game, correlation_id=new_correlation_id())
    state(owned_user, game, PlayerGameStatus.PLAYED)
    status_events(owned_library).update(effective_time=None)

    assert status_history(owned_library, game) == [
        StatusEntry(
            recorded_at=None,
            previous=PlayerGameStatus.UNPLAYED,
            current=PlayerGameStatus.PLAYED,
        )
    ]


@pytest.mark.django_db(transaction=True)
def test_the_chain_follows_the_stream_not_the_clock(owned_user, owned_library):
    """recorded_at runs backwards through a mixed stream."""
    game = Game.objects.create(library=owned_library, name="Hollow Knight")
    track_game(owned_user, game, correlation_id=new_correlation_id())
    state(owned_user, game, PlayerGameStatus.PLAYED)
    state(owned_user, game, PlayerGameStatus.COMPLETED)
    older, newer = status_events(owned_library)
    #: The older transition states no day and was appended
    #: last; the newer one states the day it happened.
    status_events(owned_library).filter(pk=older.pk).update(
        effective_time=None, recorded_at=timezone.now()
    )
    status_events(owned_library).filter(pk=newer.pk).update(
        recorded_at=timezone.now() - timedelta(days=491)
    )

    entries = status_history(owned_library, game)
    assert [(entry.previous, entry.current) for entry in entries] == [
        (PlayerGameStatus.PLAYED, PlayerGameStatus.COMPLETED),
        (PlayerGameStatus.UNPLAYED, PlayerGameStatus.PLAYED),
    ]
    #: The undated one is older, and undated.
    assert [entry.recorded_at is None for entry in entries] == [False, True]


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
