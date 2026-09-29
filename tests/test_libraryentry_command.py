"""Stating a copy of a Release the library sees."""

import uuid
from datetime import UTC, datetime

import pytest
from django.db import connection, models
from django.test.utils import isolate_apps
from django.utils import timezone
from entries import record_entry, remove_entry, restore_entry

from games.catalog_writes import EditionState, ReleaseState, state_catalog_graph
from games.commands.endpoint import ActStatement
from games.commands.libraryentry import (
    ENTRY_REMOVED,
    PLAYER_GAME_REMOVED,
    RECORD_UNDER_REMOVED_GAME,
    RELEASE_OF_ANOTHER_GAME,
    RELEASE_REMOVED,
    UNKNOWN_ACCESS,
    UNKNOWN_FORMAT,
    CorrectEntryAcquisition,
    DescribeEntry,
    RecordEntry,
    RemoveEntry,
    RestoreEntry,
)
from games.commands.playergame import RemovePlayerGame
from games.events.dispatch import (
    CommandOutcome,
    CommandRejected,
    CommandResult,
    RowNotHeld,
    RowUnreadable,
    dispatch,
)
from games.models import (
    Game,
    LibraryEntry,
    LibraryEvent,
    PlayerGame,
    Playthrough,
    ProjectionModel,
    Release,
    RemovableLibraryQuerySet,
)
from games.reads import referrers
from games.reads.referrers import BlockingReferrer, referrers_of
from games.removal import remove
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


@pytest.fixture
def shared_graph(owned_library, stated_graph):
    """A shared Game: stated as the library's, then given away."""
    graph = stated_graph(Game(name="Hades", library=owned_library), owned_library)
    Game.objects.filter(pk=graph.game.pk).update(library=None)
    return graph


def _dispatch(library, command, key: str | None = None) -> CommandResult:
    return dispatch(
        command,
        actor=library.user,
        library=library,
        idempotency_key=str(uuid.uuid7()) if key is None else key,
    )


def _refused(library, command) -> CommandRejected:
    with pytest.raises(CommandRejected) as refused:
        _dispatch(library, command)
    return refused.value


def _track(library, game: Game) -> PlayerGame:
    from games.commands.playergame import TrackGame

    _dispatch(library, TrackGame(game_id=game.pk))
    return PlayerGame.objects.get(library=library, game=game)


def _event_types(entry: LibraryEntry) -> list[str]:
    return list(
        LibraryEvent.objects.filter(aggregate_id=entry.pk)
        .order_by("sequence")
        .values_list("event_type", flat=True)
    )


def _second_release(library, graph, *, is_default: bool = True) -> Release:
    """A second live Release on the graph's game."""
    written = state_catalog_graph(
        game=graph.game,
        library=library,
        editions=[
            EditionState(
                key="edition-0",
                edition=graph.edition,
                is_default=True,
                releases=(
                    ReleaseState(
                        key="edition-0-release-0",
                        release=graph.release,
                        is_default=True,
                    ),
                    ReleaseState(key="edition-0-release-1"),
                ),
            )
        ],
    )
    return written.editions[0].releases[1].release


# --- recording ------------------------------------------------------------


def test_recording_on_a_tracked_game_writes_one_event(owned_library, graph):
    tracked = _track(owned_library, graph.game)
    entry = record_entry(
        owned_library, graph.release, note="  gift ", acquired=MAY, acquisition_note="x"
    )

    assert (entry.player_game, entry.release, entry.access, entry.format) == (
        tracked,
        graph.release,
        "owned",
        "digital",
    )
    assert (entry.note, entry.acquired, entry.acquisition_note) == ("gift", MAY, "x")
    created = LibraryEvent.objects.get(aggregate_id=entry.pk)
    assert created.event_type == "library.libraryentry.created"
    assert created.payload["player_game"] == str(tracked.pk)
    assert created.payload["release"]["id"] == str(graph.release.pk)
    assert entry.created_at == created.recorded_at
    assert entry.acquisition_recorded_at == created.recorded_at
    assert (
        LibraryEvent.objects.filter(correlation_id=created.correlation_id).count() == 1
    )


