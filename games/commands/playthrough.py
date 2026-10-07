"""Commands about the runs a library records."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from functools import partial
from typing import ClassVar, NamedTuple, cast

from django.db.models import QuerySet

from games.commands.batch_undo import UndoSentences, refuse_unless_this_batch_wrote_it
from games.commands.endpoint import (
    ActStatement,
    EndpointSentences,
    Rejection,
    certainly_reversed,
    correct_endpoint,
    state_endpoint,
    void_endpoint,
)
from games.commands.playergame import (
    HeldGame,
    implied_if,
    tracked_game,
    tracking_event,
    with_implied_status,
)
from games.commands.scope import Refusal, library_row, visible_row
from games.endpoints import PLAYTHROUGH_COMPLETION, PLAYTHROUGH_START, Endpoint
from games.events.dispatch import (
    Command,
    CommandContext,
    CommandName,
    CommandRejected,
    RowNotHeld,
    RowUnreadable,
)
from games.events.historical_playtime import historicalplaytime_moved
from games.events.playersession import playersession_release_changed
from games.events.playthrough import (
    playthrough_completed,
    playthrough_created,
    playthrough_moved,
    playthrough_name_changed,
    playthrough_note_changed,
    playthrough_removed,
    playthrough_restored,
    playthrough_started,
)
from games.events.vocabulary import NewEvent, Unchanged
from games.ids import GameId, HistoricalPlaytimeId, PlayerGameId, PlayerSessionId
from games.models import (
    Game,
    HistoricalPlaytime,
    HistoricalPlaytimeRun,
    ImpliedStatus,
    PlayerGame,
    PlayerGameStatus,
    PlayerSession,
    Playthrough,
    PlaythroughKind,
)
from games.reads.playthrough_endpoints import stated_completion, stated_start
from games.reads.referrers import (
    blocking_referrer,
    foreign_referrer,
)
from timetracker.temporal import TemporalValue, stated_date

#: Read off the column, so the refusal and the constraint cannot drift.
PLAYTHROUGH_NAME_MAX_LENGTH: int = cast(
    int, Playthrough._meta.get_field("name").max_length
)


def refuse_name_the_column_cannot_hold(name: str) -> None:
    """Refuse a name longer than the column holds.

    In a build, not a __post_init__: a refusal carries a
    sentence, and a value error carries none.
    """
    if len(name) <= PLAYTHROUGH_NAME_MAX_LENGTH:
        return
    raise CommandRejected(
        f"The stated name is {len(name)} characters, and the "
        f"column holds {PLAYTHROUGH_NAME_MAX_LENGTH}.",
        sentence=(
            "That name is too long. Keep it to "
            f"{PLAYTHROUGH_NAME_MAX_LENGTH} characters or fewer."
        ),
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class CreatePlaythrough(Command):
    """State one more run at a game.

    One build rather than four dispatches: a creation that
    commits before a failed start leaves a run with no act,
    and RemovePlaythrough refuses the last live ordinary
    run of a tracked game.
    """

    command_name: ClassVar[CommandName] = CommandName.PLAYTHROUGH_CREATE
    #: A UUID, because Command fingerprints its fields.
    game_id: uuid.UUID
    #: None is an act that never happened.
    started: ActStatement | None = None
    completed: ActStatement | None = None
    note: str = ""
    #: No default: every caller decides.
    implies_played: bool
    implies_completed: bool

    def __post_init__(self) -> None:
        for field_name in ("started", "completed"):
            act = cast(ActStatement | None, getattr(self, field_name))
            if act is not None:
                #: One spelling of no day and no note,
                #: so a restatement fingerprints alike.
                object.__setattr__(
                    self,
                    field_name,
                    ActStatement(stated_date(act.when), act.note.strip()),
                )
        object.__setattr__(self, "note", self.note.strip())

    def build(self, context: CommandContext) -> Sequence[NewEvent] | Unchanged:
        tracked = tracked_game(context, self.game_id)
        #: Under dispatch's lock: the mark cannot move.
        if tracked.removed_at is not None:
            raise CommandRejected(
                f"This library removed game {self.game_id}, so it records no "
                "further runs at it. A removed game is restored first.",
                sentence=(
                    "That game was removed from your library. Restore it "
                    "before adding a playthrough."
                ),
            )
        if certainly_reversed(
            earlier=None if self.started is None else self.started.when,
            later=None if self.completed is None else self.completed.when,
        ):
            raise CommandRejected(
                f"The run being created at game {self.game_id} would complete "
                "before it began, and no run ends before it begins.",
                sentence="This run finished before it started. Check the days.",
            )
        #: Minted here, so every event names it.
        run_id = uuid.uuid7()
        events: list[NewEvent] = [
            playthrough_created(tracked.pk, playthrough_id=run_id)
        ]
        if self.note:
            events.append(playthrough_note_changed(run_id, note=self.note))
        if self.started is not None:
            events.append(
                playthrough_started(
                    run_id, when=self.started.when, note=self.started.note
                )
            )
        if self.completed is not None:
            events.append(
                playthrough_completed(
                    run_id, when=self.completed.when, note=self.completed.note
                )
            )
        return with_implied_status(context, events, HeldGame(tracked), self._implied())

    def _implied(self) -> ImpliedStatus | None:
        """Completed over Played: one status at most."""
        if self.implies_completed and self.completed is not None:
            return PlayerGameStatus.COMPLETED
        if self.implies_played and self.started is not None:
            return PlayerGameStatus.PLAYED
        return None


@dataclass(frozen=True, slots=True)
class RecordPlaythroughByName(Command):
    """State the run a person named at a game.

    One command rather than a read and a dispatch: the
    build runs under the stream head's lock, and a
    session recorded between a read and an append would
    be carried under a name nobody gave it.

    The placeholder tracking minted is named rather than
    left beside the new run. Creating one regardless
    would leave a never-played game holding a blank run
    forever, which is what `record_run` adopts to avoid;
    adopting as widely as `record_run` does would rename
    a run that already holds sessions.
    """

    command_name: ClassVar[CommandName] = CommandName.PLAYTHROUGH_RECORD_BY_NAME
    #: A UUID, because Command fingerprints its fields.
    game_id: uuid.UUID
    name: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", self.name.strip())

    def build(self, context: CommandContext) -> Sequence[NewEvent] | Unchanged:
        #: Function-local: that module reads this one's registry.
        from games.reads.playthrough_runs import (
            live_ordinary_runs,
            placeholder_run,
        )

        tracked = tracked_game(context, self.game_id)
        #: Under dispatch's lock: the mark cannot move.
        if tracked.removed_at is not None:
            raise CommandRejected(
                f"This library removed game {self.game_id}, so it records no "
                "further runs at it. A removed game is restored first.",
                sentence=(
                    "That game was removed from your library. Restore it "
                    "before adding a playthrough."
                ),
            )
        if not self.name:
            raise CommandRejected(
                f"A run at game {self.game_id} was stated with no name, and "
                "this command states nothing else about it.",
                sentence="Type a name for the playthrough.",
            )
        refuse_name_the_column_cannot_hold(self.name)
        #: Ahead of the placeholder read: a run already called this
        #: is the run the person named. Case is ignored, as the
        #: create row ignores it.
        if (
            live_ordinary_runs(context.library, tracked)
            .filter(name__iexact=self.name)
            .exists()
        ):
            return Unchanged("This game already holds a run of that name.")
        adopted = placeholder_run(context.library, tracked)
        if adopted is None:
            run_id = uuid.uuid7()
            return [
                playthrough_created(tracked.pk, playthrough_id=run_id),
                playthrough_name_changed(run_id, name=self.name),
            ]
        return [playthrough_name_changed(adopted.pk, name=self.name)]


class PlaythroughNotHeld(RowNotHeld):
    """The library holds no such run; caught by name."""


def library_playthrough(
    context: CommandContext, playthrough_id: uuid.UUID
) -> Playthrough:
    """This library's run, or a refusal."""
    return library_row(
        context,
        #: Every caller reads the parent's mark.
        Playthrough.objects.select_related("player_game"),
        Refusal(
            message=(
                f"This library holds no playthrough {playthrough_id}. A stated "
                "fact belongs to a run the library records."
            ),
            raises=PlaythroughNotHeld,
        ),
        pk=playthrough_id,
    )


