"""Backfilling the baseline events a library's tracked games fold from."""

import uuid
from datetime import datetime, timedelta, timezone as datetime_timezone

import pytest
from django.utils import timezone

from games.backfill.playergame import (
    LEGACY_STATUS_TO_PLAYER_STATUS,
    UnmappedLegacyStatus,
    backfill_game,
    player_status_for,
    transition_effective_time,
)
from games.models import (
    Game,
    GameStatusChange,
    LibraryEvent,
    PlayerGame,
    PlayerGameStatus,
)


def test_every_legacy_status_letter_is_mapped():
    #: A sixth letter added to Game.Status fails here rather than at run time.
    assert set(LEGACY_STATUS_TO_PLAYER_STATUS) == set(Game.Status.values)


def test_the_map_names_the_statuses_the_charter_names():
    assert LEGACY_STATUS_TO_PLAYER_STATUS == {
        "u": PlayerGameStatus.UNPLAYED,
        "p": PlayerGameStatus.PLAYED,
        "f": PlayerGameStatus.COMPLETED,
        "r": PlayerGameStatus.RETIRED,
        "a": PlayerGameStatus.ABANDONED,
    }


def test_shelved_has_no_legacy_source():
    assert PlayerGameStatus.SHELVED not in LEGACY_STATUS_TO_PLAYER_STATUS.values()


def test_an_unknown_letter_is_refused_by_name():
    with pytest.raises(UnmappedLegacyStatus, match="'z'"):
        player_status_for("z")


def test_a_null_timestamp_stays_unknown():
    #: The charter puts an undated transition in approximate history only.
    assert transition_effective_time(None).is_unknown


def test_a_dated_timestamp_becomes_the_local_day():
    #: 23:30 UTC is already the next day in Europe/Prague.
    timestamp = datetime(2023, 6, 2, 23, 30, tzinfo=datetime_timezone.utc)
    expected = timezone.localtime(timestamp).date().isoformat()
    assert transition_effective_time(timestamp).serialize() == expected


def test_a_dated_timestamp_is_day_precision_not_a_range():
    timestamp = timezone.now() - timedelta(days=400)
    value = transition_effective_time(timestamp)
    assert value.is_range is False
    assert value.has_known_day is True


def backdate(game, created_at):
    """Game.created_at is auto_now_add, so a test moves it with UPDATE."""
    Game.objects.filter(pk=game.pk).update(created_at=created_at)
    game.refresh_from_db()
    return game


def run_for(game, owned_user, owned_library, run_time=None):
    return backfill_game(
        game,
        library=owned_library,
        actor=owned_user,
        run_time=run_time or timezone.now(),
    )


@pytest.mark.django_db(transaction=True)
def test_an_unplayed_game_with_no_history_records_only_its_creation(
    owned_user, owned_library
):
    added = timezone.now() - timedelta(days=500)
    game = backdate(
        Game.objects.create(library=owned_library, name="Outer Wilds"), added
    )

    counts = run_for(game, owned_user, owned_library)

    assert (counts.created_events, counts.status_events) == (1, 0)
    assert counts.corrective_events == 0
    event = LibraryEvent.objects.get()
    assert event.event_type == "library.playergame.created"
    assert event.recorded_at == added
    assert event.effective_time is None
    assert event.source_metadata == {"origin": "backfill", "issue": 676}
    row = PlayerGame.objects.get()
    assert (row.status, row.tracked_at) == (PlayerGameStatus.UNPLAYED, added)


@pytest.mark.django_db(transaction=True)
def test_a_finished_game_with_no_history_gets_an_undated_corrective_event(
    owned_user, owned_library
):
    added = timezone.now() - timedelta(days=500)
    run_time = timezone.now()
    game = backdate(
        Game.objects.create(
            library=owned_library, name="Tunic", status=Game.Status.FINISHED
        ),
        added,
    )

    counts = run_for(game, owned_user, owned_library, run_time=run_time)

    assert (counts.status_events, counts.corrective_events) == (0, 1)
    assert counts.unknown_effective_times == 1
    corrective = LibraryEvent.objects.get(
        event_type="library.playergame.status_changed"
    )
    assert corrective.payload == {"status": "completed"}
    #: auto_now would be a fabrication; the run time is the honest recording.
    assert corrective.recorded_at == run_time
    assert corrective.effective_time is None
    assert PlayerGame.objects.get().status == PlayerGameStatus.COMPLETED


