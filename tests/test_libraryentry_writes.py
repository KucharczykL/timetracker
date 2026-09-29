"""The entry write path and the reads it serves."""

import uuid

import pytest
from django.utils import timezone
from entries import record_entry as record_by_event
from entries import remove_entry as remove_by_event

from games.commands.endpoint import ActStatement
from games.commands.libraryentry import ENTRY_REMOVED, UNKNOWN_ACCESS
from games.commands.playergame import RemovePlayerGame
from games.events.dispatch import CommandResult, dispatch
from games.models import Game, LibraryEntry, LibraryEvent, PlayerGame
from games.reads.entries import game_entries, library_entries, readable_entries
from games.reads.events import dispatched_events
from games.reads.unscoped import UnscopedRead
from games.removal import remove
from games.writes.answers import CommandFailed
from games.writes.libraryentry import (
    EntryDraft,
    record_entry,
    remove_entry,
    restate_entry,
    restore_entry,
)
from timetracker.temporal import TemporalValue

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.untracked_games]

MAY = TemporalValue.parse("2021-05")
JUNE = TemporalValue.parse("2021-06")


@pytest.fixture
def second_library(django_user_model):
    return django_user_model.objects.create_user(username="second-owner").library


@pytest.fixture
def graph(owned_library, stated_graph):
    return stated_graph(Game(name="Tunic", library=owned_library), owned_library)


def _draft(release, **changes) -> EntryDraft:
    stated = {
        "release_id": release.pk,
        "access": "owned",
        "format": "digital",
        "note": "",
        "acquired": ActStatement(None, ""),
    } | changes
    return EntryDraft(**stated)


def _types(entry: LibraryEntry) -> list[str]:
    return list(
        LibraryEvent.objects.filter(aggregate_id=entry.pk)
        .order_by("sequence")
        .values_list("event_type", flat=True)
    )


# --- record ---------------------------------------------------------------


def test_record_answers_the_entry_id_and_that_it_tracked_the_game(
    owned_user, owned_library, graph
):
    answer = record_entry(
        owned_user, _draft(graph.release), correlation_id=uuid.uuid7()
    )

    entry = LibraryEntry.objects.get(pk=answer.entry_id)
    assert answer.tracked_the_game is True
    assert entry.player_game.game == graph.game
    #: The entry's id, not the tracking pair's.
    assert entry.pk != PlayerGame.objects.get(game=graph.game).pk


def test_record_on_a_tracked_game_says_so(owned_user, owned_library, graph):
    record_by_event(owned_library, graph.release)

    answer = record_entry(
        owned_user, _draft(graph.release), correlation_id=uuid.uuid7()
    )

    assert answer.tracked_the_game is False
    assert LibraryEntry.objects.filter(pk=answer.entry_id).exists()


def test_a_repeat_under_one_key_answers_the_same_id(owned_user, owned_library, graph):
    first = record_entry(
        owned_user,
        _draft(graph.release),
        correlation_id=uuid.uuid7(),
        idempotency_key="once",
    )
    again = record_entry(
        owned_user,
        _draft(graph.release),
        correlation_id=uuid.uuid7(),
        idempotency_key="once",
    )

    assert again == first
    assert LibraryEntry.objects.count() == 1


def test_a_refusal_is_answered(owned_user, owned_library, graph):
    remove(graph.release)

    with pytest.raises(CommandFailed) as failed:
        record_entry(owned_user, _draft(graph.release), correlation_id=uuid.uuid7())

    assert failed.value.status_code == 409


def test_dispatched_events_refuses_an_unchanged_outcome(owned_user, owned_library):
    unchanged = CommandResult(
        stream_id=uuid.uuid7(),
        outcome=None,  # type: ignore[arg-type]
        sequences=None,
        reason="nothing",
        correlation_id=uuid.uuid7(),
    )
    with pytest.raises(ValueError, match="no range"):
        dispatched_events(unchanged)


# --- restate --------------------------------------------------------------


def test_restate_sends_the_description_first(owned_user, owned_library, graph):
    entry = record_by_event(owned_library, graph.release, acquired=MAY)
    correlation = uuid.uuid7()

    restate_entry(
        owned_user,
        entry,
        access="borrowed",
        acquired=ActStatement(JUNE, ""),
        correlation_id=correlation,
    )

    assert _types(entry)[1:] == [
        "library.libraryentry.access_changed",
        "library.libraryentry.acquisition_corrected",
    ]
    assert LibraryEvent.objects.filter(correlation_id=correlation).count() == 2


