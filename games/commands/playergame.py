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
    PLAYERGAME_ARCHIVED,
    PLAYERGAME_CREATED,
    PLAYERGAME_EXCLUDED_FROM_UNFINISHED_CHANGED,
    PLAYERGAME_MASTERED_CHANGED,
    PLAYERGAME_RESTORED,
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
        tracked = PlayerGame.objects.filter(library=context.library, game=game).first()
        if tracked is not None:
            if tracked.archived_at is not None:
                raise CommandRejected(
                    f"This library archives {game.name} rather than tracking it. "
                    "An archived game is restored, not tracked again."
                )
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
                tombstoned_at__isnull=True,
            ).get(pk=self.game_id)
        except Game.DoesNotExist:
            #: Leaks nothing about another library's rows.
            raise CommandRejected(
                f"No game {self.game_id} this library can track. A library "
                "tracks its own games and the shared catalog, and neither "
                "offers a tombstoned row."
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


@dataclass(frozen=True, slots=True)
class SetPlayerGameExcludedFromUnfinished(Command):
    """State whether unfinished lists omit a game."""

    command_name: ClassVar[CommandName] = (
        CommandName.PLAYERGAME_SET_EXCLUDED_FROM_UNFINISHED
    )
    #: A UUID, because Command fingerprints its fields.
    game_id: uuid.UUID
    excluded_from_unfinished: bool

    def build(self, context: CommandContext) -> Sequence[NewEvent]:
        tracked = _tracked_game(context, self.game_id)
        #: Under dispatch's lock: no concurrent duplicate.
        if tracked.excluded_from_unfinished == self.excluded_from_unfinished:
            recorded = (
                "excluded from" if self.excluded_from_unfinished else "included in"
            )
            raise CommandRejected(
                f"This library already records game {self.game_id} as "
                f"{recorded} unfinished lists. Whether a repeat should instead "
                "succeed as a no-op is EV-23 (#906)."
            )
        return [
            PLAYERGAME_EXCLUDED_FROM_UNFINISHED_CHANGED.new(
                aggregate_id=tracked.pk,
                payload={"excluded_from_unfinished": self.excluded_from_unfinished},
            )
        ]


@dataclass(frozen=True, slots=True)
class ArchivePlayerGame(Command):
    """Archive a tracked game."""

    command_name: ClassVar[CommandName] = CommandName.PLAYERGAME_ARCHIVE
    #: A UUID, because Command fingerprints its fields.
    game_id: uuid.UUID

    def build(self, context: CommandContext) -> Sequence[NewEvent]:
        tracked = _tracked_game(context, self.game_id)
        #: Under dispatch's lock: no concurrent duplicate.
        if tracked.archived_at is not None:
            raise CommandRejected(
                f"This library already archives game {self.game_id}. Whether a "
                "repeat should instead succeed as a no-op is EV-23 (#906)."
            )
        return [PLAYERGAME_ARCHIVED.new(aggregate_id=tracked.pk, payload={})]


@dataclass(frozen=True, slots=True)
class RestorePlayerGame(Command):
    """Restore a game this library archived.

    The catalog is not consulted. A delete of a tracked game tombstones the
    catalog row and keeps this one, so an archived game may outlive the row it
    names; refusing would leave the library a game it can neither see nor
    recover.
    """

    command_name: ClassVar[CommandName] = CommandName.PLAYERGAME_RESTORE
    #: A UUID, because Command fingerprints its fields.
    game_id: uuid.UUID

    def build(self, context: CommandContext) -> Sequence[NewEvent]:
        tracked = _tracked_game(context, self.game_id)
        #: Under dispatch's lock: no concurrent duplicate.
        if tracked.archived_at is None:
            raise CommandRejected(
                f"This library does not archive game {self.game_id}. Whether a "
                "repeat should instead succeed as a no-op is EV-23 (#906)."
            )
        return [PLAYERGAME_RESTORED.new(aggregate_id=tracked.pk, payload={})]
