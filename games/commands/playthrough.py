"""Commands about the runs a library records."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, ClassVar, NamedTuple, Protocol, cast

from django.db import models
from django.db.models import QuerySet

from games.commands.playergame import tracked_game
from games.commands.scope import Refusal, library_row
from games.events.dispatch import Command, CommandContext, CommandName, CommandRejected
from games.events.playthrough import (
    playthrough_completed,
    playthrough_completion_corrected,
    playthrough_created,
    playthrough_name_changed,
    playthrough_note_changed,
    playthrough_removed,
    playthrough_restored,
    playthrough_start_corrected,
    playthrough_started,
)
from games.events.vocabulary import NewEvent, Unchanged
from games.models import Playthrough, PlaythroughKind, ProjectionModel
from games.projections import FieldName
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


class ActStatement(NamedTuple):
    """An act, and what was said.

    A NamedTuple, so the idempotency fingerprint encodes it
    as an array and the TemporalValue inside reaches the
    encoder that knows it.
    """

    #: None is a day nobody wrote down.
    when: TemporalValue | None
    note: str = ""


@dataclass(frozen=True, slots=True)
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
        if endpoints_certainly_reversed(
            started=None if self.started is None else self.started.when,
            completed=None if self.completed is None else self.completed.when,
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
        return events


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
            sentence="That playthrough is not available.",
        ),
        pk=playthrough_id,
    )


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
        #: One spelling of a blank note, for the same reason.
        object.__setattr__(self, "note", self.note.strip())

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
        #: One spelling of a blank note, for the same reason.
        object.__setattr__(self, "note", self.note.strip())

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
        #: Three spaces is a cleared value, for either fact.
        if self.name is not None:
            object.__setattr__(self, "name", self.name.strip())
        if self.note is not None:
            object.__setattr__(self, "note", self.note.strip())

    def build(self, context: CommandContext) -> Sequence[NewEvent] | Unchanged:
        run = _live_run(context, self.playthrough_id)
        #: In build, not __post_init__: a refusal carries a sentence.
        if self.name is not None and len(self.name) > PLAYTHROUGH_NAME_MAX_LENGTH:
            raise CommandRejected(
                f"The stated name is {len(self.name)} characters, and the "
                f"column holds {PLAYTHROUGH_NAME_MAX_LENGTH}.",
                sentence=(
                    "That name is too long. Keep it to "
                    f"{PLAYTHROUGH_NAME_MAX_LENGTH} characters or fewer."
                ),
            )
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
            return Unchanged("This correction states the start the run states.")
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
            return Unchanged("This correction states the completion the run states.")
        if endpoints_certainly_reversed(started=run.started, completed=self.when):
            raise CommandRejected(
                f"Playthrough {self.playthrough_id} started after the completion "
                "being stated, and no run ends before it begins.",
                sentence="This run started after that date. Check the day.",
            )
        return [
            playthrough_completion_corrected(run.pk, when=self.when, note=self.note)
        ]


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


class RemovableReads(Protocol):
    """A manager whose reads skip a removed row."""

    def alive(self) -> QuerySet[Any]: ...


def _skips_removed_rows(model: type[ProjectionModel]) -> bool:
    """Whether the model's manager states `alive()`."""
    return hasattr(model._default_manager, "alive")


class BlockingReferrer(NamedTuple):
    """One registered way to name a run."""

    #: A projection, which #701 makes Session one of.
    model: type[ProjectionModel]
    #: Field name alias from games/projections.py.
    field_name: FieldName
    #: What a person is shown.
    sentence: str

    @classmethod
    def on(
        cls, model: type[ProjectionModel], field_name: FieldName, *, sentence: str
    ) -> BlockingReferrer:
        """The one construction path; refuses an entry the query cannot run.

        A malformed entry would raise a FieldError inside build(),
        which answers every removal with a 500. Refusing it here
        states it at import.
        """
        field = model._meta.get_field(field_name)
        if not isinstance(field, models.ForeignKey):
            raise TypeError(f"{model.__name__}.{field_name} is not a foreign key.")
        if field.related_model is not Playthrough:
            raise TypeError(
                f"{model.__name__}.{field_name} names "
                f"{field.related_model.__name__}, not a playthrough."
            )
        if not _skips_removed_rows(model):
            raise TypeError(
                f"{model.__name__} states no alive(), so a removed row of it "
                "would keep a run in place forever."
            )
        return cls(model, field_name, sentence)


#: Empty until #700 and #701 land.
BLOCKING_REFERRERS: tuple[BlockingReferrer, ...] = ()


def blocking_referrer(run: Playthrough) -> BlockingReferrer | None:
    """The first registered entry a live row answers.

    Scoped on the library, as `_other_live_ordinary_runs` is: a
    row of another library naming this run is the drift
    `audit_library_ownership` reports, and a person cannot act on
    advice about rows their library does not hold. `model` is a
    projection, so the column is always there, and `on()` states
    the manager's `alive()`, which reads a parent's mark too.
    """
    for referrer in BLOCKING_REFERRERS:
        #: `on()` refuses a manager without it. The annotation on
        #: `_default_manager` names the base, which cannot say so.
        reads = cast(RemovableReads, referrer.model._default_manager)
        named = reads.alive().filter(**{referrer.field_name: run}, library=run.library)
        if named.exists():
            return referrer
    return None


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
        #: #906: a repeat still succeeds once the game is gone.
        if run.removed_at is not None:
            return Unchanged(
                f"This library already removed playthrough {self.playthrough_id}."
            )
        _refuse_under_a_removed_game(run)
        blocker = blocking_referrer(run)
        if blocker is not None:
            raise CommandRejected(
                f"A live {blocker.model.__name__} names playthrough "
                f"{self.playthrough_id}, so the run stays where it can "
                "be found.",
                sentence=blocker.sentence,
            )
        #: Ordinary only. A bucket takes none away.
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
