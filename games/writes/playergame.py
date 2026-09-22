"""State a fact; answer a refused one.

Takes an actor, not a request.
The view half makes it a toast.
"""

import uuid
from functools import partial

from django.contrib.auth.models import User

from games.commands.playergame import (
    PlayerGameNotTracked,
    RecordPlayerGameFacts,
    RemovePlayerGame,
    RestorePlayerGame,
    TrackGame,
)
from games.events.append import SourceMetadata
from games.events.dispatch import Command, CommandResult, dispatch
from games.events.idempotency import IdempotencyKey
from games.models import Game, PlayerGameStatus, UserLibrary
from games.writes.answers import answered


def new_correlation_id() -> uuid.UUID:
    """One per request, however many dispatches."""
    return uuid.uuid7()


def _dispatch(
    command: Command,
    *,
    actor: User,
    library: UserLibrary,
    correlation_id: uuid.UUID,
    idempotency_key: IdempotencyKey | None = None,
    source_metadata: SourceMetadata | None = None,
) -> CommandResult:
    return dispatch(
        command,
        actor=actor,
        library=library,
        #: A caller's key, else one per dispatch, which deduplicates
        #: nothing: build()'s comparison absorbs a repeat. A batch states
        #: its own, so a chunk posted twice writes once.
        #:
        #: Not `or`: a blank key is falsy, so it would be minted over.
        idempotency_key=(
            str(uuid.uuid7()) if idempotency_key is None else idempotency_key
        ),
        correlation_id=correlation_id,
        source_metadata=source_metadata,
    )


def track_game(actor: User, game: Game, *, correlation_id: uuid.UUID) -> None:
    """Track one catalog game for the actor."""
    with answered("game"):
        _dispatch(
            TrackGame(game_id=game.pk),
            actor=actor,
            library=actor.library,
            correlation_id=correlation_id,
        )


def untrack_game(actor: User, game: Game, *, correlation_id: uuid.UUID) -> None:
    """State that the library stopped tracking it."""
    with answered("game"):
        try:
            _dispatch(
                RemovePlayerGame(game_id=game.pk),
                actor=actor,
                library=actor.library,
                correlation_id=correlation_id,
            )
        except PlayerGameNotTracked:
            #: Untracked: the catalog stamp is the act.
            pass


def retrack_game(actor: User, game: Game, *, correlation_id: uuid.UUID) -> None:
    """State that the library tracks a removed game again.

    A game the library never tracked is tracked now: a restored
    catalog row nothing tracks would sit in no list.
    """
    with answered("game"):
        try:
            _dispatch(
                RestorePlayerGame(game_id=game.pk),
                actor=actor,
                library=actor.library,
                correlation_id=correlation_id,
            )
        except PlayerGameNotTracked:
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
    idempotency_key: IdempotencyKey | None = None,
    source_metadata: SourceMetadata | None = None,
) -> CommandResult:
    """State one fact or two.

    None leaves that fact unstated.
    """
    if status is not None:
        #: A form field and a Ninja schema each hand over the word as
        #: a plain str. The command reads `.value`, so the member is
        #: what crosses this boundary.
        status = PlayerGameStatus(status)
    library = actor.library
    command = RecordPlayerGameFacts(
        game_id=game.pk,
        status=status,
        mastered=mastered,
    )
    state = partial(
        _dispatch,
        command,
        actor=actor,
        library=library,
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
        source_metadata=source_metadata,
    )
    with answered("game"):
        try:
            return state()
        except PlayerGameNotTracked:
            #: One retry, never a loop. Creating a game and tracking it
            #: are two commits, since run_in_transaction refuses to nest.
            #: A restored dump reaches here too.
            track_game(actor, game, correlation_id=correlation_id)
            return state()
