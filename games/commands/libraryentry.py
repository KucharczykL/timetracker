"""Commands on one copy of a Release."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from functools import partial
from typing import ClassVar, cast, get_args

from games.commands.endpoint import ActStatement, correct_opening_endpoint
from games.commands.playergame import tracking_events
from games.commands.scope import Refusal, library_entry_row, visible_row
from games.endpoints import ENTRY_ACQUISITION
from games.events.dispatch import (
    Command,
    CommandContext,
    CommandName,
    CommandRejected,
    RowUnreadable,
)
from games.events.libraryentry import (
    EntryAccessValue,
    EntryFormatValue,
    libraryentry_access_changed,
    libraryentry_created,
    libraryentry_format_changed,
    libraryentry_note_changed,
    libraryentry_release_changed,
    libraryentry_removed,
    libraryentry_restored,
)
from games.events.vocabulary import NewEvent, Unchanged
from games.models import LibraryEntry, PlayerGame, Release
from games.reads.referrers import blocking_referrer, foreign_referrer
from timetracker.temporal import stated_date

UNKNOWN_ACCESS = "Choose one of the listed access words."
UNKNOWN_FORMAT = "Choose one of the listed formats."
RELEASE_REMOVED = (
    "That release was removed from the catalog. Choose another, or restore it."
)
RELEASE_OF_ANOTHER_GAME = (
    "That release belongs to another game. Choose a release of this one."
)
PLAYER_GAME_REMOVED = (
    "That game was removed from your library. Restore it before changing its copies."
)
RECORD_UNDER_REMOVED_GAME = (
    "That game was removed from your library. Restore it before recording a copy."
)
ENTRY_REMOVED = "That copy was removed. Put it back before changing what it records."

#: An acquisition with no stated day.
UNDATED_ACQUISITION = ActStatement(None, "")


ACCESS_WORDS: frozenset[str] = frozenset(get_args(EntryAccessValue.__value__))
FORMAT_WORDS: frozenset[str] = frozenset(get_args(EntryFormatValue.__value__))


def check_access(access: str) -> EntryAccessValue:
    """The payload's access word, or a refusal."""
    if access not in ACCESS_WORDS:
        raise CommandRejected(
            f"{access!r} is not an access word.", sentence=UNKNOWN_ACCESS
        )
    return cast(EntryAccessValue, access)


def check_format(format: str) -> EntryFormatValue:
    """The payload's format word, or a refusal."""
    if format not in FORMAT_WORDS:
        raise CommandRejected(f"{format!r} is not a format.", sentence=UNKNOWN_FORMAT)
    return cast(EntryFormatValue, format)


def normalized(statement: ActStatement) -> ActStatement:
    """One spelling, so restatements fingerprint alike."""
    return ActStatement(stated_date(statement.when), statement.note.strip())


def _visible_release(context: CommandContext, release_id: uuid.UUID) -> Release:
    """A visible Release, removed or not."""
    return visible_row(
        context,
        Release.objects.select_related("edition__game"),
        Refusal(
            message=(
                f"No release {release_id} this library can see. A copy names "
                "a release of its own catalog or the shared one."
            )
        ),
        pk=release_id,
    )


def _refuse_a_removed_release(release: Release) -> None:
    """Refuse a Release a mark hides."""
    if not Release.objects.alive().filter(pk=release.pk).exists():
        raise CommandRejected(
            f"Release {release.pk} or one of its parents is removed, so no "
            "copy names it.",
            sentence=RELEASE_REMOVED,
        )


def _refuse_under_a_removed_game(entry: LibraryEntry) -> None:
    #: Under dispatch's lock; the mark cannot move.
    if entry.player_game.removed_at is not None:
        raise CommandRejected(
            f"This library removed the game behind entry {entry.pk}, so it "
            "states no further facts about the copy.",
            sentence=PLAYER_GAME_REMOVED,
        )


def _refuse_a_removed_entry(entry: LibraryEntry) -> None:
    #: Under dispatch's lock; the mark cannot move.
    if entry.removed_at is not None:
        raise CommandRejected(
            f"This library removed entry {entry.pk}, so it states no further "
            "facts about it.",
            sentence=ENTRY_REMOVED,
        )


def _refuse_a_foreign_referrer(entry: LibraryEntry) -> None:
    """Refuse a foreign row naming the entry."""
    foreign = foreign_referrer(entry)
    if foreign is None:
        return
    library_keys = ", ".join(str(library_id) for library_id in foreign.library_ids)
    raise RowUnreadable(
        f"A live {foreign.referrer.model.__name__}.{foreign.referrer.field_name} "
        f"of libraries {library_keys} names entry {entry.pk} of library "
        f"{entry.library_id}; the ownership audit reports it, and removing the "
        "entry would strand it."
    )