def _live_run(context: CommandContext, playthrough_id: uuid.UUID) -> Playthrough:
    """The run, refused if nothing may be stated about it."""
    return refuse_unless_live(library_playthrough(context, playthrough_id))


def refuse_unless_live(run: Playthrough) -> Playthrough:
    """Refuse a run under either mark."""
    playthrough_id = run.pk
    #: Under dispatch's lock: neither mark can move.
    if run.player_game.removed_at is not None:
        raise CommandRejected(
            f"This library removed the game behind playthrough {playthrough_id}, "
            "so it states no further facts about its runs.",
            sentence=(
                "That game was removed from your library. Restore it before "
                "recording this."
            ),
        )
    if run.removed_at is not None:
        raise CommandRejected(
            f"This library removed playthrough {playthrough_id}, so it states "
            "no further facts about it.",
            sentence=(
                "That playthrough was removed from your library. Restore it "
                "before recording this."
            ),
        )
    return run


@dataclass(frozen=True, slots=True)
class StartPlaythrough(Command):
    """State that a run began."""

    command_name: ClassVar[CommandName] = CommandName.PLAYTHROUGH_START
    #: A UUID, because Command fingerprints its fields.
    playthrough_id: uuid.UUID
    #: None is "played before": the act, and no day.
    when: TemporalValue | None
    #: No default: the build compares the whole endpoint.
    note: str
    #: Played, where the game is Unplayed.
    implies_status: bool

    def __post_init__(self) -> None:
        #: One spelling of no day, so a restatement fingerprints alike.
        object.__setattr__(self, "when", stated_date(self.when))
        #: One spelling of a blank note, for the same reason.
        object.__setattr__(self, "note", self.note.strip())

    def build(self, context: CommandContext) -> Sequence[NewEvent] | Unchanged:
        run = _live_run(context, self.playthrough_id)
        acts = state_endpoint(
            run,
            PLAYTHROUGH_START,
            ActStatement(self.when, self.note),
            sentences=_start_sentences(run.pk),
            before_event=partial(
                _refuse_a_start_after_the_completion, run, started=self.when
            ),
        )
        return with_implied_status(
            context,
            acts,
            HeldGame(run.player_game),
            implied_if(self.implies_status, PlayerGameStatus.PLAYED),
        )


