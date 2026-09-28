"""Dispatching the command that tracks a game."""

import uuid
from typing import Any, NamedTuple

import pytest
from django.utils import timezone

from games.commands.playergame import (
    PlayerGameNotTracked,
    RecordPlayerGameFacts,
    RemovePlayerGame,
    RestorePlayerGame,
    SetPlayerGameExcludedFromUnfinished,
    TrackGame,
)
from games.events.dispatch import CommandOutcome, CommandRejected, dispatch
from games.models import Game, LibraryEvent, PlayerGame, PlayerGameStatus
from games.removal import remove
from games.retention import purging_library
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
    event = LibraryEvent.objects.get(
        library=owned_library, event_type="library.playergame.created"
    )
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
def test_a_removed_game_cannot_be_tracked(owned_user, owned_library):
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


class StatedFact(NamedTuple):
    """One fact RecordPlayerGameFacts states alone."""

    stated: dict[str, Any]
    #: What a freshly tracked row already holds.
    held: dict[str, Any]
    #: Set first, so it is no default.
    other: dict[str, Any]
    event_type: str
    payload: dict[str, Any]
    column: str
    value: Any
    default: Any


FACTS = [
    pytest.param(
        StatedFact(
            stated={"status": PlayerGameStatus.COMPLETED, "mastered": None},
            held={"status": PlayerGameStatus.UNPLAYED, "mastered": None},
            other={"status": None, "mastered": True},
            event_type="library.playergame.status_changed",
            payload={"status": "completed"},
            column="status",
            value=PlayerGameStatus.COMPLETED,
            default=PlayerGameStatus.UNPLAYED,
        ),
        id="status",
    ),
    pytest.param(
        StatedFact(
            stated={"status": None, "mastered": True},
            held={"status": None, "mastered": False},
            other={"status": PlayerGameStatus.COMPLETED, "mastered": None},
            event_type="library.playergame.mastered_changed",
            payload={"mastered": True},
            column="mastered",
            value=True,
            default=False,
        ),
        id="mastery",
    ),
]


def state(actor, library, game, facts, key):
    """RecordPlayerGameFacts through dispatch, which tracks nothing."""
    return dispatch(
        RecordPlayerGameFacts(game_id=game.pk, **facts),
        actor=actor,
        library=library,
        idempotency_key=key,
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("fact", FACTS)
def test_a_stated_fact_records_it_and_projects_it(owned_user, owned_library, fact):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    track(owned_user, owned_library, game)

    state(owned_user, owned_library, game, fact.stated, "state")

    event = LibraryEvent.objects.get(event_type=fact.event_type)
    assert event.payload == fact.payload
    row = PlayerGame.objects.get()
    assert event.aggregate_id == row.pk
    assert getattr(row, fact.column) == fact.value


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("fact", FACTS)
def test_a_stated_fact_leaves_the_rest_of_the_row_alone(
    owned_user, owned_library, fact
):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    track(owned_user, owned_library, game)
    state(owned_user, owned_library, game, fact.other, "other")
    untouched = [
        column
        for column in ("pk", "game_id", "tracked_at", "status", "mastered")
        if column != fact.column
    ]
    before = PlayerGame.objects.get()

    state(owned_user, owned_library, game, fact.stated, "state")

    after = PlayerGame.objects.get()
    assert [getattr(after, c) for c in untouched] == [
        getattr(before, c) for c in untouched
    ]


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("fact", FACTS)
def test_a_fact_for_an_untracked_game_is_refused(owned_user, owned_library, fact):
    game = Game.objects.create(library=owned_library, name="Untracked")

    with pytest.raises(CommandRejected, match="tracks no game"):
        state(owned_user, owned_library, game, fact.stated, "state")

    assert not LibraryEvent.objects.filter(event_type=fact.event_type).exists()


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("fact", FACTS)
def test_a_fact_for_a_game_another_library_tracks_is_refused(
    owned_user, owned_library, other_user, other_library, shared_game, fact
):
    track(other_user, other_library, shared_game)

    with pytest.raises(CommandRejected, match="tracks no game"):
        state(owned_user, owned_library, shared_game, fact.stated, "state")

    assert getattr(PlayerGame.objects.get(), fact.column) == fact.default


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("fact", FACTS)
def test_a_fact_that_already_holds_changes_nothing(owned_user, owned_library, fact):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    track(owned_user, owned_library, game)

    result = state(owned_user, owned_library, game, fact.held, "hold")

    assert result.outcome is CommandOutcome.UNCHANGED
    assert "already records" in result.reason
    assert not LibraryEvent.objects.filter(event_type=fact.event_type).exists()


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("fact", FACTS)
def test_one_idempotency_key_records_one_fact_change(owned_user, owned_library, fact):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    track(owned_user, owned_library, game)

    first = state(owned_user, owned_library, game, fact.stated, "state")
    second = state(owned_user, owned_library, game, fact.stated, "state")

    assert (first.outcome, second.outcome) == (
        CommandOutcome.APPENDED,
        CommandOutcome.REPLAYED,
    )
    assert LibraryEvent.objects.filter(event_type=fact.event_type).count() == 1


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
    state(owned_user, owned_library, game, {"status": None, "mastered": True}, "master")
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
    state(
        owned_user,
        owned_library,
        game,
        {"status": PlayerGameStatus.PLAYED, "mastered": True},
        "play-and-master",
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
def test_a_game_whose_catalog_row_is_removed_is_still_restored(
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
    #: Removal keeps the projection row.
    remove(game)

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
    assert types == [
        "library.playergame.created",
        #: Tracking states the default run: #679.
        "library.playthrough.created",
        "library.playergame.status_changed",
    ]
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

    #: Its own class: the write path tracks it first.
    with pytest.raises(PlayerGameNotTracked):
        dispatch(
            RecordPlayerGameFacts(
                game_id=game.pk, status=PlayerGameStatus.PLAYED, mastered=None
            ),
            actor=owned_user,
            library=owned_library,
            idempotency_key="facts",
        )