@pytest.mark.django_db(transaction=True)
def test_dated_history_that_reaches_the_current_status_needs_no_correction(
    owned_user, owned_library
):
    added = timezone.now() - timedelta(days=500)
    game = backdate(
        Game.objects.create(
            library=owned_library, name="Hades", status=Game.Status.FINISHED
        ),
        added,
    )
    played_at = added + timedelta(days=10)
    finished_at = added + timedelta(days=40)
    GameStatusChange.objects.create(
        game=game, old_status="u", new_status="p", timestamp=played_at
    )
    GameStatusChange.objects.create(
        game=game, old_status="p", new_status="f", timestamp=finished_at
    )

    counts = run_for(game, owned_user, owned_library)

    assert (counts.status_events, counts.corrective_events) == (2, 0)
    statuses = list(
        LibraryEvent.objects.filter(event_type="library.playergame.status_changed")
        .order_by("sequence")
        .values_list("payload", "recorded_at")
    )
    assert [payload["status"] for payload, _ in statuses] == ["played", "completed"]
    assert [recorded_at for _, recorded_at in statuses] == [played_at, finished_at]
    assert PlayerGame.objects.get().status == PlayerGameStatus.COMPLETED


@pytest.mark.django_db(transaction=True)
def test_dated_history_that_misses_the_current_status_is_corrected(
    owned_user, owned_library
):
    added = timezone.now() - timedelta(days=500)
    game = backdate(
        Game.objects.create(
            library=owned_library, name="Celeste", status=Game.Status.ABANDONED
        ),
        added,
    )
    GameStatusChange.objects.create(
        game=game, old_status="u", new_status="p", timestamp=added + timedelta(days=3)
    )

    counts = run_for(game, owned_user, owned_library)

    assert (counts.status_events, counts.corrective_events) == (1, 1)
    assert PlayerGame.objects.get().status == PlayerGameStatus.ABANDONED


@pytest.mark.django_db(transaction=True)
def test_a_dated_transition_carries_its_local_day_and_names_its_source_row(
    owned_user, owned_library
):
    added = timezone.now() - timedelta(days=500)
    game = backdate(
        Game.objects.create(
            library=owned_library, name="Inscryption", status=Game.Status.PLAYED
        ),
        added,
    )
    played_at = added + timedelta(days=10)
    change = GameStatusChange.objects.create(
        game=game, old_status="u", new_status="p", timestamp=played_at
    )

    run_for(game, owned_user, owned_library)

    event = LibraryEvent.objects.get(event_type="library.playergame.status_changed")
    assert event.effective_time.serialize() == (
        timezone.localtime(played_at).date().isoformat()
    )
    assert event.source_metadata == {
        "origin": "backfill",
        "issue": 676,
        "status_change_id": str(change.pk),
    }


@pytest.mark.django_db(transaction=True)
def test_an_undated_transition_records_an_unknown_effective_time(
    owned_user, owned_library
):
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

    counts = run_for(game, owned_user, owned_library)

    event = LibraryEvent.objects.get(event_type="library.playergame.status_changed")
    assert event.effective_time is None
    #: Not coerced to a date; only the recording falls back to created_at.
    assert event.recorded_at == added
    assert counts.unknown_effective_times == 1


@pytest.mark.django_db(transaction=True)
def test_undated_transitions_are_folded_before_dated_ones(owned_user, owned_library):
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

    counts = run_for(game, owned_user, owned_library)

    ordered = list(
        LibraryEvent.objects.filter(event_type="library.playergame.status_changed")
        .order_by("sequence")
        .values_list("payload", flat=True)
    )
    assert [payload["status"] for payload in ordered] == ["played", "completed"]
    assert counts.corrective_events == 0


