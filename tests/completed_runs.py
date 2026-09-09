"""Seed a purchase whose games state completions."""

import uuid
from datetime import UTC, datetime

from games.commands.playergame import TrackGame
from games.commands.playthrough import ActStatement, CompletePlaythrough
from games.events.dispatch import dispatch
from games.models import Game, Playthrough, Purchase
from games.writes.playthrough import RunDraft, record_run


def make_purchase(library, name="Bundle"):
    return Purchase.objects.create(
        library=library,
        name=name,
        date_purchased=datetime(2020, 1, 1, tzinfo=UTC),
        price=0,
        price_currency="USD",
    )


def add_game(user, library, purchase, name, completed):
    """Track a game and state its completion.

    False is a run that reached no completion, and None is one
    completed on a day nobody wrote down.
    """
    game = Game.objects.create(library=library, name=name)
    purchase.games.add(game)
    dispatch(
        TrackGame(game_id=game.pk),
        actor=user,
        library=library,
        idempotency_key=f"track-{name}",
    )
    run = Playthrough.objects.get(player_game__game=game)
    if completed is not False:
        dispatch(
            CompletePlaythrough(playthrough_id=run.pk, when=completed, note=""),
            actor=user,
            library=library,
            idempotency_key=f"done-{name}",
        )
    return game, run


def add_run(user, game, completed):
    """State one more run at a game.

    The game's first run states a completion already, so
    `run_to_adopt` refuses it and this creates a second.
    """
    record_run(
        user,
        game,
        RunDraft(
            started=None,
            completed=None if completed is False else ActStatement(completed),
            note="",
        ),
        correlation_id=uuid.uuid7(),
    )
