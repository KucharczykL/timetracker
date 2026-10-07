"""Test entries via append_command; dispatch cannot nest."""

import uuid

from django.db import transaction

from games.catalog_writes import EditionState, ReleaseState, state_catalog_graph
from games.commands.endpoint import ActStatement, WayActStatement
from games.commands.libraryentry import (
    EndEntryAccess,
    RecordEntry,
    RemoveEntry,
    RestoreEntry,
    ResumeEntryAccess,
)
from games.end_ways import EndWay
from games.events.append import SourceMetadata
from games.events.dispatch import Command, CommandResult, append_command
from games.models import EditionKind, LibraryEntry, LibraryEvent, Release, UserLibrary
from timetracker.temporal import TemporalValue


def _state(
    library: UserLibrary,
    command: Command,
    source_metadata: SourceMetadata | None = None,
) -> CommandResult:
    with transaction.atomic():
        return append_command(
            command,
            actor=library.user,
            library=library,
            idempotency_key=str(uuid.uuid7()),
            correlation_id=uuid.uuid7(),
            source_metadata=source_metadata,
        )


def second_release(library: UserLibrary, release: Release) -> Release:
    """A second live Release beside the default one."""
    edition = release.edition
    written = state_catalog_graph(
        game=edition.game,
        library=library,
        editions=[
            EditionState(
                key="edition-0",
                edition=edition,
                is_default=True,
                releases=(
                    ReleaseState(
                        key="edition-0-release-0", release=release, is_default=True
                    ),
                    ReleaseState(key="edition-0-release-1"),
                ),
            )
        ],
    )
    return written.editions[0].releases[1].release


def prerelease_release(library: UserLibrary, release: Release) -> Release:
    """A prerelease Edition's Release beside this one."""
    edition = release.edition
    written = state_catalog_graph(
        game=edition.game,
        library=library,
        editions=[
            EditionState(
                key="edition-0",
                edition=edition,
                is_default=True,
                releases=(
                    ReleaseState(
                        key="edition-0-release-0", release=release, is_default=True
                    ),
                ),
            ),
            EditionState(
                key="edition-1",
                kind=EditionKind.PRERELEASE,
                releases=(ReleaseState(key="edition-1-release-0", is_default=True),),
            ),
        ],
    )
    return written.editions[1].releases[0].release


def record_entry(
    library: UserLibrary,
    release: Release,
    *,
    access: str = "owned",
    format: str = "digital",
    note: str = "",
    acquired: TemporalValue | None = None,
    acquisition_note: str = "",
    source_metadata: SourceMetadata | None = None,
) -> LibraryEntry:
    """A live entry by event; tracks the game."""
    result = _state(
        library,
        RecordEntry(
            release_id=release.pk,
            access=access,
            format=format,
            note=note,
            acquired=ActStatement(acquired, acquisition_note),
        ),
        source_metadata,
    )
    assert result.sequences is not None
    #: The creation is the dispatch's last event.
    created = LibraryEvent.objects.get(
        stream_id=result.stream_id, sequence=result.sequences.last
    )
    return LibraryEntry.objects.get(pk=created.aggregate_id)


def remove_entry(entry: LibraryEntry) -> LibraryEntry:
    _state(entry.library, RemoveEntry(entry_id=entry.pk))
    entry.refresh_from_db()
    return entry


def restore_entry(entry: LibraryEntry) -> LibraryEntry:
    _state(entry.library, RestoreEntry(entry_id=entry.pk))
    entry.refresh_from_db()
    return entry


def end_entry_access(
    entry: LibraryEntry,
    *,
    way: EndWay = EndWay.RETURNED,
    ended: TemporalValue | None = None,
    note: str = "",
) -> LibraryEntry:
    _state(
        entry.library,
        EndEntryAccess(entry_id=entry.pk, statement=WayActStatement(ended, way, note)),
    )
    entry.refresh_from_db()
    return entry


def resume_entry_access(entry: LibraryEntry) -> LibraryEntry:
    _state(
        entry.library,
        ResumeEntryAccess(entry_id=entry.pk, statement=ActStatement(None, "")),
    )
    entry.refresh_from_db()
    return entry
