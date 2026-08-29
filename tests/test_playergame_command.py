"""Dispatching the command that tracks a game."""

import uuid

import pytest
from django.utils import timezone

from games.commands.playergame import (
    PlayerGameNotTracked,
    RecordPlayerGameFacts,
    RemovePlayerGame,
    RestorePlayerGame,
    SetPlayerGameExcludedFromUnfinished,
    SetPlayerGameMastered,
    SetPlayerGameStatus,
    TrackGame,
)
from games.events.dispatch import CommandOutcome, CommandRejected, dispatch
from games.models import Game, LibraryEvent, PlayerGame, PlayerGameStatus
from games.retention import Retirement, purging_library, tombstone_or_delete
from timetracker.temporal import TemporalValue

pytestmark = pytest.mark.untracked_games


@pytest.fixture
def other_user(django_user_model, db):
    return django_user_model.objects.create_user(username="other-owner", password="p")


@pytest.fixture
def other_library(other_user):
    return other_user.library


@pytest.fixture
def shared_game(db):
    #: No library: the shared catalog.
    return Game.objects.create(name="Outer Wilds")


@pytest.mark.django_db(transaction=True)
def test_tracking_a_game_records_it_and_projects_it(owned_user, owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")

    result = dispatch(
        TrackGame(game_id=game.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="track-outer-wilds",
    )

    assert result.outcome is CommandOutcome.APPENDED
    event = LibraryEvent.objects.get(library=owned_library)
    assert event.event_type == "library.playergame.created"
    assert event.payload["game"]["id"] == str(game.pk)

    row = PlayerGame.objects.get()
    assert (row.pk, row.game_id, row.library_id) == (
        event.aggregate_id,
        game.pk,
        owned_library.pk,
    )


@pytest.mark.django_db(transaction=True)
def test_two_libraries_track_one_shared_game_independently(
    owned_user, owned_library, other_user, other_library, shared_game
):
    for actor, library in ((owned_user, owned_library), (other_user, other_library)):
        dispatch(
            TrackGame(game_id=shared_game.pk),
            actor=actor,
            library=library,
            idempotency_key="track-shared",
        )

    assert PlayerGame.objects.filter(game=shared_game).count() == 2
    assert PlayerGame.objects.filter(library=owned_library).count() == 1
    #: One shared row, two private facts.
    assert Game.objects.filter(pk=shared_game.pk).count() == 1


@pytest.mark.django_db(transaction=True)
def test_another_librarys_private_game_cannot_be_tracked(
    owned_user, owned_library, other_library
):
    theirs = Game.objects.create(library=other_library, name="Their Secret")

    with pytest.raises(CommandRejected):
        dispatch(
            TrackGame(game_id=theirs.pk),
            actor=owned_user,
            library=owned_library,
            idempotency_key="track-theirs",
        )

    assert not PlayerGame.objects.exists()
    assert not LibraryEvent.objects.exists()


@pytest.mark.django_db(transaction=True)
def test_a_tombstoned_game_cannot_be_tracked(owned_user, owned_library):
    from django.utils import timezone

    game = Game.objects.create(
        library=owned_library, name="Retired", removed_at=timezone.now()
    )

    with pytest.raises(CommandRejected):
        dispatch(
            TrackGame(game_id=game.pk),
            actor=owned_user,
            library=owned_library,
            idempotency_key="track-retired",
        )


@pytest.mark.django_db(transaction=True)
def test_a_game_nobody_has_cannot_be_tracked(owned_user, owned_library):
    with pytest.raises(CommandRejected):
        dispatch(
            TrackGame(game_id=uuid.uuid7()),
            actor=owned_user,
            library=owned_library,
            idempotency_key="track-nothing",
        )


@pytest.mark.django_db(transaction=True)
def test_tracking_the_same_game_twice_changes_nothing(owned_user, owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    dispatch(
        TrackGame(game_id=game.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="track-first",
    )

    #: A different key: a second intent, not a repeated delivery.
    result = dispatch(
        TrackGame(game_id=game.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="track-again",
    )

    assert result.outcome is CommandOutcome.UNCHANGED
    assert PlayerGame.objects.count() == 1


@pytest.mark.django_db(transaction=True)
def test_repeating_the_key_replays_rather_than_tracking_twice(
    owned_user, owned_library
):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    command = TrackGame(game_id=game.pk)
    first = dispatch(
        command, actor=owned_user, library=owned_library, idempotency_key="once"
    )
    second = dispatch(
        command, actor=owned_user, library=owned_library, idempotency_key="once"
    )

    assert second.outcome is CommandOutcome.REPLAYED
    assert second.sequences == first.sequences
    assert PlayerGame.objects.count() == 1


@pytest.mark.django_db(transaction=True)
def test_purging_the_library_takes_the_tracked_row_with_it(owned_user, owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    dispatch(
        TrackGame(game_id=game.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="track",
    )

    #: A purge collects everything in one cascade.
    with purging_library():
        owned_user.delete()

    assert not PlayerGame.objects.exists()


def track(actor, library, game):
    """The command this library must run first."""
    dispatch(
        TrackGame(game_id=game.pk),
        actor=actor,
        library=library,
        idempotency_key=f"track-{game.pk}",
    )


@pytest.mark.django_db(transaction=True)
def test_setting_a_status_records_it_and_projects_it(owned_user, owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    track(owned_user, owned_library, game)

    dispatch(
        SetPlayerGameStatus(game_id=game.pk, status=PlayerGameStatus.COMPLETED),
        actor=owned_user,
        library=owned_library,
        idempotency_key="complete-outer-wilds",
    )

    event = LibraryEvent.objects.get(event_type="library.playergame.status_changed")
    assert event.payload == {"status": "completed"}
    row = PlayerGame.objects.get()
    assert event.aggregate_id == row.pk
    assert row.status == PlayerGameStatus.COMPLETED


@pytest.mark.django_db(transaction=True)
def test_a_live_status_change_states_the_day_it_happened(owned_user, owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    track(owned_user, owned_library, game)

    dispatch(
        SetPlayerGameStatus(game_id=game.pk, status=PlayerGameStatus.COMPLETED),
        actor=owned_user,
        library=owned_library,
        idempotency_key="complete-outer-wilds",
    )

    event = LibraryEvent.objects.get(event_type="library.playergame.status_changed")
    #: None would mean nobody knows when.
    assert event.effective_time == TemporalValue.from_day(timezone.localdate())


@pytest.mark.django_db(transaction=True)
def test_a_recorded_status_fact_states_the_day_too(owned_user, owned_library):
    #: The game form dispatches this one.
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    track(owned_user, owned_library, game)

    dispatch(
        RecordPlayerGameFacts(
            game_id=game.pk, status=PlayerGameStatus.PLAYED, mastered=None
        ),
        actor=owned_user,
        library=owned_library,
        idempotency_key="play-outer-wilds",
    )

    event = LibraryEvent.objects.get(event_type="library.playergame.status_changed")
    assert event.effective_time == TemporalValue.from_day(timezone.localdate())


@pytest.mark.django_db(transaction=True)
def test_a_mastery_fact_still_states_no_time(owned_user, owned_library):
    #: Only the status event states a time.
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    track(owned_user, owned_library, game)

    dispatch(
        RecordPlayerGameFacts(game_id=game.pk, status=None, mastered=True),
        actor=owned_user,
        library=owned_library,
        idempotency_key="master-outer-wilds",
    )

    event = LibraryEvent.objects.get(event_type="library.playergame.mastered_changed")
    assert event.effective_time is None


@pytest.mark.django_db(transaction=True)
def test_a_status_leaves_the_rest_of_the_row_alone(owned_user, owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    track(owned_user, owned_library, game)
    before = PlayerGame.objects.get()

    dispatch(
        SetPlayerGameStatus(game_id=game.pk, status=PlayerGameStatus.PLAYED),
        actor=owned_user,
        library=owned_library,
        idempotency_key="play-outer-wilds",
    )

    after = PlayerGame.objects.get()
    assert (after.pk, after.game_id, after.tracked_at) == (
        before.pk,
        before.game_id,
        before.tracked_at,
    )


@pytest.mark.django_db(transaction=True)
def test_a_status_for_an_untracked_game_is_refused(owned_user, owned_library):
    game = Game.objects.create(library=owned_library, name="Untracked")

    with pytest.raises(CommandRejected, match="tracks no game"):
        dispatch(
            SetPlayerGameStatus(game_id=game.pk, status=PlayerGameStatus.PLAYED),
            actor=owned_user,
            library=owned_library,
            idempotency_key="play-untracked",
        )

    assert not LibraryEvent.objects.filter(
        event_type="library.playergame.status_changed"
    ).exists()


@pytest.mark.django_db(transaction=True)
def test_a_status_for_a_game_another_library_tracks_is_refused(
    owned_user, owned_library, other_user, other_library, shared_game
):
    track(other_user, other_library, shared_game)

    with pytest.raises(CommandRejected, match="tracks no game"):
        dispatch(
            SetPlayerGameStatus(game_id=shared_game.pk, status=PlayerGameStatus.PLAYED),
            actor=owned_user,
            library=owned_library,
            idempotency_key="play-theirs",
        )

    assert PlayerGame.objects.get().status == PlayerGameStatus.UNPLAYED


@pytest.mark.django_db(transaction=True)
def test_the_status_a_game_already_has_changes_nothing(owned_user, owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    track(owned_user, owned_library, game)

    result = dispatch(
        SetPlayerGameStatus(game_id=game.pk, status=PlayerGameStatus.UNPLAYED),
        actor=owned_user,
        library=owned_library,
        idempotency_key="unplay-outer-wilds",
    )

    assert result.outcome is CommandOutcome.UNCHANGED
    assert "already gives" in result.reason
    assert not LibraryEvent.objects.filter(
        event_type="library.playergame.status_changed"
    ).exists()


@pytest.mark.django_db(transaction=True)
def test_one_idempotency_key_records_one_status_change(owned_user, owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    track(owned_user, owned_library, game)
    command = SetPlayerGameStatus(game_id=game.pk, status=PlayerGameStatus.COMPLETED)

    first = dispatch(
        command, actor=owned_user, library=owned_library, idempotency_key="complete"
    )
    second = dispatch(
        command, actor=owned_user, library=owned_library, idempotency_key="complete"
    )

    assert (first.outcome, second.outcome) == (
        CommandOutcome.APPENDED,
        CommandOutcome.REPLAYED,
    )
    assert (
        LibraryEvent.objects.filter(
            event_type="library.playergame.status_changed"
        ).count()
        == 1
    )


@pytest.mark.django_db(transaction=True)
def test_mastering_a_game_records_it_and_projects_it(owned_user, owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    track(owned_user, owned_library, game)

    dispatch(
        SetPlayerGameMastered(game_id=game.pk, mastered=True),
        actor=owned_user,
        library=owned_library,
        idempotency_key="master-outer-wilds",
    )

    event = LibraryEvent.objects.get(event_type="library.playergame.mastered_changed")
    assert event.payload == {"mastered": True}
    row = PlayerGame.objects.get()
    assert event.aggregate_id == row.pk
    assert row.mastered is True


@pytest.mark.django_db(transaction=True)
def test_mastery_leaves_the_rest_of_the_row_alone(owned_user, owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    track(owned_user, owned_library, game)
    dispatch(
        SetPlayerGameStatus(game_id=game.pk, status=PlayerGameStatus.COMPLETED),
        actor=owned_user,
        library=owned_library,
        idempotency_key="complete-outer-wilds",
    )
    before = PlayerGame.objects.get()

    dispatch(
        SetPlayerGameMastered(game_id=game.pk, mastered=True),
        actor=owned_user,
        library=owned_library,
        idempotency_key="master-outer-wilds",
    )

    after = PlayerGame.objects.get()
    assert (after.pk, after.game_id, after.tracked_at, after.status) == (
        before.pk,
        before.game_id,
        before.tracked_at,
        PlayerGameStatus.COMPLETED,
    )


@pytest.mark.django_db(transaction=True)
def test_mastery_of_an_untracked_game_is_refused(owned_user, owned_library):
    game = Game.objects.create(library=owned_library, name="Untracked")

    with pytest.raises(CommandRejected, match="tracks no game"):
        dispatch(
            SetPlayerGameMastered(game_id=game.pk, mastered=True),
            actor=owned_user,
            library=owned_library,
            idempotency_key="master-untracked",
        )

    assert not LibraryEvent.objects.filter(
        event_type="library.playergame.mastered_changed"
    ).exists()


@pytest.mark.django_db(transaction=True)
def test_mastery_of_a_game_another_library_tracks_is_refused(
    owned_user, owned_library, other_user, other_library, shared_game
):
    track(other_user, other_library, shared_game)

    with pytest.raises(CommandRejected, match="tracks no game"):
        dispatch(
            SetPlayerGameMastered(game_id=shared_game.pk, mastered=True),
            actor=owned_user,
            library=owned_library,
            idempotency_key="master-theirs",
        )

    assert PlayerGame.objects.get().mastered is False


@pytest.mark.django_db(transaction=True)
def test_the_mastery_a_game_already_records_changes_nothing(owned_user, owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    track(owned_user, owned_library, game)

    result = dispatch(
        SetPlayerGameMastered(game_id=game.pk, mastered=False),
        actor=owned_user,
        library=owned_library,
        idempotency_key="unmaster-outer-wilds",
    )

    assert result.outcome is CommandOutcome.UNCHANGED
    assert "not mastered" in result.reason
    assert not LibraryEvent.objects.filter(
        event_type="library.playergame.mastered_changed"
    ).exists()


@pytest.mark.django_db(transaction=True)
def test_one_idempotency_key_records_one_mastery_change(owned_user, owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    track(owned_user, owned_library, game)
    command = SetPlayerGameMastered(game_id=game.pk, mastered=True)

    first = dispatch(
        command, actor=owned_user, library=owned_library, idempotency_key="master"
    )
    second = dispatch(
        command, actor=owned_user, library=owned_library, idempotency_key="master"
    )

    assert (first.outcome, second.outcome) == (
        CommandOutcome.APPENDED,
        CommandOutcome.REPLAYED,
    )
    assert (
        LibraryEvent.objects.filter(
            event_type="library.playergame.mastered_changed"
        ).count()
        == 1
    )


@pytest.mark.django_db(transaction=True)
def test_excluding_a_game_records_it_and_projects_it(owned_user, owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    track(owned_user, owned_library, game)

    dispatch(
        SetPlayerGameExcludedFromUnfinished(
            game_id=game.pk, excluded_from_unfinished=True
        ),
        actor=owned_user,
        library=owned_library,
        idempotency_key="exclude-outer-wilds",
    )

    event = LibraryEvent.objects.get(
        event_type="library.playergame.excluded_from_unfinished_changed"
    )
    assert event.payload == {"excluded_from_unfinished": True}
    row = PlayerGame.objects.get()
    assert event.aggregate_id == row.pk
    assert row.excluded_from_unfinished is True


@pytest.mark.django_db(transaction=True)
def test_an_exclusion_leaves_the_rest_of_the_row_alone(owned_user, owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    track(owned_user, owned_library, game)
    dispatch(
        SetPlayerGameMastered(game_id=game.pk, mastered=True),
        actor=owned_user,
        library=owned_library,
        idempotency_key="master-outer-wilds",
    )
    before = PlayerGame.objects.get()

    dispatch(
        SetPlayerGameExcludedFromUnfinished(
            game_id=game.pk, excluded_from_unfinished=True
        ),
        actor=owned_user,
        library=owned_library,
        idempotency_key="exclude-outer-wilds",
    )

    after = PlayerGame.objects.get()
    assert (after.pk, after.game_id, after.tracked_at, after.status) == (
        before.pk,
        before.game_id,
        before.tracked_at,
        before.status,
    )
    assert after.mastered is True


@pytest.mark.django_db(transaction=True)
def test_excluding_an_untracked_game_is_refused(owned_user, owned_library):
    game = Game.objects.create(library=owned_library, name="Untracked")

    with pytest.raises(CommandRejected, match="tracks no game"):
        dispatch(
            SetPlayerGameExcludedFromUnfinished(
                game_id=game.pk, excluded_from_unfinished=True
            ),
            actor=owned_user,
            library=owned_library,
            idempotency_key="exclude-untracked",
        )

    assert not LibraryEvent.objects.filter(
        event_type="library.playergame.excluded_from_unfinished_changed"
    ).exists()


@pytest.mark.django_db(transaction=True)
def test_excluding_a_game_another_library_tracks_is_refused(
    owned_user, owned_library, other_user, other_library, shared_game
):
    track(other_user, other_library, shared_game)

    with pytest.raises(CommandRejected, match="tracks no game"):
        dispatch(
            SetPlayerGameExcludedFromUnfinished(
                game_id=shared_game.pk, excluded_from_unfinished=True
            ),
            actor=owned_user,
            library=owned_library,
            idempotency_key="exclude-theirs",
        )

    assert PlayerGame.objects.get().excluded_from_unfinished is False


@pytest.mark.django_db(transaction=True)
def test_the_exclusion_a_game_already_records_changes_nothing(
    owned_user, owned_library
):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    track(owned_user, owned_library, game)

    result = dispatch(
        SetPlayerGameExcludedFromUnfinished(
            game_id=game.pk, excluded_from_unfinished=False
        ),
        actor=owned_user,
        library=owned_library,
        idempotency_key="include-outer-wilds",
    )

    assert result.outcome is CommandOutcome.UNCHANGED
    assert "included in" in result.reason
    assert not LibraryEvent.objects.filter(
        event_type="library.playergame.excluded_from_unfinished_changed"
    ).exists()


@pytest.mark.django_db(transaction=True)
def test_one_idempotency_key_records_one_exclusion_change(owned_user, owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    track(owned_user, owned_library, game)
    command = SetPlayerGameExcludedFromUnfinished(
        game_id=game.pk, excluded_from_unfinished=True
    )

    first = dispatch(
        command, actor=owned_user, library=owned_library, idempotency_key="exclude"
    )
    second = dispatch(
        command, actor=owned_user, library=owned_library, idempotency_key="exclude"
    )

    assert (first.outcome, second.outcome) == (
        CommandOutcome.APPENDED,
        CommandOutcome.REPLAYED,
    )
    assert (
        LibraryEvent.objects.filter(
            event_type="library.playergame.excluded_from_unfinished_changed"
        ).count()
        == 1
    )


@pytest.mark.django_db(transaction=True)
def test_removing_a_game_records_it_and_projects_it(owned_user, owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    track(owned_user, owned_library, game)

    dispatch(
        RemovePlayerGame(game_id=game.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="remove-outer-wilds",
    )

    event = LibraryEvent.objects.get(event_type="library.playergame.removed")
    assert event.payload == {}
    row = PlayerGame.objects.get()
    assert event.aggregate_id == row.pk
    assert row.removed_at == event.recorded_at


@pytest.mark.django_db(transaction=True)
def test_restoring_a_game_returns_it(owned_user, owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    track(owned_user, owned_library, game)
    dispatch(
        RemovePlayerGame(game_id=game.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="remove-outer-wilds",
    )

    dispatch(
        RestorePlayerGame(game_id=game.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="restore-outer-wilds",
    )

    assert LibraryEvent.objects.get(event_type="library.playergame.restored")
    assert PlayerGame.objects.get().removed_at is None


@pytest.mark.django_db(transaction=True)
def test_removing_a_game_leaves_the_rest_of_the_row_alone(owned_user, owned_library):
    """A restore gives back the game the library had."""
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    track(owned_user, owned_library, game)
    dispatch(
        SetPlayerGameStatus(game_id=game.pk, status=PlayerGameStatus.PLAYED),
        actor=owned_user,
        library=owned_library,
        idempotency_key="play-outer-wilds",
    )
    dispatch(
        SetPlayerGameMastered(game_id=game.pk, mastered=True),
        actor=owned_user,
        library=owned_library,
        idempotency_key="master-outer-wilds",
    )
    before = PlayerGame.objects.get()

    dispatch(
        RemovePlayerGame(game_id=game.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="remove-outer-wilds",
    )

    after = PlayerGame.objects.get()
    assert (after.pk, after.game_id, after.tracked_at, after.status) == (
        before.pk,
        before.game_id,
        before.tracked_at,
        before.status,
    )
    assert after.mastered is True


@pytest.mark.django_db(transaction=True)
def test_removing_an_untracked_game_is_refused(owned_user, owned_library):
    game = Game.objects.create(library=owned_library, name="Untracked")

    with pytest.raises(CommandRejected, match="tracks no game"):
        dispatch(
            RemovePlayerGame(game_id=game.pk),
            actor=owned_user,
            library=owned_library,
            idempotency_key="remove-untracked",
        )

    assert not LibraryEvent.objects.filter(
        event_type="library.playergame.removed"
    ).exists()


@pytest.mark.django_db(transaction=True)
def test_removing_a_game_another_library_tracks_is_refused(
    owned_user, owned_library, other_user, other_library, shared_game
):
    track(other_user, other_library, shared_game)

    with pytest.raises(CommandRejected, match="tracks no game"):
        dispatch(
            RemovePlayerGame(game_id=shared_game.pk),
            actor=owned_user,
            library=owned_library,
            idempotency_key="remove-theirs",
        )

    assert PlayerGame.objects.get().removed_at is None


@pytest.mark.django_db(transaction=True)
def test_removing_a_game_the_library_already_removed_changes_nothing(
    owned_user, owned_library
):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    track(owned_user, owned_library, game)
    dispatch(
        RemovePlayerGame(game_id=game.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="remove-outer-wilds",
    )

    result = dispatch(
        RemovePlayerGame(game_id=game.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="remove-outer-wilds-again",
    )

    assert result.outcome is CommandOutcome.UNCHANGED
    assert (
        LibraryEvent.objects.filter(event_type="library.playergame.removed").count()
        == 1
    )


@pytest.mark.django_db(transaction=True)
def test_restoring_a_game_the_library_did_not_remove_changes_nothing(
    owned_user, owned_library
):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    track(owned_user, owned_library, game)

    result = dispatch(
        RestorePlayerGame(game_id=game.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="restore-outer-wilds",
    )

    assert result.outcome is CommandOutcome.UNCHANGED
    assert not LibraryEvent.objects.filter(
        event_type="library.playergame.restored"
    ).exists()


@pytest.mark.django_db(transaction=True)
def test_one_idempotency_key_records_one_removal(owned_user, owned_library):
    """The key answers before the state check does."""
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    track(owned_user, owned_library, game)
    command = RemovePlayerGame(game_id=game.pk)

    first = dispatch(
        command, actor=owned_user, library=owned_library, idempotency_key="remove"
    )
    second = dispatch(
        command, actor=owned_user, library=owned_library, idempotency_key="remove"
    )

    assert (first.outcome, second.outcome) == (
        CommandOutcome.APPENDED,
        CommandOutcome.REPLAYED,
    )
    assert (
        LibraryEvent.objects.filter(event_type="library.playergame.removed").count()
        == 1
    )


@pytest.mark.django_db(transaction=True)
def test_tracking_a_removed_game_names_the_restore(owned_user, owned_library):
    """The message a person reads must match what they see."""
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    track(owned_user, owned_library, game)
    dispatch(
        RemovePlayerGame(game_id=game.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="remove-outer-wilds",
    )

    with pytest.raises(CommandRejected, match="restored, not tracked again"):
        dispatch(
            TrackGame(game_id=game.pk),
            actor=owned_user,
            library=owned_library,
            idempotency_key="track-again",
        )

    assert PlayerGame.objects.count() == 1


@pytest.mark.django_db(transaction=True)
def test_tracking_a_live_game_twice_still_names_the_game(owned_user, owned_library):
    """The rare case may not blunt the common one."""
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    track(owned_user, owned_library, game)

    result = dispatch(
        TrackGame(game_id=game.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="track-again",
    )

    assert result.outcome is CommandOutcome.UNCHANGED
    assert "already tracks Outer Wilds" in result.reason


@pytest.mark.django_db(transaction=True)
def test_a_game_whose_catalog_row_is_tombstoned_is_still_restored(
    owned_user, owned_library
):
    """The projection answers, not the catalog."""
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    track(owned_user, owned_library, game)
    dispatch(
        RemovePlayerGame(game_id=game.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="remove-outer-wilds",
    )
    #: A delete of a tracked game keeps the projection row.
    assert tombstone_or_delete(game) is Retirement.TOMBSTONED

    dispatch(
        RestorePlayerGame(game_id=game.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="restore-outer-wilds",
    )

    assert PlayerGame.objects.get().removed_at is None


@pytest.mark.django_db(transaction=True)
def test_recording_both_facts_appends_two_events(owned_user, owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    dispatch(
        TrackGame(game_id=game.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="track",
    )

    result = dispatch(
        RecordPlayerGameFacts(
            game_id=game.pk, status=PlayerGameStatus.COMPLETED, mastered=True
        ),
        actor=owned_user,
        library=owned_library,
        idempotency_key="facts",
    )

    assert result.outcome is CommandOutcome.APPENDED
    assert result.sequences is not None
    assert result.sequences.last - result.sequences.first == 1
    row = PlayerGame.objects.get()
    assert (row.status, row.mastered) == (PlayerGameStatus.COMPLETED, True)


@pytest.mark.django_db(transaction=True)
def test_recording_one_fact_appends_one_event(owned_user, owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    dispatch(
        TrackGame(game_id=game.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="track",
    )

    dispatch(
        RecordPlayerGameFacts(
            game_id=game.pk, status=PlayerGameStatus.PLAYED, mastered=None
        ),
        actor=owned_user,
        library=owned_library,
        idempotency_key="facts",
    )

    types = list(
        LibraryEvent.objects.filter(library=owned_library)
        .order_by("sequence")
        .values_list("event_type", flat=True)
    )
    assert types == ["library.playergame.created", "library.playergame.status_changed"]
    assert PlayerGame.objects.get().mastered is False


@pytest.mark.django_db(transaction=True)
def test_recording_only_the_fact_that_differs(owned_user, owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    dispatch(
        TrackGame(game_id=game.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="track",
    )
    dispatch(
        RecordPlayerGameFacts(
            game_id=game.pk, status=PlayerGameStatus.PLAYED, mastered=None
        ),
        actor=owned_user,
        library=owned_library,
        idempotency_key="first",
    )

    #: Same status, new mastery: no repeated status event.
    dispatch(
        RecordPlayerGameFacts(
            game_id=game.pk, status=PlayerGameStatus.PLAYED, mastered=True
        ),
        actor=owned_user,
        library=owned_library,
        idempotency_key="second",
    )

    assert (
        LibraryEvent.objects.filter(
            library=owned_library, event_type="library.playergame.status_changed"
        ).count()
        == 1
    )
    assert PlayerGame.objects.get().mastered is True


@pytest.mark.django_db(transaction=True)
def test_recording_facts_that_already_hold_is_unchanged(owned_user, owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    dispatch(
        TrackGame(game_id=game.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="track",
    )
    before = LibraryEvent.objects.filter(library=owned_library).count()

    result = dispatch(
        RecordPlayerGameFacts(
            game_id=game.pk, status=PlayerGameStatus.UNPLAYED, mastered=False
        ),
        actor=owned_user,
        library=owned_library,
        idempotency_key="facts",
    )

    assert result.outcome is CommandOutcome.UNCHANGED
    assert result.sequences is None
    assert LibraryEvent.objects.filter(library=owned_library).count() == before


def test_a_command_that_states_no_fact_cannot_be_built():
    with pytest.raises(ValueError, match="states no fact"):
        RecordPlayerGameFacts(game_id=uuid.uuid7(), status=None, mastered=None)


@pytest.mark.django_db(transaction=True)
def test_recording_facts_for_an_untracked_game_is_its_own_rejection(
    owned_user, owned_library
):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")

    #: Its own class, because the write path heals this case.
    with pytest.raises(PlayerGameNotTracked):
        dispatch(
            RecordPlayerGameFacts(
                game_id=game.pk, status=PlayerGameStatus.PLAYED, mastered=None
            ),
            actor=owned_user,
            library=owned_library,
            idempotency_key="facts",
        )