def test_a_refused_description_leaves_the_day_unmoved(owned_user, owned_library, graph):
    entry = record_by_event(owned_library, graph.release, acquired=MAY)

    with pytest.raises(CommandFailed) as failed:
        restate_entry(
            owned_user,
            entry,
            access="stolen",
            acquired=ActStatement(JUNE, ""),
            correlation_id=uuid.uuid7(),
        )

    assert failed.value.message == UNKNOWN_ACCESS
    entry.refresh_from_db()
    assert entry.acquired == MAY
    assert _types(entry) == ["library.libraryentry.created"]


def test_a_removed_entry_refuses_the_whole_restatement(
    owned_user, owned_library, graph
):
    entry = remove_by_event(record_by_event(owned_library, graph.release, acquired=MAY))

    with pytest.raises(CommandFailed) as failed:
        restate_entry(
            owned_user,
            entry,
            access="borrowed",
            acquired=ActStatement(JUNE, ""),
            correlation_id=uuid.uuid7(),
        )

    assert failed.value.message == ENTRY_REMOVED
    assert _types(entry) == [
        "library.libraryentry.created",
        "library.libraryentry.removed",
    ]


def test_restate_without_a_day_describes_alone(owned_user, owned_library, graph):
    entry = record_by_event(owned_library, graph.release)

    restate_entry(
        owned_user, entry, note="lent", acquired=None, correlation_id=uuid.uuid7()
    )

    assert _types(entry)[-1] == "library.libraryentry.note_changed"


# --- remove and restore ---------------------------------------------------


def test_remove_and_restore_move_the_mark(owned_user, owned_library, graph):
    entry = record_by_event(owned_library, graph.release)

    remove_entry(owned_user, entry, correlation_id=uuid.uuid7())
    entry.refresh_from_db()
    assert entry.removed_at is not None

    restore_entry(owned_user, entry, correlation_id=uuid.uuid7())
    entry.refresh_from_db()
    assert entry.removed_at is None


# --- reads ----------------------------------------------------------------


def test_library_entries_refuses_no_library():
    with pytest.raises(UnscopedRead):
        library_entries(None)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "hide",
    ["entry", "player_game", "release", "edition", "game"],
)
def test_library_entries_reads_each_of_the_five_marks(
    owned_user, owned_library, graph, hide
):
    entry = record_by_event(owned_library, graph.release)
    assert list(library_entries(owned_library)) == [entry]

    match hide:
        case "entry":
            remove_by_event(entry)
        case "player_game":
            dispatch(
                RemovePlayerGame(game_id=graph.game.pk),
                actor=owned_user,
                library=owned_library,
                idempotency_key="untrack",
            )
        case _:
            remove(getattr(graph, hide))

    assert not library_entries(owned_library).exists()


def test_library_entries_never_answers_another_librarys_row(
    owned_library, second_library, graph, stated_graph
):
    Game.objects.filter(pk=graph.game.pk).update(library=None)
    mine = record_by_event(owned_library, graph.release)
    theirs = record_by_event(second_library, graph.release)

    assert list(library_entries(owned_library)) == [mine]
    assert list(library_entries(second_library)) == [theirs]


def test_library_entries_reads_the_tracked_games_library(
    owned_library, second_library, graph
):
    """A drifted parent hides the entry."""
    entry = record_by_event(owned_library, graph.release)
    PlayerGame.objects.filter(pk=entry.player_game_id).update(library=second_library)

    assert not library_entries(owned_library).exists()


def test_game_entries_and_readable_entries_narrow_the_same_rows(
    owned_library, graph, stated_graph
):
    other = stated_graph(Game(name="Celeste", library=owned_library), owned_library)
    mine = record_by_event(owned_library, graph.release)
    record_by_event(owned_library, other.release)

    assert list(game_entries(owned_library, graph.game)) == [mine]
    assert readable_entries(owned_library).count() == 2
    (row,) = readable_entries(owned_library).filter(pk=mine.pk)
    assert row.player_game.game.name == "Tunic"
    assert row.acquisition_recorded_at <= timezone.now()