@dataclass(frozen=True, slots=True)
class CompletePlaythrough(Command):
    """State that a run met its main objective."""

    command_name: ClassVar[CommandName] = CommandName.PLAYTHROUGH_COMPLETE
    #: A UUID, because Command fingerprints its fields.
    playthrough_id: uuid.UUID
    when: TemporalValue | None
    note: str
    #: Completed, wherever the game is not.
    implies_status: bool

    def __post_init__(self) -> None:
        #: One spelling of no day, so a restatement fingerprints alike.
        object.__setattr__(self, "when", stated_date(self.when))
        #: One spelling of a blank note, for the same reason.
        object.__setattr__(self, "note", self.note.strip())

    def build(self, context: CommandContext) -> Sequence[NewEvent] | Unchanged:
        run = _live_run(context, self.playthrough_id)
        acts = state_endpoint(
            run,
            PLAYTHROUGH_COMPLETION,
            ActStatement(self.when, self.note),
            sentences=_completion_sentences(run.pk),
            before_event=partial(
                _refuse_a_completion_before_the_start, run, completed=self.when
            ),
        )
        return with_implied_status(
            context,
            acts,
            HeldGame(run.player_game),
            implied_if(self.implies_status, PlayerGameStatus.COMPLETED),
        )


@dataclass(frozen=True, slots=True)
class DescribePlaythrough(Command):
    """State the run's name, its note, or both."""

    command_name: ClassVar[CommandName] = CommandName.PLAYTHROUGH_DESCRIBE
    #: A UUID, because Command fingerprints its fields.
    playthrough_id: uuid.UUID
    #: None states no fact. "" clears the value.
    name: str | None
    note: str | None

    def __post_init__(self) -> None:
        if self.name is None and self.note is None:
            raise ValueError(
                "DescribePlaythrough states no fact. A command that asks for "
                "nothing would still claim an idempotency key and write a "
                "record for a request that expressed no intent."
            )
        #: Three spaces is a cleared value, for either fact.
        if self.name is not None:
            object.__setattr__(self, "name", self.name.strip())
        if self.note is not None:
            object.__setattr__(self, "note", self.note.strip())

    def build(self, context: CommandContext) -> Sequence[NewEvent] | Unchanged:
        run = _live_run(context, self.playthrough_id)
        if self.name is not None:
            refuse_name_the_column_cannot_hold(self.name)
        #: Only a name being taken away. A row born blank is left as it
        #: is, so a save that repeats that blank still states its note.
        if self.name == "" and run.name != "" and run.kind != PlaythroughKind.ORDINARY:
            raise CommandRejected(
                f"Playthrough {self.playthrough_id} is of kind {run.kind}, which "
                "no display number is counted across, so a blank name would "
                "leave the run with nothing to be called.",
                sentence=("This run is not numbered, so it needs a name of its own."),
            )
        events: list[NewEvent] = []
        if self.name is not None and self.name != run.name:
            events.append(playthrough_name_changed(run.pk, name=self.name))
        if self.note is not None and self.note != run.note:
            events.append(playthrough_note_changed(run.pk, note=self.note))
        if not events:
            return Unchanged("This run already reads that way.")
        return events


