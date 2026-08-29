"""Commands about the games a library tracks."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import ClassVar, cast

from django.db.models import Q
from django.utils import timezone

from games.events.dispatch import (
    Command,
    CommandContext,
    CommandName,
    CommandRejected,
)
from games.events.playergame import (
    PLAYERGAME_CREATED,
    PLAYERGAME_EXCLUDED_FROM_UNFINISHED_CHANGED,
    PLAYERGAME_MASTERED_CHANGED,
    PLAYERGAME_REMOVED,
    PLAYERGAME_RESTORED,
    PLAYERGAME_STATUS_CHANGED,
    StatusValue,
)
from games.events.references import capture_reference
from games.events.vocabulary import NewEvent, Unchanged
from games.models import Game, PlayerGame, PlayerGameStatus
from timetracker.temporal import TemporalValue


def _stated_now() -> TemporalValue:
    """A live change happens when recorded."""
    return TemporalValue.from_day(timezone.localdate())


class PlayerGameNotTracked(CommandRejected):
    """The library tracks no such game.

    Its own class, because the write path answers this one case by
    tracking the game and stating the fact again. Matching on a
    message is the alternative, and is not one.
    """


def _tracked_game(context: CommandContext, game_id: uuid.UUID) -> PlayerGame:
    """The projection row, never the catalog."""
    try:
        return PlayerGame.objects.get(library=context.library, game_id=game_id)
    except PlayerGame.DoesNotExist:
        raise PlayerGameNotTracked(
            f"This library tracks no game {game_id}. A recorded fact belongs "
            "to a tracked game, and #676 backfills one for every game a "
            "library has.",
            sentence="This game is not tracked yet. Reload the page and try again.",
        ) from None


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
        return [
            PLAYERGAME_CREATED.new(
                aggregate_id=uuid.uuid7(),
                payload={"game": capture_reference(game)},
            )
        ]

    def _visible_game(self, context: CommandContext) -> Game:
        """Its own game, or a shared one."""
        try:
            return Game.objects.filter(
                Q(library=context.library) | Q(library__isnull=True),
                removed_at__isnull=True,
            ).get(pk=self.game_id)
        except Game.DoesNotExist:
            #: Leaks nothing about another library's rows.
            raise CommandRejected(
                f"No game {self.game_id} this library can track. A library "
                "tracks its own games and the shared catalog, and neither "
                "offers a removed row.",
                #: Names no id: a refusal is not a place to learn one.
                sentence="That game is not available to track.",
            ) from None


@dataclass(frozen=True, slots=True)
class SetPlayerGameStatus(Command):
    """Set the status of a tracked game."""

    command_name: ClassVar[CommandName] = CommandName.PLAYERGAME_SET_STATUS
    #: A UUID, because Command fingerprints its fields.
    game_id: uuid.UUID
    #: A TextChoices member is a str.
    status: PlayerGameStatus

    def build(self, context: CommandContext) -> Sequence[NewEvent] | Unchanged:
        tracked = _tracked_game(context, self.game_id)
        #: Under dispatch's lock: no concurrent duplicate.
        if tracked.status == self.status:
            return Unchanged(
                f"This library already gives game {self.game_id} the status "
                f"{self.status.value!r}."
            )
        return [
            PLAYERGAME_STATUS_CHANGED.new(
                aggregate_id=tracked.pk,
                #: A test pins Literal and choices equal.
                payload={"status": cast("StatusValue", self.status.value)},
                effective_time=_stated_now(),
            )
        ]


@dataclass(frozen=True, slots=True)
class SetPlayerGameMastered(Command):
    """State whether this library mastered a tracked game."""

    command_name: ClassVar[CommandName] = CommandName.PLAYERGAME_SET_MASTERED
    #: A UUID, because Command fingerprints its fields.
    game_id: uuid.UUID
    mastered: bool

    def build(self, context: CommandContext) -> Sequence[NewEvent] | Unchanged:
        tracked = _tracked_game(context, self.game_id)
        #: Under dispatch's lock: no concurrent duplicate.
        if tracked.mastered == self.mastered:
            recorded = "mastered" if self.mastered else "not mastered"
            return Unchanged(
                f"This library already records game {self.game_id} as {recorded}."
            )
        return [
            PLAYERGAME_MASTERED_CHANGED.new(
                aggregate_id=tracked.pk,
                payload={"mastered": self.mastered},
            )
        ]


@dataclass(frozen=True, slots=True)
class SetPlayerGameExcludedFromUnfinished(Command):
    """State whether unfinished lists omit a game."""

    command_name: ClassVar[CommandName] = (
        CommandName.PLAYERGAME_SET_EXCLUDED_FROM_UNFINISHED
    )
    #: A UUID, because Command fingerprints its fields.
    game_id: uuid.UUID
    excluded_from_unfinished: bool

    def build(self, context: CommandContext) -> Sequence[NewEvent] | Unchanged:
        tracked = _tracked_game(context, self.game_id)
        #: Under dispatch's lock: no concurrent duplicate.
        if tracked.excluded_from_unfinished == self.excluded_from_unfinished:
            recorded = (
                "excluded from" if self.excluded_from_unfinished else "included in"
            )
            return Unchanged(
                f"This library already records game {self.game_id} as {recorded} "
                "unfinished lists."
            )
        return [
            PLAYERGAME_EXCLUDED_FROM_UNFINISHED_CHANGED.new(
                aggregate_id=tracked.pk,
                payload={"excluded_from_unfinished": self.excluded_from_unfinished},
            )
        ]


@dataclass(frozen=True, slots=True)
class RemovePlayerGame(Command):
    """Take a tracked game out."""

    command_name: ClassVar[CommandName] = CommandName.PLAYERGAME_REMOVE
    #: A UUID, because Command fingerprints its fields.
    game_id: uuid.UUID

    def build(self, context: CommandContext) -> Sequence[NewEvent] | Unchanged:
        tracked = _tracked_game(context, self.game_id)
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
        tracked = _tracked_game(context, self.game_id)
        #: Under dispatch's lock: no concurrent duplicate.
        if tracked.removed_at is None:
            return Unchanged(f"This library did not remove game {self.game_id}.")
        return [PLAYERGAME_RESTORED.new(aggregate_id=tracked.pk, payload={})]


@dataclass(frozen=True, slots=True)
class RecordPlayerGameFacts(Command):
    """State a status, a mastery, or both.

    The game form states both facts at every save, so the two travel as
    one command. build() decides which already holds, under the lock,
    where a form's stale initial cannot reach it.
    """

    command_name: ClassVar[CommandName] = CommandName.PLAYERGAME_RECORD_FACTS
    #: A UUID, because Command fingerprints its fields.
    game_id: uuid.UUID
    #: None states no fact, and it fingerprints.
    status: PlayerGameStatus | None
    mastered: bool | None

    def __post_init__(self) -> None:
        if self.status is None and self.mastered is None:
            raise ValueError(
                "RecordPlayerGameFacts states no fact. A command that asks for "
                "nothing would still claim an idempotency key and write a "
                "record for a request that expressed no intent."
            )

    def build(self, context: CommandContext) -> Sequence[NewEvent] | Unchanged:
        tracked = _tracked_game(context, self.game_id)
        #: Under dispatch's lock: no concurrent duplicate.
        events: list[NewEvent] = []
        if self.status is not None and tracked.status != self.status:
            events.append(
                PLAYERGAME_STATUS_CHANGED.new(
                    aggregate_id=tracked.pk,
                    #: A test pins Literal and choices equal.
                    payload={"status": cast("StatusValue", self.status.value)},
                    effective_time=_stated_now(),
                )
            )
        if self.mastered is not None and tracked.mastered != self.mastered:
            events.append(
                PLAYERGAME_MASTERED_CHANGED.new(
                    aggregate_id=tracked.pk,
                    payload={"mastered": self.mastered},
                )
            )
        if not events:
            return Unchanged(
                f"This library already records the stated facts for game "
                f"{self.game_id}."
            )
        return events