def test_recording_on_an_untracked_game_tracks_it_in_the_same_dispatch(
    owned_library, graph
):
    entry = record_entry(owned_library, graph.release)

    tracked = PlayerGame.objects.get(library=owned_library, game=graph.game)
    assert entry.player_game == tracked
    assert Playthrough.objects.filter(player_game=tracked).count() == 1
    created = LibraryEvent.objects.get(aggregate_id=entry.pk)
    batch = LibraryEvent.objects.filter(correlation_id=created.correlation_id).order_by(
        "sequence"
    )
    assert list(batch.values_list("event_type", flat=True)) == [
        "library.playergame.created",
        "library.playthrough.created",
        "library.libraryentry.created",
    ]


@pytest.mark.parametrize(
    ("access", "format", "sentence"),
    (
        ("stolen", "digital", UNKNOWN_ACCESS),
        ("owned", "cartridge", UNKNOWN_FORMAT),
    ),
)
def test_a_foreign_word_is_refused(owned_library, graph, access, format, sentence):
    refused = _refused(
        owned_library,
        RecordEntry(release_id=graph.release.pk, access=access, format=format),
    )

    assert refused.sentence == sentence
    assert not LibraryEntry.objects.exists()


@pytest.mark.parametrize("level", ("release", "edition", "game"))
def test_a_removed_release_or_parent_is_refused(owned_library, graph, level):
    remove(getattr(graph, level))

    refused = _refused(
        owned_library,
        RecordEntry(release_id=graph.release.pk, access="owned", format="digital"),
    )

    assert refused.sentence == RELEASE_REMOVED


def test_another_librarys_private_release_is_absent(
    owned_library, second_library, stated_graph
):
    theirs = stated_graph(Game(name="Hades", library=second_library), second_library)

    with pytest.raises(RowNotHeld):
        _dispatch(
            owned_library,
            RecordEntry(release_id=theirs.release.pk, access="owned", format="digital"),
        )


def test_a_shared_release_gives_each_library_its_own_row(
    owned_library, second_library, shared_graph
):
    mine = record_entry(owned_library, shared_graph.release)
    theirs = record_entry(second_library, shared_graph.release, access="borrowed")

    assert mine.library == owned_library
    assert theirs.library == second_library
    assert mine.player_game.library == owned_library
    assert theirs.player_game.library == second_library
    assert mine.player_game.game == theirs.player_game.game == shared_graph.game


def test_a_release_under_a_non_default_edition_resolves(owned_library, graph):
    written = state_catalog_graph(
        game=graph.game,
        library=owned_library,
        editions=[
            EditionState(
                key="edition-0", edition=graph.edition, is_default=True, releases=()
            ),
            EditionState(
                key="edition-1",
                name="Deluxe",
                releases=(ReleaseState(key="edition-1-release-0"),),
            ),
        ],
    )
    deluxe = written.editions[1].releases[0].release

    entry = record_entry(owned_library, deluxe)

    assert entry.release == deluxe
    assert entry.player_game.game == graph.game


def test_two_entries_on_one_release_are_two_copies(owned_library, graph):
    first = record_entry(owned_library, graph.release, format="physical")
    second = record_entry(owned_library, graph.release, format="digital")

    assert first.pk != second.pk
    assert LibraryEntry.objects.filter(release=graph.release).count() == 2


def test_recording_under_a_removed_player_game_is_refused(owned_library, graph):
    tracked = _track(owned_library, graph.game)
    _dispatch(owned_library, RemovePlayerGame(game_id=graph.game.pk))

    refused = _refused(
        owned_library,
        RecordEntry(release_id=graph.release.pk, access="owned", format="digital"),
    )

    assert refused.sentence == RECORD_UNDER_REMOVED_GAME
    assert PlayerGame.objects.filter(pk=tracked.pk).count() == 1


# --- describing -----------------------------------------------------------


def test_a_description_states_one_event_per_differing_fact(owned_library, graph):
    entry = record_entry(owned_library, graph.release)
    other = _second_release(owned_library, graph)

    _dispatch(
        owned_library,
        DescribeEntry(
            entry_id=entry.pk,
            access="borrowed",
            format="physical",
            note=" lent ",
            release_id=other.pk,
        ),
    )

    entry.refresh_from_db()
    assert (entry.access, entry.format, entry.note, entry.release) == (
        "borrowed",
        "physical",
        "lent",
        other,
    )
    assert _event_types(entry) == [
        "library.libraryentry.created",
        "library.libraryentry.access_changed",
        "library.libraryentry.format_changed",
        "library.libraryentry.note_changed",
        "library.libraryentry.release_changed",
    ]


