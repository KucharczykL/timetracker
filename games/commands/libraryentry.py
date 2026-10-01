"""Commands on one copy of a Release."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from functools import partial
from typing import ClassVar, NamedTuple, cast, get_args

from games.commands.endpoint import (
    ActStatement,
    EndpointSentences,
    Rejection,
    WayActStatement,
    certainly_reversed,
    correct_endpoint,
    correct_opening_endpoint,
    normalized,
    resume_endpoint,
    state_endpoint,
    void_endpoint,
)
from games.commands.playergame import tracking_events
from games.commands.playersession import check_note
from games.commands.scope import Refusal, library_entry_row, visible_row
from games.end_ways import EndWay
from games.endpoints import ENTRY_ACCESS_END, ENTRY_ACQUISITION
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
from games.events.purchase import purchase_removed, purchase_restored
from games.events.references import Reference, entry_reference
from games.events.vocabulary import NewEvent, Unchanged
from games.models import ENTRY_WAYS, LibraryEntry, PlayerGame, Release
from games.reads.endpoints import stated
from games.reads.purchases import cascaded_purchase_ids, unremoved_purchase_ids
from games.reads.referrers import blocking_referrer, foreign_referrer
from timetracker.temporal import TemporalValue

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
UNKNOWN_WAY = "Choose one of the listed ways a copy leaves your hands."
END_BEFORE_ACQUISITION = (
    "This copy was acquired after that day. Correct the acquired day first, "
    "or check the day it ended."
)
RESUME_BEFORE_END = (
    "Access to this copy ended after that day. Correct the end first, or "
    "check the day it came back."
)
ACQUISITION_AFTER_END = (
    "Access to this copy ended before that day. Correct the end first, or "
    "check the day it was acquired."
)

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


def check_way(way: str) -> EndWay:
    """The stated way, or a refusal.

    Ahead of the payload's validation, which answers a
    foreign way with a defect rather than a sentence.
    """
    if way not in ENTRY_WAYS:
        raise CommandRejected(
            f"{way!r} is not a way a copy's access ends.", sentence=UNKNOWN_WAY
        )
    return EndWay(way)


def _access_end_sentences(entry_id: uuid.UUID) -> EndpointSentences:
    return EndpointSentences(
        already_stated=Rejection(
            f"Entry {entry_id} already states an end of access. "
            "CorrectEntryAccessEnd states a better one.",
            "This copy already has an end recorded. Correct the one it has "
            "instead of adding another.",
        ),
        nothing_to_correct=Rejection(
            f"Entry {entry_id} states no end of access, so there is nothing "
            "to correct. A first statement is EndEntryAccess.",
            "This copy has no end to correct. Record how it left first.",
        ),
        same_statement="This copy already states that end.",
        same_correction="This correction states the end the copy states.",
        nothing_to_void=f"Entry {entry_id} states no end of access to take back.",
    )


def _nothing_to_resume(entry_id: uuid.UUID) -> Rejection:
    return Rejection(
        f"Entry {entry_id} states no end of access, so access cannot resume.",
        "This copy has no end recorded, so there is nothing to resume.",
    )


def _refuse_an_end_before_the_acquisition(
    entry: LibraryEntry, *, ended: TemporalValue | None
) -> None:
    if certainly_reversed(earlier=entry.acquired, later=ended):
        raise CommandRejected(
            f"Entry {entry.pk} was acquired after the end being stated, and no "
            "access ends before it begins.",
            sentence=END_BEFORE_ACQUISITION,
        )


def _refuse_a_resume_before_the_end(
    entry: LibraryEntry, *, resumed: TemporalValue | None
) -> None:
    if certainly_reversed(earlier=entry.access_ended, later=resumed):
        raise CommandRejected(
            f"Entry {entry.pk}'s access ended after the resume being stated, "
            "and no access resumes before it ends.",
            sentence=RESUME_BEFORE_END,
        )


def _refuse_an_acquisition_after_the_end(
    entry: LibraryEntry, *, acquired: TemporalValue | None
) -> None:
    if stated(entry, ENTRY_ACCESS_END) is None:
        return
    if certainly_reversed(earlier=acquired, later=entry.access_ended):
        raise CommandRejected(
            f"Entry {entry.pk}'s access ended before the acquisition being "
            "stated, and no access ends before it begins.",
            sentence=ACQUISITION_AFTER_END,
        )


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


def _refuse_a_live_act(entry: LibraryEntry) -> None:
    """Refuse a removed copy or game."""
    _refuse_a_removed_entry(entry)
    _refuse_under_a_removed_game(entry)


def _refuse_a_live_act_after_the_end(
    entry: LibraryEntry, *, acquired: TemporalValue | None
) -> None:
    _refuse_a_live_act(entry)
    _refuse_an_acquisition_after_the_end(entry, acquired=acquired)


def _refuse_a_live_end(entry: LibraryEntry, *, ended: TemporalValue | None) -> None:
    _refuse_a_live_act(entry)
    _refuse_an_end_before_the_acquisition(entry, ended=ended)


def _refuse_a_live_resume(
    entry: LibraryEntry, *, resumed: TemporalValue | None
) -> None:
    _refuse_a_live_act(entry)
    _refuse_a_resume_before_the_end(entry, resumed=resumed)


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


class EntryStatement(NamedTuple):
    """One copy to record; fingerprints by position.

    A new field moves the digest of every command
    holding one: RecordPurchase's new-copy keys.
    """

    release_id: uuid.UUID
    access: EntryAccessValue
    format: EntryFormatValue
    note: str = ""
    acquired: ActStatement = UNDATED_ACQUISITION

    def normalized(self) -> EntryStatement:
        """One spelling, so restatements fingerprint alike."""
        return self._replace(note=self.note.strip(), acquired=normalized(self.acquired))


class CreatedEntry(NamedTuple):
    """A copy's events and its reference."""

    events: tuple[NewEvent, ...]
    reference: Reference