@dataclass(frozen=True, slots=True)
class CorrectPlaythroughStart(Command):
    """State a better day or note for a start already stated."""

    command_name: ClassVar[CommandName] = CommandName.PLAYTHROUGH_CORRECT_START
    #: A UUID, because Command fingerprints its fields.
    playthrough_id: uuid.UUID
    #: None clears the day. The act stands; only the date goes.
    when: TemporalValue | None
    note: str

    def __post_init__(self) -> None:
        #: One spelling of no day, so a restatement fingerprints alike.
        object.__setattr__(self, "when", stated_date(self.when))
        #: One spelling of a blank note, for the same reason.
        object.__setattr__(self, "note", self.note.strip())

    def build(self, context: CommandContext) -> Sequence[NewEvent] | Unchanged:
        run = _live_run(context, self.playthrough_id)
        return correct_endpoint(
            run,
            PLAYTHROUGH_START,
            ActStatement(self.when, self.note),
            sentences=_start_sentences(run.pk),
            before_event=partial(
                _refuse_a_start_after_the_completion, run, started=self.when
            ),
        )


@dataclass(frozen=True, slots=True)
class CorrectPlaythroughCompletion(Command):
    """State a better day or note for a completion already stated."""

    command_name: ClassVar[CommandName] = CommandName.PLAYTHROUGH_CORRECT_COMPLETION
    #: A UUID, because Command fingerprints its fields.
    playthrough_id: uuid.UUID
    #: None clears the day. The act stands; only the date goes.
    when: TemporalValue | None
    note: str

    def __post_init__(self) -> None:
        #: One spelling of no day, so a restatement fingerprints alike.
        object.__setattr__(self, "when", stated_date(self.when))
        #: One spelling of a blank note, for the same reason.
        object.__setattr__(self, "note", self.note.strip())

    def build(self, context: CommandContext) -> Sequence[NewEvent] | Unchanged:
        run = _live_run(context, self.playthrough_id)
        return correct_endpoint(
            run,
            PLAYTHROUGH_COMPLETION,
            ActStatement(self.when, self.note),
            sentences=_completion_sentences(run.pk),
            before_event=partial(
                _refuse_a_completion_before_the_start, run, completed=self.when
            ),
        )


