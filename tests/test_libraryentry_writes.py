"""The entry write path and the reads it serves."""

import uuid

import pytest
from django.utils import timezone
from entries import record_entry as record_by_event
from entries import remove_entry as remove_by_event

from games.commands.endpoint import ActStatement, WayActStatement
from games.commands.libraryentry import (
    ACQUISITION_AFTER_END,
    END_BEFORE_ACQUISITION,
    ENTRY_REMOVED,
    UNKNOWN_ACCESS,
)
from games.commands.playergame import RemovePlayerGame
from games.end_ways import EndWay
from games.events.dispatch import CommandOutcome, CommandResult, dispatch
from games.models import (
    Game,
    LibraryEntry,
    LibraryEvent,
    LibraryIdempotencyRecord,
    PlayerGame,
)
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
    resume_entry_access,
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

    changed = restate_entry(owned_user, entry, note="lent", correlation_id=uuid.uuid7())

    assert changed is True
    assert _types(entry)[-1] == "library.libraryentry.note_changed"


def test_restate_of_nothing_dispatches_nothing(owned_user, owned_library, graph):
    entry = record_by_event(owned_library, graph.release, note="lent")
    before = LibraryIdempotencyRecord.objects.count()

    unstated = restate_entry(owned_user, entry, correlation_id=uuid.uuid7())
    same = restate_entry(owned_user, entry, note="lent", correlation_id=uuid.uuid7())

    assert (unstated, same) == (False, False)
    #: No dispatch at all for an empty body; one for the same fact.
    assert LibraryIdempotencyRecord.objects.count() == before + 1
    assert _types(entry) == ["library.libraryentry.created"]


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


# --- access end -------------------------------------------------------------

JULY = TemporalValue.parse("2021-07")


def _returned(ended) -> WayActStatement:
    return WayActStatement(ended, EndWay.RETURNED, "")


def test_restate_ends_then_corrects_then_voids(owned_user, owned_library, graph):
    entry = record_by_event(owned_library, graph.release, acquired=MAY)

    for statement in (_returned(JUNE), _returned(JULY), None):
        restate_entry(
            owned_user, entry, access_end=statement, correlation_id=uuid.uuid7()
        )
        entry.refresh_from_db()

    assert _types(entry)[1:] == [
        "library.libraryentry.access_ended",
        "library.libraryentry.access_end_corrected",
        "library.libraryentry.access_end_voided",
    ]


def test_restate_keeps_an_end_it_does_not_name(owned_user, owned_library, graph):
    entry = record_by_event(owned_library, graph.release)
    restate_entry(
        owned_user, entry, access_end=_returned(JUNE), correlation_id=uuid.uuid7()
    )
    entry.refresh_from_db()

    restate_entry(owned_user, entry, note="kept", correlation_id=uuid.uuid7())

    entry.refresh_from_db()
    assert entry.access_ended == JUNE


def test_a_draft_reversed_in_itself_appends_nothing(owned_user, owned_library, graph):
    entry = record_by_event(owned_library, graph.release, acquired=MAY)

    with pytest.raises(CommandFailed) as failed:
        restate_entry(
            owned_user,
            entry,
            note="lent",
            acquired=ActStatement(JULY, ""),
            access_end=_returned(JUNE),
            correlation_id=uuid.uuid7(),
        )

    assert "left before it was acquired" in failed.value.message
    assert _types(entry) == ["library.libraryentry.created"]


def test_a_copy_moved_wholly_earlier_lands(owned_user, owned_library, graph):
    """The acquisition moves first, or the end would precede it."""
    entry = record_by_event(owned_library, graph.release, acquired=JULY)
    earlier = TemporalValue.parse("2020-01")

    restate_entry(
        owned_user,
        entry,
        acquired=ActStatement(earlier, ""),
        access_end=_returned(MAY),
        correlation_id=uuid.uuid7(),
    )

    entry.refresh_from_db()
    assert (entry.acquired, entry.access_ended) == (earlier, MAY)
    assert _types(entry)[1:] == [
        "library.libraryentry.acquisition_corrected",
        "library.libraryentry.access_ended",
    ]