def entry_creation_events(
    context: CommandContext, statement: EntryStatement
) -> CreatedEntry:
    """A copy's creation; tracks an untracked game."""
    access = check_access(statement.access)
    format = check_format(statement.format)
    check_note(statement.note)
    check_note(statement.acquired.note)
    release = _visible_release(context, statement.release_id)
    _refuse_a_removed_release(release)
    game = release.edition.game
    tracked = PlayerGame.objects.filter(library=context.library, game=game).first()
    tracking: list[NewEvent] = []
    if tracked is None:
        tracking = tracking_events(game)
        tracked_id = tracking[0].aggregate_id
    elif tracked.removed_at is not None:
        raise CommandRejected(
            f"This library removed {game.name}, so no copy of it is recorded "
            "until it is restored.",
            sentence=RECORD_UNDER_REMOVED_GAME,
        )
    else:
        tracked_id = tracked.pk
    created = libraryentry_created(
        tracked_id,
        release,
        access=access,
        format=format,
        note=statement.note,
        acquired=statement.acquired.when,
        acquisition_note=statement.acquired.note,
    )
    return CreatedEntry(
        (*tracking, created),
        entry_reference(
            created.aggregate_id, game_name=game.name, access=access, format=format
        ),
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
        statement = EntryStatement(
            release_id=self.release_id,
            access=check_access(self.access),
            format=check_format(self.format),
            note=self.note,
            acquired=self.acquired,
        )
        return entry_creation_events(context, statement).events


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
        if self.note is not None:
            check_note(self.note)
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
        _refuse_a_live_act(entry)
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
        check_note(self.statement.note)
        entry = library_entry_row(context, self.entry_id)
        return correct_opening_endpoint(
            entry,
            ENTRY_ACQUISITION,
            self.statement,
            same_correction="This correction states the day the copy states.",
            before_event=partial(
                _refuse_a_live_act_after_the_end, entry, acquired=self.statement.when
            ),
        )


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
        return [
            *(
                purchase_removed(purchase_id)
                for purchase_id in unremoved_purchase_ids(context.library, entry.pk)
            ),
            libraryentry_removed(entry.pk),
        ]


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
        #: RestorePurchase refuses under removed copies.
        return [
            libraryentry_restored(entry.pk),
            *(
                purchase_restored(purchase_id)
                for purchase_id in cascaded_purchase_ids(context.library, entry.pk)
            ),
        ]


@dataclass(frozen=True, slots=True)
class EndEntryAccess(Command):
    """The copy's access ended."""

    command_name: ClassVar[CommandName] = CommandName.LIBRARYENTRY_END_ACCESS
    entry_id: uuid.UUID
    statement: WayActStatement

    def __post_init__(self) -> None:
        object.__setattr__(self, "statement", normalized(self.statement))

    def build(self, context: CommandContext) -> Sequence[NewEvent] | Unchanged:
        check_note(self.statement.note)
        entry = library_entry_row(context, self.entry_id)
        way = check_way(self.statement.way)
        return state_endpoint(
            entry,
            ENTRY_ACCESS_END,
            self.statement._replace(way=way),
            sentences=_access_end_sentences(entry.pk),
            before_event=partial(_refuse_a_live_end, entry, ended=self.statement.when),
        )


@dataclass(frozen=True, slots=True)
class CorrectEntryAccessEnd(Command):
    """Restate an end already stated."""

    command_name: ClassVar[CommandName] = CommandName.LIBRARYENTRY_CORRECT_ACCESS_END
    entry_id: uuid.UUID
    statement: WayActStatement

    def __post_init__(self) -> None:
        object.__setattr__(self, "statement", normalized(self.statement))

    def build(self, context: CommandContext) -> Sequence[NewEvent] | Unchanged:
        check_note(self.statement.note)
        entry = library_entry_row(context, self.entry_id)
        way = check_way(self.statement.way)
        return correct_endpoint(
            entry,
            ENTRY_ACCESS_END,
            self.statement._replace(way=way),
            sentences=_access_end_sentences(entry.pk),
            before_event=partial(_refuse_a_live_end, entry, ended=self.statement.when),
        )


@dataclass(frozen=True, slots=True)
class VoidEntryAccessEnd(Command):
    """Take back the record that access ended."""

    command_name: ClassVar[CommandName] = CommandName.LIBRARYENTRY_VOID_ACCESS_END
    entry_id: uuid.UUID

    def build(self, context: CommandContext) -> Sequence[NewEvent] | Unchanged:
        entry = library_entry_row(context, self.entry_id)
        return void_endpoint(
            entry,
            ENTRY_ACCESS_END,
            sentences=_access_end_sentences(entry.pk),
            before_event=partial(_refuse_a_live_act, entry),
        )


@dataclass(frozen=True, slots=True)
class ResumeEntryAccess(Command):
    """Access to an ended copy resumed."""

    command_name: ClassVar[CommandName] = CommandName.LIBRARYENTRY_RESUME_ACCESS
    entry_id: uuid.UUID
    statement: ActStatement

    def __post_init__(self) -> None:
        object.__setattr__(self, "statement", normalized(self.statement))

    def build(self, context: CommandContext) -> Sequence[NewEvent] | Unchanged:
        check_note(self.statement.note)
        entry = library_entry_row(context, self.entry_id)
        return resume_endpoint(
            entry,
            ENTRY_ACCESS_END,
            self.statement,
            nothing_to_resume=_nothing_to_resume(entry.pk),
            before_event=partial(
                _refuse_a_live_resume, entry, resumed=self.statement.when
            ),
        )