@pytest.mark.django_db(transaction=True)
def test_a_mastered_game_records_the_mastery_fact(owned_user, owned_library):
    added = timezone.now() - timedelta(days=500)
    game = backdate(
        Game.objects.create(library=owned_library, name="Katana Zero", mastered=True),
        added,
    )

    counts = run_for(game, owned_user, owned_library)

    assert counts.mastered_events == 1
    event = LibraryEvent.objects.get(event_type="library.playergame.mastered_changed")
    assert event.payload == {"mastered": True}
    assert event.recorded_at == added
    assert event.effective_time is None
    assert PlayerGame.objects.get().mastered is True


@pytest.mark.django_db(transaction=True)
def test_an_unmastered_game_records_no_mastery_fact(owned_user, owned_library):
    game = Game.objects.create(library=owned_library, name="Gris")

    counts = run_for(game, owned_user, owned_library)

    assert counts.mastered_events == 0
    assert not LibraryEvent.objects.filter(
        event_type="library.playergame.mastered_changed"
    ).exists()


@pytest.mark.django_db(transaction=True)
def test_no_exclusion_or_archive_fact_is_invented(owned_user, owned_library):
    game = Game.objects.create(
        library=owned_library, name="Signalis", status=Game.Status.RETIRED
    )

    run_for(game, owned_user, owned_library)

    recorded = set(LibraryEvent.objects.values_list("event_type", flat=True))
    assert "library.playergame.excluded_from_unfinished_changed" not in recorded
    assert "library.playergame.archived" not in recorded
    assert PlayerGame.objects.get().archived_at is None


@pytest.mark.django_db(transaction=True)
def test_running_a_game_twice_appends_nothing_the_second_time(
    owned_user, owned_library
):
    game = Game.objects.create(
        library=owned_library, name="Disco Elysium", status=Game.Status.FINISHED
    )
    GameStatusChange.objects.create(
        game=game, old_status="u", new_status="f", timestamp=timezone.now()
    )

    first = run_for(game, owned_user, owned_library)
    before = LibraryEvent.objects.count()
    second = run_for(game, owned_user, owned_library)

    assert first.created_events == 1
    assert LibraryEvent.objects.count() == before
    assert (second.created_events, second.status_events) == (0, 0)
    assert (second.mastered_events, second.corrective_events) == (0, 0)
    assert second.tracked == 1
    assert PlayerGame.objects.count() == 1


@pytest.mark.django_db(transaction=True)
def test_the_creation_event_is_always_sequenced_first(owned_user, owned_library):
    game = Game.objects.create(
        library=owned_library, name="Outer Wilds", status=Game.Status.FINISHED
    )

    run_for(game, owned_user, owned_library)

    first = LibraryEvent.objects.order_by("sequence").first()
    assert first.event_type == "library.playergame.created"
    assert first.payload["game"]["id"] == str(game.pk)
    assert first.aggregate_id == PlayerGame.objects.get().pk


@pytest.mark.django_db(transaction=True)
def test_every_baseline_event_names_the_library_owner_as_actor(
    owned_user, owned_library
):
    game = Game.objects.create(
        library=owned_library, name="Outer Wilds", status=Game.Status.PLAYED
    )

    run_for(game, owned_user, owned_library)

    actors = set(LibraryEvent.objects.values_list("actor_id", flat=True))
    assert actors == {owned_user.pk}


@pytest.mark.django_db(transaction=True)
def test_each_baseline_event_gets_its_own_correlation_id(owned_user, owned_library):
    game = Game.objects.create(
        library=owned_library, name="Outer Wilds", status=Game.Status.PLAYED
    )

    run_for(game, owned_user, owned_library)

    correlation_ids = list(
        LibraryEvent.objects.values_list("correlation_id", flat=True)
    )
    assert len(correlation_ids) == len(set(correlation_ids)) == 2
    assert all(isinstance(value, uuid.UUID) for value in correlation_ids)