def test_a_copy_moved_wholly_later_lands(owned_user, owned_library, graph):
    """The end moves first, or the acquisition would follow it."""
    entry = record_by_event(owned_library, graph.release, acquired=MAY)
    restate_entry(
        owned_user, entry, access_end=_returned(JUNE), correlation_id=uuid.uuid7()
    )
    entry.refresh_from_db()
    later = TemporalValue.parse("2022-01")

    restate_entry(
        owned_user,
        entry,
        acquired=ActStatement(TemporalValue.parse("2021-12"), ""),
        access_end=_returned(later),
        correlation_id=uuid.uuid7(),
    )

    entry.refresh_from_db()
    assert (entry.acquired, entry.access_ended) == (
        TemporalValue.parse("2021-12"),
        later,
    )
    assert _types(entry)[-2:] == [
        "library.libraryentry.access_end_corrected",
        "library.libraryentry.acquisition_corrected",
    ]


def test_resume_answers_the_command_result(owned_user, owned_library, graph):
    entry = record_by_event(owned_library, graph.release)
    restate_entry(
        owned_user, entry, access_end=_returned(JUNE), correlation_id=uuid.uuid7()
    )
    entry.refresh_from_db()

    result = resume_entry_access(
        owned_user, entry, ActStatement(JULY, ""), correlation_id=uuid.uuid7()
    )

    entry.refresh_from_db()
    assert result.outcome is CommandOutcome.APPENDED
    assert entry.access_end_recorded_at is None
    with pytest.raises(CommandFailed):
        resume_entry_access(
            owned_user, entry, ActStatement(JULY, ""), correlation_id=uuid.uuid7()
        )


def test_a_note_beside_an_end_before_the_acquisition_appends_nothing(
    owned_user, owned_library, graph
):
    entry = record_by_event(owned_library, graph.release, acquired=JULY)

    with pytest.raises(CommandFailed) as failed:
        restate_entry(
            owned_user,
            entry,
            note="lent",
            access_end=_returned(MAY),
            correlation_id=uuid.uuid7(),
        )

    assert failed.value.message == END_BEFORE_ACQUISITION
    assert _types(entry) == ["library.libraryentry.created"]


def test_a_note_beside_an_acquisition_after_the_end_appends_nothing(
    owned_user, owned_library, graph
):
    entry = record_by_event(owned_library, graph.release, acquired=MAY)
    restate_entry(
        owned_user, entry, access_end=_returned(JUNE), correlation_id=uuid.uuid7()
    )
    entry.refresh_from_db()

    with pytest.raises(CommandFailed) as failed:
        restate_entry(
            owned_user,
            entry,
            note="lent",
            acquired=ActStatement(JULY, ""),
            correlation_id=uuid.uuid7(),
        )

    assert failed.value.message == ACQUISITION_AFTER_END
    assert _types(entry)[-1] == "library.libraryentry.access_ended"


def test_a_void_goes_before_an_acquisition_past_the_old_end(
    owned_user, owned_library, graph
):
    entry = record_by_event(owned_library, graph.release, acquired=MAY)
    restate_entry(
        owned_user, entry, access_end=_returned(JUNE), correlation_id=uuid.uuid7()
    )
    entry.refresh_from_db()

    restate_entry(
        owned_user,
        entry,
        acquired=ActStatement(JULY, ""),
        access_end=None,
        correlation_id=uuid.uuid7(),
    )

    entry.refresh_from_db()
    assert entry.acquired == JULY
    assert _types(entry)[-2:] == [
        "library.libraryentry.access_end_voided",
        "library.libraryentry.acquisition_corrected",
    ]


def test_a_void_of_a_held_copy_dispatches_and_changes_nothing(
    owned_user, owned_library, graph
):
    entry = record_by_event(owned_library, graph.release)
    before = LibraryIdempotencyRecord.objects.count()

    changed = restate_entry(
        owned_user, entry, access_end=None, correlation_id=uuid.uuid7()
    )

    assert changed is False
    assert LibraryIdempotencyRecord.objects.count() == before + 1
    assert _types(entry) == ["library.libraryentry.created"]


@pytest.mark.parametrize(
    ("acquired", "ended"),
    [
        (None, MAY),
        (JULY, None),
        (JULY, TemporalValue.parse("2021-05~")),
        (TemporalValue.parse("../2021-07"), MAY),
    ],
)
def test_the_draft_check_admits_what_is_not_certain(
    owned_user, owned_library, graph, acquired, ended
):
    entry = record_by_event(owned_library, graph.release)

    restate_entry(
        owned_user,
        entry,
        acquired=ActStatement(acquired, ""),
        access_end=_returned(ended),
        correlation_id=uuid.uuid7(),
    )

    entry.refresh_from_db()
    assert entry.access_end_recorded_at is not None
