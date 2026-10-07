"""Seed a copy whose game states a completion."""

import uuid
from typing import NamedTuple

from entries import record_entry
from graphs import default_graph
from purchases import record_purchase

from games.commands.playthrough import ActStatement, CompletePlaythrough
from games.events.dispatch import dispatch
from games.models import Game, LibraryEntry, Playthrough, Purchase
from games.writes.playthrough import RunDraft, record_run
from timetracker.temporal import TemporalValue

#: A purchase day every helper states.
PURCHASED = TemporalValue.parse("2020-01-01")


class BoughtGame(NamedTuple):
    game: Game
    run: Playthrough
    entry: LibraryEntry
    purchase: Purchase


def bought_game(user, library, name, completed, **purchase) -> BoughtGame:
    """A game, one copy, one purchase, its run.

    `completed` False is a run that reached no completion,
    and None one completed on a day nobody wrote down.
    """
    game = default_graph(Game(library=library, name=name), library)
    entry = record_entry(library, game.release)
    run = Playthrough.objects.get(player_game__game=game.game)
    if completed is not False:
        dispatch(
            CompletePlaythrough(
                playthrough_id=run.pk, when=completed, note="", implies_status=False
            ),
            actor=user,
            library=library,
            idempotency_key=f"done-{name}",
        )
        run.refresh_from_db()
    purchase.setdefault("purchased", PURCHASED)
    return BoughtGame(game.game, run, entry, record_purchase(entry, **purchase))


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
            implies_played=False,
            implies_completed=False,
        ),
        correlation_id=uuid.uuid7(),
    )
