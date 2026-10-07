"""Commands about the games a library tracks."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import ClassVar, cast

from games.commands.scope import Refusal, library_row, visible_row
from games.events.dispatch import (
    Command,
    CommandContext,
    CommandName,
    CommandRejected,
)
from games.events.playergame import (
    PLAYERGAME_CREATED,
    PLAYERGAME_EXCLUDED_FROM_DROPPED_CHANGED,
    PLAYERGAME_EXCLUDED_FROM_UNFINISHED_CHANGED,
    PLAYERGAME_MASTERED_CHANGED,
    PLAYERGAME_REMOVED,
    PLAYERGAME_RESTORED,
    PLAYERGAME_STATUS_CHANGED,
    StatusValue,
)
from games.events.playthrough import playthrough_created
from games.events.references import capture_reference
from games.events.vocabulary import NewEvent, Unchanged
from games.models import Game, PlayerGame, PlayerGameStatus, status_implied_over
from games.reads.calendar import calendar_today
from timetracker.temporal import TemporalValue


def _stated_now(context: CommandContext) -> TemporalValue:
    """A change happens on the library's calendar."""
    return TemporalValue.from_day(calendar_today(context.library))


def _status_change(
    context: CommandContext, player_game_id: uuid.UUID, status: PlayerGameStatus
) -> NewEvent:
    return PLAYERGAME_STATUS_CHANGED.new(
        aggregate_id=player_game_id,
        #: A test pins Literal and choices equal.
        payload={"status": cast("StatusValue", status.value)},
        effective_time=_stated_now(context),
    )


def implied_status_change(
    context: CommandContext,
    player_game_id: uuid.UUID,
    held: str,
    implied: PlayerGameStatus,
) -> NewEvent | None:
    """The status an act implies, if stated."""
    if not status_implied_over(PlayerGameStatus(held), implied):
        return None
    return _status_change(context, player_game_id, implied)


class PlayerGameNotTracked(CommandRejected):
    """The library tracks no such game.

    Its own class, because the write path answers this one case by
    tracking the game and stating the fact again. Matching on a
    message is the alternative, and is not one.
    """


def tracked_game(context: CommandContext, game_id: uuid.UUID) -> PlayerGame:
    """The projection row, never the catalog."""
    return library_row(
        context,
        PlayerGame.objects.all(),
        Refusal(
            message=(
                f"This library tracks no game {game_id}. A recorded fact belongs "
                "to a tracked game, and #676 backfills one for every game a "
                "library has."
            ),
            #: A refusal, not an absence: see the class.
            sentence="This game is not tracked yet. Reload the page and try again.",
            raises=PlayerGameNotTracked,
        ),
        game_id=game_id,
    )


def tracking_event(game: Game) -> NewEvent:
    """The row alone; caller supplies the run."""
    return PLAYERGAME_CREATED.new(
        aggregate_id=uuid.uuid7(),
        payload={"game": capture_reference(game)},
    )


def tracking_events(game: Game) -> list[NewEvent]:
    """The pair that tracks a game: row, then run.

    One function rather than two alike, because the benchmark seeds this
    pair directly and a seed that drifted from the command would measure
    a stream no command can produce.
    """
    tracking = tracking_event(game)
    #: The first act states the default run.
    return [tracking, playthrough_created(tracking.aggregate_id)]


@dataclass(frozen=True, slots=True)
class TrackGame(Command):
    """Track one catalog game in this library."""

    command_name: ClassVar[CommandName] = CommandName.PLAYERGAME_TRACK
    #: A UUID, because Command fingerprints its fields.
    game_id: uuid.UUID

    def build(self, context: CommandContext) -> Sequence[NewEvent] | Unchanged:
        game = self._visible_game(context)
        #: Under dispatch's lock: no concurrent duplicate.
        tracked = PlayerGame.objects.filter(library=context.library, game=game).first()
        if tracked is not None:
            if tracked.removed_at is not None:
                raise CommandRejected(
                    f"This library removed {game.name} rather than tracking it. "
                    "A removed game is restored, not tracked again.",
                    sentence=(
                        f"This library removed {game.name}. Restore it instead "
                        "of tracking it again."
                    ),
                )
            return Unchanged(f"This library already tracks {game.name}.")
        return tracking_events(game)

    def _visible_game(self, context: CommandContext) -> Game:
        """Its own game, or a shared one."""
        return visible_row(
            context,
            Game.objects.alive(),
            #: Older than the absent rule; keeps its sentence.
            Refusal(
                message=(
                    f"No game {self.game_id} this library can track. A library "
                    "tracks its own games and the shared catalog, and neither "
                    "offers a removed row."
                ),
                #: Names no id: a refusal is not a place to learn one.
                sentence="That game is not available to track.",
                raises=CommandRejected,
            ),
            pk=self.game_id,
        )


