"""Commands about the games a library tracks."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import ClassVar

from django.db.models import Q

from games.events.dispatch import (
    Command,
    CommandContext,
    CommandName,
    CommandRejected,
)
from games.events.playergame import PLAYERGAME_CREATED
from games.events.references import capture_reference
from games.events.vocabulary import NewEvent
from games.models import Game, PlayerGame


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
