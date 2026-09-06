"""Commands about the runs a library records."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import ClassVar, cast

from games.commands.playergame import tracked_game
from games.events.dispatch import Command, CommandContext, CommandName, CommandRejected
from games.events.playthrough import (
    playthrough_completed,
    playthrough_completion_corrected,
    playthrough_created,
    playthrough_name_changed,
    playthrough_note_changed,
    playthrough_start_corrected,
    playthrough_started,
)
from games.events.vocabulary import NewEvent, Unchanged
from games.models import Playthrough, PlaythroughKind
from games.reads.playthrough_endpoints import stated_completion, stated_start
from timetracker.temporal import TemporalQualifier, TemporalValue, stated_date

#: Read off the column, so the refusal and the constraint cannot drift.
PLAYTHROUGH_NAME_MAX_LENGTH: int = cast(
    int, Playthrough._meta.get_field("name").max_length
)


def _bounding_qualifier(
    value: TemporalValue, *, at_start: bool
) -> TemporalQualifier | None:
    """The qualifier on the end the comparison reads.

    A range states no qualifier of its own; each endpoint states one.
    Only the end that produced the bound in hand can excuse it, so the
    far end is not consulted -- it says nothing about that day.
    """
    if not value.is_range:
        return value.qualifier
    endpoint = value.start if at_start else value.end
    return None if endpoint is None else endpoint.qualifier


def endpoints_certainly_reversed(
    *, started: TemporalValue | None, completed: TemporalValue | None
) -> bool:
    """Whether a completion cannot follow its start.

    Keyword-only, because the two arguments share a type and the order
    is the whole meaning: a swap is silent on every pair but the one
    this exists to catch.

    Only the certainly-impossible. A bound is unknown for two reasons:
    no date at all, or a range whose end is open or unknown --
    `../2024-06` and `2024-01/` both bound nothing below and above
    respectively -- and a window with no edge contradicts nothing.

    A qualifier leaves the bounds where the bare value put them, so
    `2024-05-10~` bounds to that day exactly. Refusing a completion on
    the 9th would refuse what `~` was written to say.
    """
    if started is None or completed is None:
        return False
    if _bounding_qualifier(started, at_start=True) is not None:
        return False
    if _bounding_qualifier(completed, at_start=False) is not None:
        return False
    if started.lower_bound is None or completed.upper_bound is None:
        return False
    return completed.upper_bound < started.lower_bound


@dataclass(frozen=True, slots=True)
class CreatePlaythrough(Command):
    """State one more run at a game."""

    command_name: ClassVar[CommandName] = CommandName.PLAYTHROUGH_CREATE
    #: A UUID, because Command fingerprints its fields.
    game_id: uuid.UUID

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
        return [playthrough_created(tracked.pk)]


def library_playthrough(
    context: CommandContext, playthrough_id: uuid.UUID
) -> Playthrough:
    """The run inside this library, or a refusal naming none.

    A row of another library and a row that does not exist answer
    alike: a refusal is not a place to learn an id. The third
    library-scoped resolver, and the third caller #909 merges.
    """
    try:
        return Playthrough.objects.select_related("player_game").get(
            library=context.library, pk=playthrough_id
        )
    except Playthrough.DoesNotExist:
        raise CommandRejected(
            f"This library holds no playthrough {playthrough_id}. A stated "
            "endpoint belongs to a run the library records.",
            sentence="That playthrough is not available.",
        ) from None


def _live_run(context: CommandContext, playthrough_id: uuid.UUID) -> Playthrough:
    """The run, refused if nothing may be stated about it."""
    run = library_playthrough(context, playthrough_id)
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

    def __post_init__(self) -> None:
        #: One spelling of no day, so a restatement fingerprints alike.
        object.__setattr__(self, "when", stated_date(self.when))

    def build(self, context: CommandContext) -> Sequence[NewEvent] | Unchanged:
        run = _live_run(context, self.playthrough_id)
        stated = stated_start(run)
        if stated is not None:
            if (self.when, self.note) == (stated.when, stated.note):
                return Unchanged("This run already states that start.")
            raise CommandRejected(
                f"Playthrough {self.playthrough_id} already states a start, and "
                "a second one would say the run began twice. "
                "CorrectPlaythroughStart states a better one.",
                sentence=(
                    "This run already has a start. Correct the one it has "
                    "instead of adding another."
                ),
            )
        if endpoints_certainly_reversed(started=self.when, completed=run.completed):
            raise CommandRejected(
                f"Playthrough {self.playthrough_id} completed before the start "
                "being stated, and no run ends before it begins.",
                sentence="This run finished before that date. Check the day.",
            )
        return [playthrough_started(run.pk, when=self.when, note=self.note)]


@dataclass(frozen=True, slots=True)
class CompletePlaythrough(Command):
    """State that a run met its main objective."""

    command_name: ClassVar[CommandName] = CommandName.PLAYTHROUGH_COMPLETE
    #: A UUID, because Command fingerprints its fields.
    playthrough_id: uuid.UUID
    when: TemporalValue | None
    note: str

    def __post_init__(self) -> None:
        #: One spelling of no day, so a restatement fingerprints alike.
        object.__setattr__(self, "when", stated_date(self.when))

    def build(self, context: CommandContext) -> Sequence[NewEvent] | Unchanged:
        run = _live_run(context, self.playthrough_id)
        stated = stated_completion(run)
        if stated is not None:
            if (self.when, self.note) == (stated.when, stated.note):
                return Unchanged("This run already states that completion.")
            raise CommandRejected(
                f"Playthrough {self.playthrough_id} already states a completion, "
                "and a second one would say the run ended twice. "
                "CorrectPlaythroughCompletion states a better one.",
                sentence=(
                    "This run already has a completion. Correct the one it has "
                    "instead of adding another."
                ),
            )
        if endpoints_certainly_reversed(started=run.started, completed=self.when):
            raise CommandRejected(
                f"Playthrough {self.playthrough_id} started after the completion "
                "being stated, and no run ends before it begins.",
                sentence="This run started after that date. Check the day.",
            )
        return [playthrough_completed(run.pk, when=self.when, note=self.note)]


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
        #: A name of three spaces is a cleared name.
        for field_name in ("name", "note"):
            stated = getattr(self, field_name)
            if stated is not None:
                object.__setattr__(self, field_name, stated.strip())

    def build(self, context: CommandContext) -> Sequence[NewEvent] | Unchanged:
        run = _live_run(context, self.playthrough_id)
        #: Both refusals read the command, so the row excuses neither.
        if self.name is not None and len(self.name) > PLAYTHROUGH_NAME_MAX_LENGTH:
            raise CommandRejected(
                f"The stated name is {len(self.name)} characters, and the "
                f"column holds {PLAYTHROUGH_NAME_MAX_LENGTH}.",
                sentence=(
                    "That name is too long. Keep it under "
                    f"{PLAYTHROUGH_NAME_MAX_LENGTH} characters."
                ),
            )
        if self.name == "" and run.kind != PlaythroughKind.ORDINARY:
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
    when: TemporalValue | None
    note: str

    def __post_init__(self) -> None:
        #: One spelling of no day, so a restatement fingerprints alike.
        object.__setattr__(self, "when", stated_date(self.when))

    def build(self, context: CommandContext) -> Sequence[NewEvent] | Unchanged:
        run = _live_run(context, self.playthrough_id)
        stated = stated_start(run)
        #: Ahead of the comparison: a run that never began holds the
        #: very values a "played before" correction states.
        if stated is None:
            raise CommandRejected(
                f"Playthrough {self.playthrough_id} states no start, so there is "
                "nothing to correct. A first statement is StartPlaythrough.",
                sentence=(
                    "This run has no start to correct. Record that it started first."
                ),
            )
        if (self.when, self.note) == (stated.when, stated.note):
            return Unchanged("This run already states that start.")
        if endpoints_certainly_reversed(started=self.when, completed=run.completed):
            raise CommandRejected(
                f"Playthrough {self.playthrough_id} completed before the start "
                "being stated, and no run ends before it begins.",
                sentence="This run finished before that date. Check the day.",
            )
        return [playthrough_start_corrected(run.pk, when=self.when, note=self.note)]


@dataclass(frozen=True, slots=True)
class CorrectPlaythroughCompletion(Command):
    """State a better day or note for a completion already stated."""

    command_name: ClassVar[CommandName] = CommandName.PLAYTHROUGH_CORRECT_COMPLETION
    #: A UUID, because Command fingerprints its fields.
    playthrough_id: uuid.UUID
    when: TemporalValue | None
    note: str

    def __post_init__(self) -> None:
        #: One spelling of no day, so a restatement fingerprints alike.
        object.__setattr__(self, "when", stated_date(self.when))

    def build(self, context: CommandContext) -> Sequence[NewEvent] | Unchanged:
        run = _live_run(context, self.playthrough_id)
        stated = stated_completion(run)
        if stated is None:
            raise CommandRejected(
                f"Playthrough {self.playthrough_id} states no completion, so "
                "there is nothing to correct. A first statement is "
                "CompletePlaythrough.",
                sentence=(
                    "This run has no completion to correct. Record that it "
                    "finished first."
                ),
            )
        if (self.when, self.note) == (stated.when, stated.note):
            return Unchanged("This run already states that completion.")
        if endpoints_certainly_reversed(started=run.started, completed=self.when):
            raise CommandRejected(
                f"Playthrough {self.playthrough_id} started after the completion "
                "being stated, and no run ends before it begins.",
                sentence="This run started after that date. Check the day.",
            )
        return [
            playthrough_completion_corrected(run.pk, when=self.when, note=self.note)
        ]
