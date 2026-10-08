"""Entry rows rebuilt from events."""

import uuid

import pytest
from django.db import connection, transaction
from django.utils import timezone
from entries import record_entry, remove_entry, restore_entry
from graphs import default_graph

from games.commands.endpoint import ActStatement
from games.commands.libraryentry import CorrectEntryAcquisition, DescribeEntry
from games.events.dispatch import append_command
from games.events.rebuild import RebuildMode, rebuild_projections
from games.events.reconcile import UnresolvedReferences, reconcile_references
from games.models import (
    Game,
    LibraryEntry,
    LibraryEvent,
    LibraryEventReference,
    PlayerGame,
)
from timetracker.temporal import TemporalValue

pytestmark = [pytest.mark.untracked_games, pytest.mark.django_db(transaction=True)]

MAY = TemporalValue.parse("2021-05")


@pytest.fixture
def graph(owned_library):
    return default_graph(Game(name="Tunic", library=owned_library), owned_library)


def _entries_drift(library) -> list[tuple[int, int, int]]:
    report = rebuild_projections(library, mode=RebuildMode.CHECK)
    return [
        (table.only_live, table.only_rebuilt, table.differing)
        for table in report.tables
        if table.table == "games_libraryentry"
    ]


def _append(library, command) -> None:
    with transaction.atomic():
        append_command(
            command,
            actor=library.user,
            library=library,
            idempotency_key=str(uuid.uuid7()),
            correlation_id=uuid.uuid7(),
        )


def test_every_event_replays_to_the_same_rows(owned_library, graph):
    kept = record_entry(owned_library, graph.release, acquired=MAY)
    _append(
        owned_library,
        DescribeEntry(
            entry_id=kept.pk, access="borrowed", format="physical", note="lent"
        ),
    )
    _append(
        owned_library,
        CorrectEntryAcquisition(entry_id=kept.pk, statement=ActStatement(None, "x")),
    )
    restore_entry(remove_entry(record_entry(owned_library, graph.release)))
    remove_entry(record_entry(owned_library, graph.release, format="unknown"))
    before = list(LibraryEntry.objects.order_by("pk").values())

    assert _entries_drift(owned_library) == [(0, 0, 0)]
    assert list(LibraryEntry.objects.order_by("pk").values()) == before


def test_a_rebuild_puts_back_a_drifted_row(owned_library, graph):
    entry = record_entry(owned_library, graph.release)
    before = LibraryEntry.objects.filter(pk=entry.pk).values().get()
    LibraryEntry.objects.filter(pk=entry.pk).update(note="Drifted")

    assert _entries_drift(owned_library) == [(0, 0, 1)]
    rebuild_projections(owned_library, mode=RebuildMode.REBUILD)
    assert LibraryEntry.objects.filter(pk=entry.pk).values().get() == before


def test_a_lost_row_is_rebuilt_rather_than_refused(owned_library, graph):
    """PROJECTED: a lost row is rebuilt."""
    entry = record_entry(owned_library, graph.release)
    before = LibraryEntry.objects.filter(pk=entry.pk).values().get()
    with connection.cursor() as cursor:
        #: Bypass the ORM guard: a lost row.
        cursor.execute("DELETE FROM games_libraryentry WHERE id = %s", [entry.pk])

    assert reconcile_references(owned_library).resolves
    rebuild_projections(owned_library, mode=RebuildMode.REBUILD)

    assert LibraryEntry.objects.filter(pk=entry.pk).values().get() == before


def test_a_stream_naming_an_entry_it_never_created_is_refused(owned_library, graph):
    """The stream check catches uncreated entries."""
    record_entry(owned_library, graph.release)
    stray = LibraryEntry.objects.create(
        id=uuid.uuid7(),
        library=owned_library,
        player_game=PlayerGame.objects.get(library=owned_library, game=graph.game),
        release=graph.release,
        access="owned",
        format="digital",
        acquisition_recorded_at=timezone.now(),
        created_at=timezone.now(),
    )
    live = LibraryEvent.objects.filter(library=owned_library).latest("sequence")
    #: A reference naming the stray; nothing creates one today.
    LibraryEventReference.objects.create(
        library=owned_library,
        event=live,
        kind="libraryentry",
        referenced_id=stray.pk,
        payload_key="entry",
    )

    with pytest.raises(UnresolvedReferences, match=str(stray.pk)):
        rebuild_projections(owned_library, mode=RebuildMode.CHECK)