def test_a_description_that_changes_nothing_is_unchanged(owned_library, graph):
    entry = record_entry(owned_library, graph.release, note="gift")

    result = _dispatch(
        owned_library,
        DescribeEntry(
            entry_id=entry.pk,
            access="owned",
            format="digital",
            note=" gift ",
            release_id=graph.release.pk,
        ),
    )

    assert result.outcome is CommandOutcome.UNCHANGED
    assert _event_types(entry) == ["library.libraryentry.created"]


def test_a_description_refuses_a_release_of_another_game(
    owned_library, graph, stated_graph
):
    entry = record_entry(owned_library, graph.release)
    other = stated_graph(Game(name="Celeste", library=owned_library), owned_library)

    refused = _refused(
        owned_library, DescribeEntry(entry_id=entry.pk, release_id=other.release.pk)
    )

    assert refused.sentence == RELEASE_OF_ANOTHER_GAME


def test_a_description_refuses_a_removed_release(owned_library, graph):
    entry = record_entry(owned_library, graph.release)
    other = _second_release(owned_library, graph)
    remove(other)

    refused = _refused(
        owned_library, DescribeEntry(entry_id=entry.pk, release_id=other.pk)
    )

    assert refused.sentence == RELEASE_REMOVED


def test_a_description_refuses_another_librarys_release(
    owned_library, second_library, graph, stated_graph
):
    entry = record_entry(owned_library, graph.release)
    theirs = stated_graph(Game(name="Hades", library=second_library), second_library)

    with pytest.raises(RowNotHeld):
        _dispatch(
            owned_library,
            DescribeEntry(entry_id=entry.pk, release_id=theirs.release.pk),
        )


def test_a_description_of_a_removed_entry_is_refused_after_unchanged(
    owned_library, graph
):
    entry = remove_entry(record_entry(owned_library, graph.release))

    same = _dispatch(owned_library, DescribeEntry(entry_id=entry.pk, access="owned"))
    refused = _refused(owned_library, DescribeEntry(entry_id=entry.pk, access="rented"))

    assert same.outcome is CommandOutcome.UNCHANGED
    assert refused.sentence == ENTRY_REMOVED


def test_a_description_under_a_removed_player_game_is_refused(owned_library, graph):
    entry = record_entry(owned_library, graph.release)
    _dispatch(owned_library, RemovePlayerGame(game_id=graph.game.pk))

    refused = _refused(owned_library, DescribeEntry(entry_id=entry.pk, access="rented"))

    assert refused.sentence == PLAYER_GAME_REMOVED


def test_a_description_of_another_librarys_entry_is_absent(
    owned_library, second_library, shared_graph
):
    theirs = record_entry(second_library, shared_graph.release)

    with pytest.raises(RowNotHeld):
        _dispatch(owned_library, DescribeEntry(entry_id=theirs.pk, access="rented"))


# --- correcting the acquisition -------------------------------------------


def test_a_correction_to_the_same_day_is_unchanged(owned_library, graph):
    entry = record_entry(
        owned_library, graph.release, acquired=MAY, acquisition_note="x"
    )

    result = _dispatch(
        owned_library,
        CorrectEntryAcquisition(entry_id=entry.pk, statement=ActStatement(MAY, " x ")),
    )

    assert result.outcome is CommandOutcome.UNCHANGED


def test_a_correction_moves_the_day_and_keeps_the_marker(owned_library, graph):
    entry = record_entry(owned_library, graph.release, acquired=MAY)
    marker = entry.acquisition_recorded_at

    _dispatch(
        owned_library,
        CorrectEntryAcquisition(
            entry_id=entry.pk, statement=ActStatement(JUNE, "receipt")
        ),
    )

    entry.refresh_from_db()
    assert (entry.acquired, entry.acquisition_note) == (JUNE, "receipt")
    assert entry.acquisition_recorded_at == marker
    assert _event_types(entry)[-1] == "library.libraryentry.acquisition_corrected"
    corrected = LibraryEvent.objects.get(
        aggregate_id=entry.pk, event_type="library.libraryentry.acquisition_corrected"
    )
    assert corrected.payload == {"note": "receipt"}