@dataclass(frozen=True, slots=True)
class RemovePlayerGame(Command):
    """Take a tracked game out."""

    command_name: ClassVar[CommandName] = CommandName.PLAYERGAME_REMOVE
    #: A UUID, because Command fingerprints its fields.
    game_id: uuid.UUID

    def build(self, context: CommandContext) -> Sequence[NewEvent] | Unchanged:
        tracked = tracked_game(context, self.game_id)
        #: Under dispatch's lock: no concurrent duplicate.
        if tracked.removed_at is not None:
            return Unchanged(f"This library already removed game {self.game_id}.")
        return [PLAYERGAME_REMOVED.new(aggregate_id=tracked.pk, payload={})]


@dataclass(frozen=True, slots=True)
class RestorePlayerGame(Command):
    """Restore a game this library removed.

    The catalog is not consulted. Removing a tracked game stamps the catalog
    row and keeps this one, so a removed game may outlive the row it names;
    refusing would leave the library a game it can neither see nor recover.
    """

    command_name: ClassVar[CommandName] = CommandName.PLAYERGAME_RESTORE
    #: A UUID, because Command fingerprints its fields.
    game_id: uuid.UUID

    def build(self, context: CommandContext) -> Sequence[NewEvent] | Unchanged:
        tracked = tracked_game(context, self.game_id)
        #: Under dispatch's lock: no concurrent duplicate.
        if tracked.removed_at is None:
            return Unchanged(f"This library did not remove game {self.game_id}.")
        return [PLAYERGAME_RESTORED.new(aggregate_id=tracked.pk, payload={})]


@dataclass(frozen=True, slots=True, kw_only=True)
class RecordPlayerGameFacts(Command):
    """State status, mastery, an exclusion, or several.

    build() skips a held fact, under the lock.
    """

    command_name: ClassVar[CommandName] = CommandName.PLAYERGAME_RECORD_FACTS
    #: A UUID, because Command fingerprints its fields.
    game_id: uuid.UUID
    #: None states no fact, and it fingerprints.
    status: PlayerGameStatus | None = None
    mastered: bool | None = None
    excluded_from_unfinished: bool | None = None
    excluded_from_dropped: bool | None = None
    #: Stated only where the rule says so.
    implied_status: PlayerGameStatus | None = None

    def __post_init__(self) -> None:
        if self.status is not None and self.implied_status is not None:
            raise ValueError(
                "RecordPlayerGameFacts states a status and an implied one. "
                "The stated one always wins, so the implied one says nothing."
            )
        if (
            self.status is None
            and self.mastered is None
            and self.excluded_from_unfinished is None
            and self.excluded_from_dropped is None
            and self.implied_status is None
        ):
            raise ValueError(
                "RecordPlayerGameFacts states no fact. A command that asks for "
                "nothing would still claim an idempotency key and write a "
                "record for a request that expressed no intent."
            )

    def build(self, context: CommandContext) -> Sequence[NewEvent] | Unchanged:
        tracked = tracked_game(context, self.game_id)
        #: Under dispatch's lock: no concurrent duplicate.
        events: list[NewEvent] = []
        if self.status is not None and tracked.status != self.status:
            events.append(_status_change(context, tracked.pk, self.status))
        #: A removed game takes no implied status.
        if self.implied_status is not None and tracked.removed_at is None:
            implied = implied_status_change(
                context, tracked.pk, tracked.status, self.implied_status
            )
            if implied is not None:
                events.append(implied)
        if self.mastered is not None and tracked.mastered != self.mastered:
            events.append(
                PLAYERGAME_MASTERED_CHANGED.new(
                    aggregate_id=tracked.pk,
                    payload={"mastered": self.mastered},
                )
            )
        if (
            self.excluded_from_unfinished is not None
            and tracked.excluded_from_unfinished != self.excluded_from_unfinished
        ):
            events.append(
                PLAYERGAME_EXCLUDED_FROM_UNFINISHED_CHANGED.new(
                    aggregate_id=tracked.pk,
                    payload={"excluded_from_unfinished": self.excluded_from_unfinished},
                )
            )
        if (
            self.excluded_from_dropped is not None
            and tracked.excluded_from_dropped != self.excluded_from_dropped
        ):
            events.append(
                PLAYERGAME_EXCLUDED_FROM_DROPPED_CHANGED.new(
                    aggregate_id=tracked.pk,
                    payload={"excluded_from_dropped": self.excluded_from_dropped},
                )
            )
        if not events:
            return Unchanged(
                f"This library already records the stated facts for game "
                f"{self.game_id}."
            )
        return events