@dataclass(frozen=True, slots=True)
class VoidPlaythroughStart(Command):
    """Take back the record that a run began.

    A retraction, not a correction: the day and the note go
    with the record, and the run states no start again.
    """

    command_name: ClassVar[CommandName] = CommandName.PLAYTHROUGH_VOID_START
    #: A UUID, because Command fingerprints its fields.
    playthrough_id: uuid.UUID

    def build(self, context: CommandContext) -> Sequence[NewEvent] | Unchanged:
        return _void_start(library_playthrough(context, self.playthrough_id))


@dataclass(frozen=True, slots=True)
class VoidPlaythroughCompletion(Command):
    """Take back the record that a run finished."""

    command_name: ClassVar[CommandName] = CommandName.PLAYTHROUGH_VOID_COMPLETION
    #: A UUID, because Command fingerprints its fields.
    playthrough_id: uuid.UUID

    def build(self, context: CommandContext) -> Sequence[NewEvent] | Unchanged:
        return _void_completion(library_playthrough(context, self.playthrough_id))


def _void_start(run: Playthrough) -> Sequence[NewEvent] | Unchanged:
    #: The no-op before either mark: a repeat still
    #: succeeds once the game is gone.
    return void_endpoint(
        run,
        PLAYTHROUGH_START,
        sentences=_start_sentences(run.pk),
        before_event=partial(_refuse_under_a_removed_parent, run),
    )


def _void_completion(run: Playthrough) -> Sequence[NewEvent] | Unchanged:
    return void_endpoint(
        run,
        PLAYTHROUGH_COMPLETION,
        sentences=_completion_sentences(run.pk),
        before_event=partial(_refuse_under_a_removed_parent, run),
    )


#: What one run's batch Undo refuses.
RUN_UNDO = UndoSentences(
    not_stated=(
        "That playthrough was not recorded by this batch, so it was left as it is."
    ),
    changed_since=(
        "That playthrough has been recorded again since this batch, so it was "
        "left as it is. Correct it by hand instead."
    ),
)


def _refuse_another_acts_value(
    context: CommandContext,
    run: Playthrough,
    endpoint: Endpoint,
    batch_id: uuid.UUID,
) -> None:
    refuse_unless_this_batch_wrote_it(
        context.library,
        run.pk,
        endpoint.events,
        batch_id=batch_id,
        row_description=f"Playthrough {run.pk} of library {run.library_id}",
        sentences=RUN_UNDO,
    )


@dataclass(frozen=True, slots=True)
class UndoPlaythroughStart(Command):
    """Void a batch's start, still latest."""

    command_name: ClassVar[CommandName] = CommandName.PLAYTHROUGH_UNDO_START
    playthrough_id: uuid.UUID
    #: The batch whose start this takes back.
    batch_id: uuid.UUID

    def build(self, context: CommandContext) -> Sequence[NewEvent] | Unchanged:
        run = library_playthrough(context, self.playthrough_id)
        _refuse_another_acts_value(context, run, PLAYTHROUGH_START, self.batch_id)
        return _void_start(run)


@dataclass(frozen=True, slots=True)
class UndoPlaythroughCompletion(Command):
    """Void a batch's completion, still latest."""

    command_name: ClassVar[CommandName] = CommandName.PLAYTHROUGH_UNDO_COMPLETION
    playthrough_id: uuid.UUID
    #: The batch whose completion this takes back.
    batch_id: uuid.UUID

    def build(self, context: CommandContext) -> Sequence[NewEvent] | Unchanged:
        run = library_playthrough(context, self.playthrough_id)
        _refuse_another_acts_value(context, run, PLAYTHROUGH_COMPLETION, self.batch_id)
        return _void_completion(run)


def _start_sentences(playthrough_id: uuid.UUID) -> EndpointSentences:
    return EndpointSentences(
        already_stated=Rejection(
            f"Playthrough {playthrough_id} already states a start, and a second "
            "one would say the run began twice. CorrectPlaythroughStart states "
            "a better one.",
            "This run already has a start. Correct the one it has instead of "
            "adding another.",
        ),
        nothing_to_correct=Rejection(
            f"Playthrough {playthrough_id} states no start, so there is nothing "
            "to correct. A first statement is StartPlaythrough.",
            "This run has no start to correct. Record that it started first.",
        ),
        same_statement="This run already states that start.",
        same_correction="This correction states the start the run states.",
        nothing_to_void=f"Playthrough {playthrough_id} states no start to take back.",
    )