@dataclass(frozen=True, slots=True)
class RecordEntry(Command):
    """State a copy, tracking an untracked game."""

    command_name: ClassVar[CommandName] = CommandName.LIBRARYENTRY_RECORD
    release_id: uuid.UUID
    access: str
    format: str
    note: str = ""
    acquired: ActStatement = UNDATED_ACQUISITION

    def __post_init__(self) -> None:
        #: One spelling, so restatements fingerprint alike.
        object.__setattr__(self, "note", self.note.strip())
        object.__setattr__(self, "acquired", normalized(self.acquired))

    def build(self, context: CommandContext) -> Sequence[NewEvent] | Unchanged:
        access = check_access(self.access)
        format = check_format(self.format)
        release = _visible_release(context, self.release_id)
        _refuse_a_removed_release(release)
        game = release.edition.game
        tracked = PlayerGame.objects.filter(library=context.library, game=game).first()
        events: list[NewEvent] = []
        if tracked is None:
            events = tracking_events(game)
            tracked_id = events[0].aggregate_id
        elif tracked.removed_at is not None:
            raise CommandRejected(
                f"This library removed {game.name}, so no copy of it is recorded "
                "until it is restored.",
                sentence=RECORD_UNDER_REMOVED_GAME,
            )
        else:
            tracked_id = tracked.pk
        events.append(
            libraryentry_created(
                tracked_id,
                release,
                access=access,
                format=format,
                note=self.note,
                acquired=self.acquired.when,
                acquisition_note=self.acquired.note,
            )
        )
        return events


@dataclass(frozen=True, slots=True)
class DescribeEntry(Command):
    """State access, format, note, Release, or several."""

    command_name: ClassVar[CommandName] = CommandName.LIBRARYENTRY_DESCRIBE
    entry_id: uuid.UUID
    access: str | None = None
    format: str | None = None
    note: str | None = None
    release_id: uuid.UUID | None = None

    def __post_init__(self) -> None:
        if self.note is not None:
            object.__setattr__(self, "note", self.note.strip())

    def build(self, context: CommandContext) -> Sequence[NewEvent] | Unchanged:
        access = None if self.access is None else check_access(self.access)
        format = None if self.format is None else check_format(self.format)
        entry = library_entry_row(context, self.entry_id)
        release = (
            None
            if self.release_id is None
            else _visible_release(context, self.release_id)
        )
        events: list[NewEvent] = []
        if access is not None and access != entry.access:
            events.append(libraryentry_access_changed(entry.pk, access))
        if format is not None and format != entry.format:
            events.append(libraryentry_format_changed(entry.pk, format))
        if self.note is not None and self.note != entry.note:
            events.append(libraryentry_note_changed(entry.pk, self.note))
        if release is not None and release.pk != entry.release_id:
            _refuse_a_removed_release(release)
            if release.edition.game_id != entry.player_game.game_id:
                raise CommandRejected(
                    f"Release {release.pk} belongs to game "
                    f"{release.edition.game_id}, and entry {entry.pk} records "
                    f"game {entry.player_game.game_id}.",
                    sentence=RELEASE_OF_ANOTHER_GAME,
                )
            events.append(libraryentry_release_changed(entry.pk, release))
        if not events:
            return Unchanged("This copy already states that.")
        _refuse_a_removed_entry(entry)
        _refuse_under_a_removed_game(entry)
        return events


@dataclass(frozen=True, slots=True)
class CorrectEntryAcquisition(Command):
    """Restate the day the copy was acquired."""

    command_name: ClassVar[CommandName] = CommandName.LIBRARYENTRY_CORRECT_ACQUISITION
    entry_id: uuid.UUID
    statement: ActStatement

    def __post_init__(self) -> None:
        object.__setattr__(self, "statement", normalized(self.statement))

    def build(self, context: CommandContext) -> Sequence[NewEvent] | Unchanged:
        entry = library_entry_row(context, self.entry_id)
        return correct_opening_endpoint(
            entry,
            ENTRY_ACQUISITION,
            self.statement,
            same_correction="This correction states the day the copy states.",
            before_event=partial(_refuse_a_live_act, entry),
        )


def _refuse_a_live_act(entry: LibraryEntry) -> None:
    _refuse_a_removed_entry(entry)
    _refuse_under_a_removed_game(entry)


@dataclass(frozen=True, slots=True)
class RemoveEntry(Command):
    """Mark a copy removed; nothing is destroyed."""

    command_name: ClassVar[CommandName] = CommandName.LIBRARYENTRY_REMOVE
    entry_id: uuid.UUID

    def build(self, context: CommandContext) -> Sequence[NewEvent] | Unchanged:
        entry = library_entry_row(context, self.entry_id)
        #: No-op first; a repeat succeeds.
        if entry.removed_at is not None:
            return Unchanged(f"This library already removed entry {entry.pk}.")
        _refuse_under_a_removed_game(entry)
        blocker = blocking_referrer(entry)
        if blocker is not None:
            raise CommandRejected(
                f"A live {blocker.model.__name__} names entry {entry.pk}, so "
                "the copy stays where it can be found.",
                sentence=blocker.sentence,
            )
        _refuse_a_foreign_referrer(entry)
        return [libraryentry_removed(entry.pk)]


@dataclass(frozen=True, slots=True)
class RestoreEntry(Command):
    """Put a removed copy back."""

    command_name: ClassVar[CommandName] = CommandName.LIBRARYENTRY_RESTORE
    entry_id: uuid.UUID

    def build(self, context: CommandContext) -> Sequence[NewEvent] | Unchanged:
        entry = library_entry_row(context, self.entry_id)
        if entry.removed_at is None:
            return Unchanged(f"Entry {entry.pk} is already in this library.")
        _refuse_under_a_removed_game(entry)
        _refuse_a_removed_release(entry.release)
        return [libraryentry_restored(entry.pk)]
