"""Commands about the catalog games a library tracks."""

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
    """Begin tracking one catalog game in this library."""

    command_name: ClassVar[CommandName] = CommandName.PLAYERGAME_TRACK
    #: A UUID rather than a Game: a model instance has no canonical form to
    #: fingerprint, so the row is re-read here, scoped to the library.
    game_id: uuid.UUID

    def build(self, context: CommandContext) -> Sequence[NewEvent]:
        game = self._visible_game(context)
        #: Both reads happen under the stream-head lock dispatch already took,
        #: so no concurrent TrackGame can land between them and the append.
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
        """This library's own game, or one from the shared catalog."""
        try:
            return Game.objects.filter(
                Q(library=context.library) | Q(library__isnull=True),
                archived_at__isnull=True,
            ).get(pk=self.game_id)
        except Game.DoesNotExist:
            #: Says nothing about whose it is. A refusal is not a place to
            #: learn what another library holds.
            raise CommandRejected(
                f"No game {self.game_id} this library can track. A library "
                "tracks its own games and the shared catalog, and neither "
                "offers an archived row."
            ) from None