def _completion_sentences(playthrough_id: uuid.UUID) -> EndpointSentences:
    return EndpointSentences(
        already_stated=Rejection(
            f"Playthrough {playthrough_id} already states a completion, and a "
            "second one would say the run ended twice. "
            "CorrectPlaythroughCompletion states a better one.",
            "This run already has a completion. Correct the one it has instead "
            "of adding another.",
        ),
        nothing_to_correct=Rejection(
            f"Playthrough {playthrough_id} states no completion, so there is "
            "nothing to correct. A first statement is CompletePlaythrough.",
            "This run has no completion to correct. Record that it finished first.",
        ),
        same_statement="This run already states that completion.",
        same_correction="This correction states the completion the run states.",
        nothing_to_void=(
            f"Playthrough {playthrough_id} states no completion to take back."
        ),
    )


def _refuse_a_start_after_the_completion(
    run: Playthrough, *, started: TemporalValue | None
) -> None:
    if certainly_reversed(earlier=started, later=run.completed):
        raise CommandRejected(
            f"Playthrough {run.pk} completed before the start being stated, and "
            "no run ends before it begins.",
            sentence="This run finished before that date. Check the day.",
        )


def _refuse_a_completion_before_the_start(
    run: Playthrough, *, completed: TemporalValue | None
) -> None:
    if certainly_reversed(earlier=run.started, later=completed):
        raise CommandRejected(
            f"Playthrough {run.pk} started after the completion being stated, "
            "and no run ends before it begins.",
            sentence="This run started after that date. Check the day.",
        )


def _refuse_under_a_removed_parent(run: Playthrough) -> None:
    """Game's mark first, then the run's."""
    _refuse_under_a_removed_game(run)
    _refuse_a_removed_run(run)


def _refuse_a_removed_run(run: Playthrough) -> None:
    """Refuse an act on a removed run."""
    #: Under dispatch's lock the mark cannot move.
    if run.removed_at is not None:
        raise CommandRejected(
            f"This library removed playthrough {run.pk}, so it states no "
            "further facts about it.",
            sentence=(
                "That playthrough was removed. Put it back before changing "
                "what it records."
            ),
        )


def _refuse_under_a_removed_game(run: Playthrough) -> None:
    """Refuse an act under a removed game."""
    #: Under dispatch's lock the mark cannot move.
    if run.player_game.removed_at is not None:
        raise CommandRejected(
            f"This library removed the game behind playthrough {run.pk}, "
            "so its runs neither leave the lists nor come back.",
            sentence=(
                "That game was removed from your library. Restore it before "
                "changing its playthroughs."
            ),
        )


def refuse_a_foreign_referrer(run: Playthrough) -> None:
    """Refuse a foreign row naming the run."""
    foreign = foreign_referrer(run)
    if foreign is None:
        return
    library_keys = ", ".join(str(library_id) for library_id in foreign.library_ids)
    raise RowUnreadable(
        f"A live {foreign.referrer.model.__name__}.{foreign.referrer.field_name} "
        f"of libraries {library_keys} names playthrough {run.pk} of library "
        f"{run.library_id}; the ownership audit reports it, and removing the "
        "run would strand it."
    )


def _other_live_ordinary_runs(
    context: CommandContext, run: Playthrough
) -> QuerySet[Playthrough]:
    """This game's other live ordinary runs.

    Scoped on the library explicitly: a run may name another
    library's PlayerGame, the drift `audit_library_ownership`
    reports, so the parent alone counts rows this library does
    not hold.
    """
    return Playthrough.objects.filter(
        library=context.library,
        player_game=run.player_game,
        removed_at__isnull=True,
        kind=PlaythroughKind.ORDINARY,
    ).exclude(pk=run.pk)


