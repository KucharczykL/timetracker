"""Dispatching the command that tracks a game."""

import uuid

import pytest

from games.commands.playergame import (
    ArchivePlayerGame,
    RestorePlayerGame,
    SetPlayerGameExcludedFromUnfinished,
    SetPlayerGameMastered,
    SetPlayerGameStatus,
    TrackGame,
)
from games.events.dispatch import CommandRejected, dispatch
from games.models import Game, LibraryEvent, PlayerGame, PlayerGameStatus
from games.retention import Retirement, purging_library, tombstone_or_delete


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

    assert result.replayed is False
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
        library=owned_library, name="Retired", tombstoned_at=timezone.now()
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
def test_tracking_the_same_game_twice_is_refused(owned_user, owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    dispatch(
        TrackGame(game_id=game.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="track-first",
    )

    #: A different key: a second intent.
    with pytest.raises(CommandRejected):
        dispatch(
            TrackGame(game_id=game.pk),
            actor=owned_user,
            library=owned_library,
            idempotency_key="track-again",
        )

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

    assert second.replayed is True
    assert (second.first_sequence, second.last_sequence) == (
        first.first_sequence,
        first.last_sequence,
    )
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
def test_the_status_a_game_already_has_is_refused(owned_user, owned_library):
    """One convention for #906 to change."""
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    track(owned_user, owned_library, game)

    with pytest.raises(CommandRejected, match="#906"):
        dispatch(
            SetPlayerGameStatus(game_id=game.pk, status=PlayerGameStatus.UNPLAYED),
            actor=owned_user,
            library=owned_library,
            idempotency_key="unplay-outer-wilds",
        )


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

    assert (first.replayed, second.replayed) == (False, True)
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
def test_the_mastery_a_game_already_records_is_refused(owned_user, owned_library):
    """One convention for #906 to change."""
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    track(owned_user, owned_library, game)

    with pytest.raises(CommandRejected, match="#906"):
        dispatch(
            SetPlayerGameMastered(game_id=game.pk, mastered=False),
            actor=owned_user,
            library=owned_library,
            idempotency_key="unmaster-outer-wilds",
        )


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

    assert (first.replayed, second.replayed) == (False, True)
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
def test_the_exclusion_a_game_already_records_is_refused(owned_user, owned_library):
    """One convention for #906 to change."""
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    track(owned_user, owned_library, game)

    with pytest.raises(CommandRejected, match="#906"):
        dispatch(
            SetPlayerGameExcludedFromUnfinished(
                game_id=game.pk, excluded_from_unfinished=False
            ),
            actor=owned_user,
            library=owned_library,
            idempotency_key="include-outer-wilds",
        )


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

    assert (first.replayed, second.replayed) == (False, True)
    assert (
        LibraryEvent.objects.filter(
            event_type="library.playergame.excluded_from_unfinished_changed"
        ).count()
        == 1
    )


@pytest.mark.django_db(transaction=True)
def test_archiving_a_game_records_it_and_projects_it(owned_user, owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    track(owned_user, owned_library, game)

    dispatch(
        ArchivePlayerGame(game_id=game.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="archive-outer-wilds",
    )

    event = LibraryEvent.objects.get(event_type="library.playergame.archived")
    assert event.payload == {}
    row = PlayerGame.objects.get()
    assert event.aggregate_id == row.pk
    assert row.archived_at == event.recorded_at


@pytest.mark.django_db(transaction=True)
def test_restoring_a_game_returns_it(owned_user, owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    track(owned_user, owned_library, game)
    dispatch(
        ArchivePlayerGame(game_id=game.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="archive-outer-wilds",
    )

    dispatch(
        RestorePlayerGame(game_id=game.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="restore-outer-wilds",
    )

    assert LibraryEvent.objects.get(event_type="library.playergame.restored")
    assert PlayerGame.objects.get().archived_at is None


@pytest.mark.django_db(transaction=True)
def test_archiving_a_game_leaves_the_rest_of_the_row_alone(owned_user, owned_library):
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
        ArchivePlayerGame(game_id=game.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="archive-outer-wilds",
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
def test_archiving_an_untracked_game_is_refused(owned_user, owned_library):
    game = Game.objects.create(library=owned_library, name="Untracked")

    with pytest.raises(CommandRejected, match="tracks no game"):
        dispatch(
            ArchivePlayerGame(game_id=game.pk),
            actor=owned_user,
            library=owned_library,
            idempotency_key="archive-untracked",
        )

    assert not LibraryEvent.objects.filter(
        event_type="library.playergame.archived"
    ).exists()


@pytest.mark.django_db(transaction=True)
def test_archiving_a_game_another_library_tracks_is_refused(
    owned_user, owned_library, other_user, other_library, shared_game
):
    track(other_user, other_library, shared_game)

    with pytest.raises(CommandRejected, match="tracks no game"):
        dispatch(
            ArchivePlayerGame(game_id=shared_game.pk),
            actor=owned_user,
            library=owned_library,
            idempotency_key="archive-theirs",
        )

    assert PlayerGame.objects.get().archived_at is None


@pytest.mark.django_db(transaction=True)
def test_archiving_a_game_the_library_already_archives_is_refused(
    owned_user, owned_library
):
    """One convention for #906 to change."""
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    track(owned_user, owned_library, game)
    dispatch(
        ArchivePlayerGame(game_id=game.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="archive-outer-wilds",
    )

    with pytest.raises(CommandRejected, match="#906"):
        dispatch(
            ArchivePlayerGame(game_id=game.pk),
            actor=owned_user,
            library=owned_library,
            idempotency_key="archive-outer-wilds-again",
        )

    assert (
        LibraryEvent.objects.filter(event_type="library.playergame.archived").count()
        == 1
    )


@pytest.mark.django_db(transaction=True)
def test_restoring_a_game_the_library_does_not_archive_is_refused(
    owned_user, owned_library
):
    """One convention for #906 to change."""
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    track(owned_user, owned_library, game)

    with pytest.raises(CommandRejected, match="#906"):
        dispatch(
            RestorePlayerGame(game_id=game.pk),
            actor=owned_user,
            library=owned_library,
            idempotency_key="restore-outer-wilds",
        )

    assert not LibraryEvent.objects.filter(
        event_type="library.playergame.restored"
    ).exists()


@pytest.mark.django_db(transaction=True)
def test_one_idempotency_key_records_one_archive(owned_user, owned_library):
    """The key answers before the state check does."""
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    track(owned_user, owned_library, game)
    command = ArchivePlayerGame(game_id=game.pk)

    first = dispatch(
        command, actor=owned_user, library=owned_library, idempotency_key="archive"
    )
    second = dispatch(
        command, actor=owned_user, library=owned_library, idempotency_key="archive"
    )

    assert (first.replayed, second.replayed) == (False, True)
    assert (
        LibraryEvent.objects.filter(event_type="library.playergame.archived").count()
        == 1
    )


@pytest.mark.django_db(transaction=True)
def test_tracking_an_archived_game_names_the_restore(owned_user, owned_library):
    """The message a person reads must match what they see."""
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    track(owned_user, owned_library, game)
    dispatch(
        ArchivePlayerGame(game_id=game.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="archive-outer-wilds",
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
def test_tracking_a_live_game_twice_still_says_the_library_tracks_it(
    owned_user, owned_library
):
    """The rare case may not blunt the common one."""
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    track(owned_user, owned_library, game)

    with pytest.raises(CommandRejected, match="already tracks Outer Wilds"):
        dispatch(
            TrackGame(game_id=game.pk),
            actor=owned_user,
            library=owned_library,
            idempotency_key="track-again",
        )


@pytest.mark.django_db(transaction=True)
def test_a_game_whose_catalog_row_is_tombstoned_is_still_restored(
    owned_user, owned_library
):
    """The projection answers, not the catalog."""
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    track(owned_user, owned_library, game)
    dispatch(
        ArchivePlayerGame(game_id=game.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="archive-outer-wilds",
    )
    #: A delete of a tracked game keeps the projection row.
    assert tombstone_or_delete(game) is Retirement.TOMBSTONED

    dispatch(
        RestorePlayerGame(game_id=game.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="restore-outer-wilds",
    )

    assert PlayerGame.objects.get().archived_at is None
