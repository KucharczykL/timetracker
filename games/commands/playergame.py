"""Commands about the games a library tracks."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import ClassVar, cast

from django.db.models import Q

from games.events.dispatch import (
    Command,
    CommandContext,
    CommandName,
    CommandRejected,
)
from games.events.playergame import (
    PLAYERGAME_CREATED,
    PLAYERGAME_MASTERED_CHANGED,
    PLAYERGAME_STATUS_CHANGED,
    StatusValue,
)
from games.events.references import capture_reference
from games.events.vocabulary import NewEvent
from games.models import Game, PlayerGame, PlayerGameStatus


def _tracked_game(context: CommandContext, game_id: uuid.UUID) -> PlayerGame:
    """The projection row, never the catalog."""
    try:
        return PlayerGame.objects.get(library=context.library, game_id=game_id)
    except PlayerGame.DoesNotExist:
        raise CommandRejected(
            f"This library tracks no game {game_id}. A recorded fact belongs "
            "to a tracked game, and #676 backfills one for every game a "
            "library has."
        ) from None


@dataclass(frozen=True, slots=True)
class TrackGame(Command):
    """Track one catalog game in this library."""

    command_name: ClassVar[CommandName] = CommandName.PLAYERGAME_TRACK
    #: A UUID, because Command fingerprints its fields.
    game_id: uuid.UUID

    def build(self, context: CommandContext) -> Sequence[NewEvent]:
        game = self._visible_game(context)
        #: Under dispatch's lock: no concurrent duplicate.
        if PlayerGame.objects.filter(library=context.library, game=game).exists():
            raise CommandRejected(
                f"This library already tracks {game.name}. Whether a repeat "
                "should instead succeed as a no-op is EV-23 (#906)."
            )
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
                archived_at__isnull=True,
            ).get(pk=self.game_id)
        except Game.DoesNotExist:
            #: Leaks nothing about another library's rows.
            raise CommandRejected(
                f"No game {self.game_id} this library can track. A library "
                "tracks its own games and the shared catalog, and neither "
                "offers an archived row."
            ) from None


@dataclass(frozen=True, slots=True)
class SetPlayerGameStatus(Command):
    """Set the status of a tracked game."""

    command_name: ClassVar[CommandName] = CommandName.PLAYERGAME_SET_STATUS
    #: A UUID, because Command fingerprints its fields.
    game_id: uuid.UUID
    #: A TextChoices member is a str.
    status: PlayerGameStatus

    def build(self, context: CommandContext) -> Sequence[NewEvent]:
        tracked = _tracked_game(context, self.game_id)
        #: Under dispatch's lock: no concurrent duplicate.
        if tracked.status == self.status:
            raise CommandRejected(
                f"This library already gives game {self.game_id} the status "
                f"{self.status.value!r}. Whether a repeat should instead "
                "succeed as a no-op is EV-23 (#906)."
            )
        return [
            PLAYERGAME_STATUS_CHANGED.new(
                aggregate_id=tracked.pk,
                #: A test pins Literal and choices equal.
                payload={"status": cast("StatusValue", self.status.value)},
            )
        ]


@dataclass(frozen=True, slots=True)
class SetPlayerGameMastered(Command):
    """State whether this library mastered a tracked game."""

    command_name: ClassVar[CommandName] = CommandName.PLAYERGAME_SET_MASTERED
    #: A UUID, because Command fingerprints its fields.
    game_id: uuid.UUID
    mastered: bool

    def build(self, context: CommandContext) -> Sequence[NewEvent]:
        tracked = _tracked_game(context, self.game_id)
        #: Under dispatch's lock: no concurrent duplicate.
        if tracked.mastered == self.mastered:
            recorded = "mastered" if self.mastered else "not mastered"
            raise CommandRejected(
                f"This library already records game {self.game_id} as "
                f"{recorded}. Whether a repeat should instead succeed as a "
                "no-op is EV-23 (#906)."
            )
        return [
            PLAYERGAME_MASTERED_CHANGED.new(
                aggregate_id=tracked.pk,
                payload={"mastered": self.mastered},
            )
        ]
