"""Commands about the runs a library records."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import ClassVar

from games.commands.playergame import tracked_game
from games.events.dispatch import Command, CommandContext, CommandName, CommandRejected
from games.events.playthrough import (
    playthrough_completed,
    playthrough_created,
    playthrough_started,
)
from games.events.vocabulary import NewEvent, Unchanged
from games.models import Playthrough
from timetracker.temporal import TemporalValue


def _states_a_qualifier(value: TemporalValue) -> bool:
    """Whether the value, or either end of a range, is qualified."""
    return value.qualifier is not None or any(
        endpoint is not None and endpoint.qualifier is not None
        for endpoint in (value.start, value.end)
    )


def endpoints_certainly_reversed(
    started: TemporalValue | None, completed: TemporalValue | None
) -> bool:
    """Whether a completion cannot follow its start.

    Only the certainly-impossible. Each guard drops a pair the
    comparison cannot judge, and the last two are why a bare `<` is
    wrong rather than merely incomplete:

    A bound is unknown for two reasons. The endpoint carries no date, or
    it is an open-ended range -- `../2024-06` bounds nothing below and
    `2024-01/..` nothing above -- and a window with no edge contradicts
    nothing.

    A qualifier leaves the bounds where the bare value put them, so
    `2024-05-10~` bounds to that day exactly. Refusing a completion on
    the 9th would refuse what `~` was written to say.
    """
    if started is None or completed is None:
        return False
    if _states_a_qualifier(started) or _states_a_qualifier(completed):
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
    """The run inside this library, or a refusal that names none.

    A row of another library and a row that does not exist answer alike:
    a refusal is not a place to learn an id. The third library-scoped
    resolver, beside `tracked_game` and `TrackGame._visible_game`, and
    the third caller #909 merges.
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


def _endpoint_subject(
    context: CommandContext, playthrough_id: uuid.UUID
) -> Playthrough:
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
    #: No default. The build compares the whole endpoint, so a caller
    #: who omitted this would be refused for changing it.
    note: str

    def build(self, context: CommandContext) -> Sequence[NewEvent] | Unchanged:
        run = _endpoint_subject(context, self.playthrough_id)
        #: The marker, never the date: a null date is also an unknown day.
        if run.start_recorded_at is not None:
            if (self.when, self.note) == (run.started, run.start_note):
                return Unchanged("This run already started on that day.")
            raise CommandRejected(
                f"Playthrough {self.playthrough_id} already states a start, and "
                "a second one would say the run began twice. #1010 corrects a "
                "stated endpoint.",
                sentence=(
                    "This run already has a start. Correct the one it has "
                    "instead of adding another."
                ),
            )
        if endpoints_certainly_reversed(self.when, run.completed):
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

    def build(self, context: CommandContext) -> Sequence[NewEvent] | Unchanged:
        run = _endpoint_subject(context, self.playthrough_id)
        if run.completion_recorded_at is not None:
            if (self.when, self.note) == (run.completed, run.completion_note):
                return Unchanged("This run already completed on that day.")
            raise CommandRejected(
                f"Playthrough {self.playthrough_id} already states a completion, "
                "and a second one would say the run ended twice. #1010 corrects "
                "a stated endpoint.",
                sentence=(
                    "This run already has a completion. Correct the one it has "
                    "instead of adding another."
                ),
            )
        if endpoints_certainly_reversed(run.started, self.when):
            raise CommandRejected(
                f"Playthrough {self.playthrough_id} started after the completion "
                "being stated, and no run ends before it begins.",
                sentence="This run started after that date. Check the day.",
            )
        return [playthrough_completed(run.pk, when=self.when, note=self.note)]