def test_a_correction_to_an_unknown_day_is_a_correction(owned_library, graph):
    entry = record_entry(owned_library, graph.release, acquired=MAY)

    _dispatch(
        owned_library,
        CorrectEntryAcquisition(entry_id=entry.pk, statement=ActStatement(None, "")),
    )

    entry.refresh_from_db()
    assert entry.acquired is None
    assert entry.acquisition_recorded_at is not None


def test_a_correction_of_a_removed_entry_is_refused_after_unchanged(
    owned_library, graph
):
    entry = remove_entry(record_entry(owned_library, graph.release, acquired=MAY))

    same = _dispatch(
        owned_library,
        CorrectEntryAcquisition(entry_id=entry.pk, statement=ActStatement(MAY, "")),
    )
    refused = _refused(
        owned_library,
        CorrectEntryAcquisition(entry_id=entry.pk, statement=ActStatement(JUNE, "")),
    )

    assert same.outcome is CommandOutcome.UNCHANGED
    assert refused.sentence == ENTRY_REMOVED


def test_a_correction_under_a_removed_player_game_is_refused(owned_library, graph):
    entry = record_entry(owned_library, graph.release, acquired=MAY)
    _dispatch(owned_library, RemovePlayerGame(game_id=graph.game.pk))

    refused = _refused(
        owned_library,
        CorrectEntryAcquisition(entry_id=entry.pk, statement=ActStatement(JUNE, "")),
    )

    assert refused.sentence == PLAYER_GAME_REMOVED


# --- removing and restoring -----------------------------------------------


def test_remove_and_restore_move_the_mark(owned_library, graph):
    entry = record_entry(owned_library, graph.release)

    removed = remove_entry(entry)
    assert removed.removed_at is not None
    assert not LibraryEntry.objects.alive().filter(pk=entry.pk).exists()

    restored = restore_entry(entry)
    assert restored.removed_at is None
    assert _event_types(entry) == [
        "library.libraryentry.created",
        "library.libraryentry.removed",
        "library.libraryentry.restored",
    ]


def test_a_repeated_remove_or_restore_is_unchanged(owned_library, graph):
    entry = record_entry(owned_library, graph.release)

    assert (
        _dispatch(owned_library, RestoreEntry(entry_id=entry.pk)).outcome
        is CommandOutcome.UNCHANGED
    )
    remove_entry(entry)
    assert (
        _dispatch(owned_library, RemoveEntry(entry_id=entry.pk)).outcome
        is CommandOutcome.UNCHANGED
    )


def test_remove_and_restore_are_refused_under_a_removed_player_game(
    owned_library, graph
):
    live = record_entry(owned_library, graph.release)
    gone = remove_entry(record_entry(owned_library, graph.release))
    _dispatch(owned_library, RemovePlayerGame(game_id=graph.game.pk))

    assert (
        _refused(owned_library, RemoveEntry(entry_id=live.pk)).sentence
        == PLAYER_GAME_REMOVED
    )
    assert (
        _refused(owned_library, RestoreEntry(entry_id=gone.pk)).sentence
        == PLAYER_GAME_REMOVED
    )
    #: The state a row holds answers ahead of the parent's mark.
    assert (
        _dispatch(owned_library, RemoveEntry(entry_id=gone.pk)).outcome
        is CommandOutcome.UNCHANGED
    )
    assert (
        _dispatch(owned_library, RestoreEntry(entry_id=live.pk)).outcome
        is CommandOutcome.UNCHANGED
    )


@pytest.mark.parametrize("level", ("release", "edition", "game"))
def test_a_restore_is_refused_under_a_removed_release(owned_library, graph, level):
    entry = remove_entry(record_entry(owned_library, graph.release))
    remove(getattr(graph, level))

    refused = _refused(owned_library, RestoreEntry(entry_id=entry.pk))

    assert refused.sentence == RELEASE_REMOVED


def test_an_entry_naming_a_foreign_player_game_is_a_defect(
    owned_library, second_library, graph
):
    """The drift the ownership audit reports; no command writes on it."""
    entry = record_entry(owned_library, graph.release)
    Game.objects.filter(pk=graph.game.pk).update(library=None)
    theirs = _track(second_library, graph.game)
    LibraryEntry.objects.filter(pk=entry.pk).update(player_game=theirs)

    with pytest.raises(RowUnreadable, match=str(theirs.pk)):
        _dispatch(owned_library, DescribeEntry(entry_id=entry.pk, access="rented"))
    assert _event_types(entry) == ["library.libraryentry.created"]


