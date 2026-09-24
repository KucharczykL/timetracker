"""State a fact; answer a refused one.

Takes an actor, not a request.
The view half makes it a toast.
"""

import logging
import uuid
from functools import partial
from typing import Literal, overload

from django.contrib.auth.models import User
from django.db.models import Q

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
from games.removal import remove, restore
from games.writes.answers import CONFLICT_STATUS, CommandFailed, answered

logger = logging.getLogger("games")


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


def untrack_game(
    actor: User,
    game: Game,
    *,
    correlation_id: uuid.UUID,
    idempotency_key: IdempotencyKey | None = None,
    source_metadata: SourceMetadata | None = None,
) -> CommandResult:
    """State that the library stopped tracking it.

    A game the library does not track is refused with a sentence: the
    caller that accepts one says so, in `remove_from_library`.
    """
    with answered("game"):
        return _dispatch(
            RemovePlayerGame(game_id=game.pk),
            actor=actor,
            library=actor.library,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            source_metadata=source_metadata,
        )


def retrack_game(
    actor: User,
    game: Game,
    *,
    correlation_id: uuid.UUID,
    idempotency_key: IdempotencyKey | None = None,
    source_metadata: SourceMetadata | None = None,
) -> CommandResult:
    """State that the library tracks a removed game again.

    A game the library never tracked is tracked now: a restored
    catalog row nothing tracks would sit in no list. Only the per-row
    restore reaches that, because an Undo restores a PlayerGame it
    found.

    The fallback mints its own key. A second command under the
    caller's key is an `IdempotencyKeyMismatch`.
    """
    with answered("game"):
        try:
            return _dispatch(
                RestorePlayerGame(game_id=game.pk),
                actor=actor,
                library=actor.library,
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
                source_metadata=source_metadata,
            )
        except PlayerGameNotTracked:
            return _dispatch(
                TrackGame(game_id=game.pk),
                actor=actor,
                library=actor.library,
                correlation_id=correlation_id,
                source_metadata=source_metadata,
            )


def _owned(actor: User, game: Game) -> bool:
    """The library's own catalog row, never a shared one.

    A shared row is stamped by nobody: `_stamp` recounts every
    purchase of the game and writes its wikidata mirror, across every
    library that holds it.
    """
    return game.library_id is not None and game.library_id == actor.library.pk


@overload
def remove_from_library(
    actor: User,
    game: Game,
    *,
    correlation_id: uuid.UUID,
    idempotency_key: IdempotencyKey | None = None,
    source_metadata: SourceMetadata | None = None,
    stamp_untracked: Literal[False] = False,
) -> CommandResult: ...


@overload
def remove_from_library(
    actor: User,
    game: Game,
    *,
    correlation_id: uuid.UUID,
    idempotency_key: IdempotencyKey | None = None,
    source_metadata: SourceMetadata | None = None,
    stamp_untracked: Literal[True],
) -> CommandResult | None: ...


def remove_from_library(
    actor: User,
    game: Game,
    *,
    correlation_id: uuid.UUID,
    idempotency_key: IdempotencyKey | None = None,
    source_metadata: SourceMetadata | None = None,
    stamp_untracked: bool = False,
) -> CommandResult | None:
    """Untrack the game, then stamp the catalog row the library owns.

    This order, and no transaction around it: dispatch opens its own
    and refuses to nest. A defect between the two leaves an owned game
    untracked and unstamped, on no list; the per-row route completes
    it, and the event is the batch's, so its Undo restores it too. The
    act itself cannot: such a game is off `tracked_by`, so it is off
    the act's scope, and the tally names that remedy instead
    (`_partly_removed` in `games/bulk_removal.py`).

    The stamp writes no event. A game the library does not track is
    refused and stamped nowhere, since a stamp with no event is a row
    no Undo can see. `stamp_untracked` is the per-row route's: it
    stamps such a game, and answers None for the dispatch it skipped.
    """
    try:
        result: CommandResult | None = untrack_game(
            actor,
            game,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            source_metadata=source_metadata,
        )
    except CommandFailed as failure:
        #: `answered` raises from the refusal, so the cause names
        #: which one it was; a sentence is no thing to match on.
        untracked = isinstance(failure.__cause__, PlayerGameNotTracked)
        if not (stamp_untracked and untracked):
            raise
        result = None
    if _owned(actor, game):
        with answered("game"):
            remove(game)
    return result


def _collision(library: UserLibrary, game: Game) -> Game | None:
    """A live game of the library the partial unique constraints refuse.

    One `Q` states both: `platform=None` compiles to IS NULL, which is
    the platformless constraint's own condition. A NULL year is
    distinct from every year, so neither constraint holds it.

    A forecast, not the rule: a game created after this read still
    meets the constraint, and `answered`'s backstop answers that.
    """
    if game.year_released is None:
        return None
    return (
        Game.objects.filter(
            Q(library=library)
            & Q(removed_at__isnull=True)
            & Q(name=game.name)
            & Q(year_released=game.year_released)
            & Q(platform=game.platform_id)
        )
        .exclude(pk=game.pk)
        .select_related("platform")
        .order_by("-created_at")
        .first()
    )


def _collision_sentence(game: Game, newer: Game) -> str:
    platform = f" on {newer.platform.name}" if newer.platform is not None else ""
    return (
        f"{game.name} cannot come back: your library already holds another "
        f"{newer.name}{platform} from {newer.year_released}. Rename or remove "
        "that one first."
    )


def restore_to_library(
    actor: User,
    game: Game,
    *,
    correlation_id: uuid.UUID,
    idempotency_key: IdempotencyKey | None = None,
    source_metadata: SourceMetadata | None = None,
) -> CommandResult:
    """Clear the stamp of a game the library owns, then track it again.

    The removal's order reversed, so a halfway is the removal's own
    halfway. A shared row keeps its stamp untouched: nobody stamps it.

    A game the library recreated since would meet a unique constraint,
    which answers 500 and ends a whole Undo as a defect. So the
    collision is refused first, with 409 and a sentence naming the
    newer game, and nothing changes.
    """
    #: What the stamp did, not what the library owns: a row already
    #: clear -- the removal's own halfway, or the restore route, whose
    #: read states no mark -- had nothing cleared, and a sentence
    #: saying it did would name a change nobody made.
    cleared = _owned(actor, game) and game.removed_at is not None
    if cleared:
        newer = _collision(actor.library, game)
        if newer is not None:
            raise CommandFailed(_collision_sentence(game, newer), CONFLICT_STATUS)
        with answered("game"):
            restore(game)
    try:
        return retrack_game(
            actor,
            game,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            source_metadata=source_metadata,
        )
    except CommandFailed as failure:
        if not cleared:
            raise
        #: The stamp is cleared; the sentence must not say nothing was.
        #: A 409 is contention a second press settles, so it is a
        #: warning; a traceback for one would read as a defect and
        #: report itself as one. Anything else is ours, with its own.
        settles = failure.status_code == CONFLICT_STATUS
        logger.log(
            logging.WARNING if settles else logging.ERROR,
            "[restore]: game %s of library %s is back in the catalog but not "
            "tracked: %s",
            game.pk,
            game.library_id,
            failure.message,
            exc_info=None if settles else failure,
        )
        #: A defect admits no second press.
        tail = "Try again." if settles else "The problem has been reported."
        raise CommandFailed(
            f"{game.name} is back in the catalog but not tracked yet. {tail}",
            failure.status_code,
        ) from failure


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