@dataclass(frozen=True, slots=True)
class RemovePlaythrough(Command):
    """Take a run out of the lists."""

    command_name: ClassVar[CommandName] = CommandName.PLAYTHROUGH_REMOVE
    #: A UUID, because Command fingerprints its fields.
    playthrough_id: uuid.UUID

    def build(self, context: CommandContext) -> Sequence[NewEvent] | Unchanged:
        run = library_playthrough(context, self.playthrough_id)
        #: The no-op before the game's mark.
        #: A repeat still succeeds once the game is gone.
        if run.removed_at is not None:
            return Unchanged(
                f"This library already removed playthrough {self.playthrough_id}."
            )
        _refuse_under_a_removed_game(run)
        #: Ordinary only. A bucket takes none away.
        #: First: a move leaves a sole run still last.
        if (
            run.kind == PlaythroughKind.ORDINARY
            and not _other_live_ordinary_runs(context, run).exists()
        ):
            raise CommandRejected(
                f"Playthrough {self.playthrough_id} is the last live ordinary "
                f"run of player game {run.player_game_id}, and every tracked "
                "game holds one.",
                sentence=(
                    "This is the only playthrough of that game, and a tracked "
                    "game keeps one. Remove the game itself instead."
                ),
            )
        blocker = blocking_referrer(run)
        if blocker is not None:
            raise CommandRejected(
                f"A live {blocker.model.__name__} names playthrough "
                f"{self.playthrough_id}, so the run stays where it can "
                "be found.",
                sentence=blocker.sentence,
            )
        refuse_a_foreign_referrer(run)
        return [playthrough_removed(run.pk)]


@dataclass(frozen=True, slots=True)
class RestorePlaythrough(Command):
    """Put a removed run back."""

    command_name: ClassVar[CommandName] = CommandName.PLAYTHROUGH_RESTORE
    #: A UUID, because Command fingerprints its fields.
    playthrough_id: uuid.UUID

    def build(self, context: CommandContext) -> Sequence[NewEvent] | Unchanged:
        run = library_playthrough(context, self.playthrough_id)
        #: The no-op first, as in RemovePlaythrough.
        if run.removed_at is None:
            return Unchanged(
                f"This library did not remove playthrough {self.playthrough_id}."
            )
        _refuse_under_a_removed_game(run)
        return [playthrough_restored(run.pk)]


#: The importer's bucket belongs to one game.
BUCKET_STAYS = (
    "That is the imported-history bucket, which stays with its game. Move its "
    "sessions to a playthrough instead."
)
TARGET_REMOVED = (
    "That game was removed from your library. Restore it before moving a "
    "playthrough to it."
)
SHARED_RECORD = (
    "A historical playtime record names this playthrough beside another one "
    "of the same game. Edit that record to take this playthrough off it, then "
    "move it."
)
SHARED_REMOVED_RECORD = (
    "A removed historical playtime record names this playthrough beside "
    "another one of the same game. Restore it and take this playthrough off "
    "it, then move it."
)


class NewlyTracked(NamedTuple):
    """A game this dispatch starts tracking."""

    tracking: NewEvent

    @property
    def player_game_id(self) -> PlayerGameId:
        return self.tracking.aggregate_id

    @property
    def status(self) -> PlayerGameStatus:
        """A newly tracked game holds Unplayed."""
        return PlayerGameStatus.UNPLAYED


type MoveTarget = HeldGame | NewlyTracked


def _move_target(context: CommandContext, game_id: GameId) -> MoveTarget:
    """Library's mark first; a shared game has none."""
    #: Under dispatch's lock: no concurrent duplicate.
    tracked = PlayerGame.objects.filter(
        library=context.library, game_id=game_id
    ).first()
    if tracked is not None:
        if tracked.removed_at is not None:
            raise CommandRejected(
                f"This library removed game {game_id}, so no run moves to it "
                "until it is restored.",
                sentence=TARGET_REMOVED,
            )
        return HeldGame(tracked)
    game = visible_row(
        context,
        Game.objects.alive(),
        Refusal(message=f"No game {game_id} this library can move a run to."),
        pk=game_id,
    )
    return NewlyTracked(tracking_event(game))