def test_an_entry_naming_a_foreign_private_release_is_a_defect(
    owned_library, second_library, graph, stated_graph
):
    entry = record_entry(owned_library, graph.release)
    theirs = stated_graph(Game(name="Hades", library=second_library), second_library)
    LibraryEntry.objects.filter(pk=entry.pk).update(release=theirs.release)

    with pytest.raises(RowUnreadable, match=str(theirs.release.pk)):
        _dispatch(owned_library, RemoveEntry(entry_id=entry.pk))
    assert _event_types(entry) == ["library.libraryentry.created"]


def test_no_referrer_names_an_entry_yet():
    assert referrers_of(LibraryEntry) == ()


@pytest.fixture
def referring_model():
    """A throwaway projection naming an entry."""
    with isolate_apps("games"):

        class Claim(ProjectionModel):
            id = models.UUIDField(primary_key=True, default=uuid.uuid7)
            entry = models.ForeignKey(LibraryEntry, on_delete=models.RESTRICT)
            removed_at = models.DateTimeField(null=True, default=None)

            objects = RemovableLibraryQuerySet.as_manager()

            class Meta:
                app_label = "games"
                db_table = "test_libraryentry_claim"

        with connection.schema_editor() as schema_editor:
            schema_editor.create_model(Claim)
        try:
            yield Claim
        finally:
            with connection.schema_editor() as schema_editor:
                schema_editor.delete_model(Claim)


CLAIMED_SENTENCE = "Purchases name this copy. Remove them first."


def _register(monkeypatch, referring_model) -> BlockingReferrer:
    """The registry is patched whole."""
    claim = BlockingReferrer.on(
        referring_model, "entry", target=LibraryEntry, sentence=CLAIMED_SENTENCE
    )
    monkeypatch.setattr(referrers, "BLOCKING_REFERRERS", (claim,))
    return claim


def test_a_registered_referrer_keeps_an_entry_in_place(
    owned_library, graph, monkeypatch, referring_model
):
    entry = record_entry(owned_library, graph.release)
    other = record_entry(owned_library, graph.release)
    referring_model.objects.create(entry=entry, library=owned_library)
    _register(monkeypatch, referring_model)

    refused = _refused(owned_library, RemoveEntry(entry_id=entry.pk))
    result = _dispatch(owned_library, RemoveEntry(entry_id=other.pk))

    assert refused.sentence == CLAIMED_SENTENCE
    assert result.outcome is CommandOutcome.APPENDED
    entry.refresh_from_db()
    assert entry.removed_at is None


def test_a_removed_referring_row_keeps_nothing_in_place(
    owned_library, graph, monkeypatch, referring_model
):
    entry = record_entry(owned_library, graph.release)
    referring_model.objects.create(
        entry=entry, library=owned_library, removed_at=timezone.now()
    )
    _register(monkeypatch, referring_model)

    result = _dispatch(owned_library, RemoveEntry(entry_id=entry.pk))

    assert result.outcome is CommandOutcome.APPENDED


def test_a_foreign_referrer_is_refused_as_a_defect(
    owned_library, second_library, graph, monkeypatch, referring_model
):
    entry = record_entry(owned_library, graph.release)
    referring_model.objects.create(entry=entry, library=second_library)
    _register(monkeypatch, referring_model)

    with pytest.raises(RowUnreadable) as refused:
        _dispatch(owned_library, RemoveEntry(entry_id=entry.pk))

    argument = str(refused.value)
    assert str(entry.pk) in argument
    assert str(second_library.pk) in argument
    assert f"{referring_model.__name__}.entry" in argument
    entry.refresh_from_db()
    assert entry.removed_at is None


def test_a_removal_is_recorded_at_the_events_instant(owned_library, graph):
    entry = remove_entry(record_entry(owned_library, graph.release))

    removed = LibraryEvent.objects.get(
        aggregate_id=entry.pk, event_type="library.libraryentry.removed"
    )
    assert entry.removed_at == removed.recorded_at
    assert removed.recorded_at > datetime(2026, 1, 1, tzinfo=UTC)
