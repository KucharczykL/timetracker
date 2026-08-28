"""State a PlayerGame fact as a command, then mirror the fold onto the catalog.

Issue #677. A projector folding these events into Game.status would be one
write path rather than two, and cannot be built: only_shadow_writes() refuses
every statement a rebuild makes against a live table. So the mirror is a dual
write at the call site, and it copies the projection rather than what the
caller asked for -- a mirror that reads the fold cannot disagree with it, and
#906 made a declined request an ordinary outcome.

This module takes an actor rather than a request, because authorize() checks
library.user_id == actor.pk and the actor therefore already names the library.
games/views/playergame_writes.py is the half that knows about requests and
toasts. #678 deletes both.
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
    LegacyStatus,
    legacy_status_for,
    player_status_for,
)


class PlayerGameWriteFailed(Exception):
    """A fact the player stated could not be recorded.

    It carries the status code as well as the sentence, because the two
    conflict leaves disagree about what to do next and the API answers with
    the number while a page answers with the words.
    """

    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def new_correlation_id() -> uuid.UUID:
    """One per request.

    A refund dispatches once per game of the purchase and a heal dispatches
    three times. Without a shared id the stream records each as its own act.
    """
    return uuid.uuid7()


@contextmanager
def _translated() -> Iterator[None]:
    """Turn every command failure into something a view can answer with."""
    try:
        yield
    except CommandNotPermitted as error:
        #: The charter: another library's object is absent, not forbidden.
        raise Http404("No such game.") from error
    except RetryBudgetExhausted as error:
        raise PlayerGameWriteFailed(
            "Another change reached this game first. Nothing was recorded; try again.",
            409,
        ) from error
    except IdempotencyKeyMismatch as error:
        #: Unreachable while every key is minted per request. Handled anyway,
        #: so a future keyed caller meets a 409 rather than a 500.
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
        #: Per request, thus it deduplicates nothing; #906's state comparison
        #: is what absorbs a repeat. See the design's key section.
        idempotency_key=str(uuid.uuid7()),
        correlation_id=correlation_id,
    )


def track_game(actor: User, game: Game, *, correlation_id: uuid.UUID) -> None:
    """Track one catalog game in the actor's library."""
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
    status: LegacyStatus | None = None,
    mastered: bool | None = None,
    correlation_id: uuid.UUID,
) -> None:
    """State one fact or two, then mirror the fold onto the catalog.

    status is a letter of Game.Status, because every caller holds one. A None
    means this act does not state that fact.
    """
    library = actor.library
    command = RecordPlayerGameFacts(
        game_id=game.pk,
        status=None if status is None else player_status_for(status),
        mastered=mastered,
    )
    with _translated():
        try:
            _dispatch(
                command, actor=actor, library=library, correlation_id=correlation_id
            )
        except PlayerGameNotTracked:
            #: #676 backfilled a row for every game a library held and
            #: add_game tracks each new one, so this means the two fell out of
            #: step: a TrackGame that did not commit, a restored dump, a game
            #: the sample loader made. Creating the catalog row and tracking it
            #: are two commits, because run_in_transaction refuses a nested
            #: transaction, so the gap is reachable.
            #: One retry, never a loop: a second rejection is a real one.
            track_game(actor, game, correlation_id=correlation_id)
            _dispatch(
                command, actor=actor, library=library, correlation_id=correlation_id
            )
    _mirror(game, library)


def _mirror(game: Game, library: UserLibrary) -> None:
    """Copy the folded row onto the catalog columns #678 has not moved yet."""
    row = PlayerGame.objects.get(library=library, game=game)
    status = legacy_status_for(PlayerGameStatus(row.status))
    #: Reread first: the caller's instance predates the command, so comparing
    #: against it would call the catalog correct on the strength of a stale
    #: copy and skip the repair.
    game.refresh_from_db(fields=["status", "mastered"])
    if (game.status, game.mastered) == (status, row.mastered):
        return
    game.status = status
    game.mastered = row.mastered
    #: A full field save, so the pre_save audit signal fires and legacy
    #: GameStatusChange history continues exactly as today.
    game.save(update_fields=["status", "mastered"])