class FollowingRecord(NamedTuple):
    """A moving record and its Release flag."""

    record_id: HistoricalPlaytimeId
    names_release: bool


def _records_that_follow(
    context: CommandContext, run: Playthrough
) -> list[FollowingRecord]:
    """Records naming only this run; refuse others."""
    record_ids = set(
        HistoricalPlaytimeRun.objects.filter(
            library=context.library, playthrough=run
        ).values_list("record_id", flat=True)
    )
    shared = (
        HistoricalPlaytimeRun.objects.filter(
            library=context.library, record_id__in=record_ids
        )
        .exclude(playthrough=run)
        .select_related("record")
        .first()
    )
    if shared is not None:
        raise CommandRejected(
            f"Record {shared.record_id} names playthrough {run.pk} beside "
            f"playthrough {shared.playthrough_id}, and a record belongs to "
            "one game.",
            sentence=(
                SHARED_RECORD
                if shared.record.removed_at is None
                else SHARED_REMOVED_RECORD
            ),
        )
    named = set(
        HistoricalPlaytime.objects.filter(
            library=context.library, pk__in=record_ids, release__isnull=False
        ).values_list("pk", flat=True)
    )
    return [
        FollowingRecord(record_id, record_id in named)
        for record_id in sorted(record_ids, key=str)
    ]


def _sessions_naming_a_release(
    context: CommandContext, run: Playthrough
) -> list[PlayerSessionId]:
    """Sessions naming a Release, removed ones too."""
    return list(
        PlayerSession.objects.filter(
            library=context.library, playthrough=run, release__isnull=False
        )
        .order_by("pk")
        .values_list("pk", flat=True)
    )


@dataclass(frozen=True, slots=True)
class MovePlaythroughToGame(Command):
    """State the game a run belongs to."""

    command_name: ClassVar[CommandName] = CommandName.PLAYTHROUGH_MOVE
    #: UUIDs, because Command fingerprints its fields.
    playthrough_id: uuid.UUID
    #: The catalog game, as CreatePlaythrough names it.
    game_id: uuid.UUID

    def build(self, context: CommandContext) -> Sequence[NewEvent] | Unchanged:
        #: Function-local: that module reads this one's registry.
        from games.reads.playthrough_runs import placeholder_run

        run = library_playthrough(context, self.playthrough_id)
        #: The no-op before every refusal.
        if run.player_game.game_id == self.game_id:
            return Unchanged("This playthrough already belongs to that game.")
        refuse_unless_live(run)
        if run.kind != PlaythroughKind.ORDINARY:
            raise CommandRejected(
                f"Playthrough {run.pk} is of kind {run.kind}, which holds one "
                "game's imported sessions.",
                sentence=BUCKET_STAYS,
            )
        target = _move_target(context, self.game_id)
        records = _records_that_follow(context, run)
        events: list[NewEvent] = []
        if isinstance(target, NewlyTracked):
            events.append(target.tracking)
        events.append(playthrough_moved(run.pk, player_game_id=target.player_game_id))
        #: The move clears every Release.
        events.extend(
            playersession_release_changed(session_id, release=None)
            for session_id in _sessions_naming_a_release(context, run)
        )
        events.extend(
            historicalplaytime_moved(
                record.record_id,
                player_game_id=target.player_game_id,
                clears_release=record.names_release,
            )
            for record in records
        )
        if isinstance(target, HeldGame):
            placeholder = placeholder_run(context.library, target.row)
            if placeholder is not None:
                events.append(playthrough_removed(placeholder.pk))
        if not _other_live_ordinary_runs(context, run).exists():
            events.append(playthrough_created(run.player_game_id))
        return with_implied_status(context, events, target, _implied_by(run))


def _implied_by(run: Playthrough) -> ImpliedStatus | None:
    """The status a run's endpoints imply."""
    if stated_completion(run) is not None:
        return PlayerGameStatus.COMPLETED
    if stated_start(run) is not None:
        return PlayerGameStatus.PLAYED
    return None
