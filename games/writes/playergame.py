"""State a fact, then mirror the row.

only_shadow_writes() refuses a live-table write, so the mirror cannot be a
projector and is a dual write here. Takes an actor, not a request;
games/views/playergame_writes.py is the request half. #678 deletes both.
"""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager

from django.contrib.auth.models import User
from django.http import Http404

from games.commands.playergame import (
    PlayerGameNotTracked,
    RecordPlayerGameFacts,
    TrackGame,
)
from games.events.dispatch import (
    Command,
    CommandNotPermitted,
    CommandRejected,
    dispatch,
)
from games.events.idempotency import IdempotencyKeyMismatch
from games.events.retry import RetryBudgetExhausted
from games.models import Game, PlayerGame, PlayerGameStatus, UserLibrary
from games.playergame_status import (
    PLAYER_STATUS_TO_LEGACY_STATUS,
    legacy_status_for,
)


class PlayerGameWriteFailed(Exception):
    """A stated fact could not be recorded.

    It carries a status code as well as a sentence, because the two
    conflict leaves disagree about what to do next.
    """

    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def new_correlation_id() -> uuid.UUID:
    """One per request, however many dispatches."""
    return uuid.uuid7()


@contextmanager
def _translated() -> Iterator[None]:
    """Turn a command failure into an answer."""
    try:
        yield
    except CommandNotPermitted as error:
        #: Another library's object is absent, not forbidden.
        raise Http404("No such game.") from error
    except RetryBudgetExhausted as error:
        raise PlayerGameWriteFailed(
            "Another change reached this game first. Nothing was recorded; try again.",
            409,
        ) from error
    except IdempotencyKeyMismatch as error:
        #: Unreachable per-request. Handled for a keyed caller.
        raise PlayerGameWriteFailed(
            "This request cannot be retried, because its key already belongs "
            "to a different one.",
            409,
        ) from error
    except CommandRejected as error:
        raise PlayerGameWriteFailed(str(error), 409) from error


def _dispatch(
    command: Command,
    *,
    actor: User,
    library: UserLibrary,
    correlation_id: uuid.UUID,
) -> None:
    dispatch(
        command,
        actor=actor,
        library=library,
        #: Deduplicates nothing; build()'s comparison absorbs a repeat.
        idempotency_key=str(uuid.uuid7()),
        correlation_id=correlation_id,
    )


def track_game(actor: User, game: Game, *, correlation_id: uuid.UUID) -> None:
    """Track one catalog game for the actor."""
    with _translated():
        _dispatch(
            TrackGame(game_id=game.pk),
            actor=actor,
            library=actor.library,
            correlation_id=correlation_id,
        )


def record_facts(
    actor: User,
    game: Game,
    *,
    status: PlayerGameStatus | None = None,
    mastered: bool | None = None,
    correlation_id: uuid.UUID,
) -> None:
    """State one fact or two, then mirror.

    None means this act does not state that fact.
    """
    if status is not None:
        #: A form field and a Ninja schema each hand over the word as
        #: a plain str. The command reads `.value`, so the member is
        #: what crosses this boundary.
        status = PlayerGameStatus(status)
        if status not in PLAYER_STATUS_TO_LEGACY_STATUS:
            #: Refused before dispatch, not after: _mirror() raising on
            #: the way out would leave a committed event whose word the
            #: catalog cannot hold.
            raise PlayerGameWriteFailed(
                f"{status.label} cannot be recorded yet. The catalog columns "
                "still mirror the projection and no catalog status states "
                "this one; #678 D removes the mirror and the restriction "
                "with it.",
                409,
            )
    library = actor.library
    command = RecordPlayerGameFacts(
        game_id=game.pk,
        status=status,
        mastered=mastered,
    )
    with _translated():
        try:
            _dispatch(
                command, actor=actor, library=library, correlation_id=correlation_id
            )
        except PlayerGameNotTracked:
            #: One retry, never a loop. Creating a game and tracking it
            #: are two commits, since run_in_transaction refuses to nest.
            #: A restored dump reaches here too.
            track_game(actor, game, correlation_id=correlation_id)
            _dispatch(
                command, actor=actor, library=library, correlation_id=correlation_id
            )
    _mirror(game, library)


def _mirror(game: Game, library: UserLibrary) -> None:
    """Copy the projection row onto the catalog."""
    row = PlayerGame.objects.get(library=library, game=game)
    status = legacy_status_for(PlayerGameStatus(row.status))
    #: Reread first: a stale instance skips the repair.
    game.refresh_from_db(fields=["status", "mastered"])
    if (game.status, game.mastered) == (status, row.mastered):
        return
    game.status = status
    game.mastered = row.mastered
    #: A field save, so the audit signal still fires.
    game.save(update_fields=["status", "mastered"])
