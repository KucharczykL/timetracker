"""Commands about the runs a library records."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import ClassVar

from games.commands.playergame import tracked_game
from games.events.dispatch import Command, CommandContext, CommandName, CommandRejected
from games.events.playthrough import playthrough_created
from games.events.vocabulary import NewEvent, Unchanged
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
