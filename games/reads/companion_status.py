"""Which status a lifecycle act may offer."""

from games.models import Game, PlayerGameStatus, UserLibrary
from games.reads.playthrough_runs import tracked_game


def played_is_offered(library: UserLibrary, game: Game) -> bool:
    """True where a start would newly make Played.

    One question, so it takes one game. A form
    with no game yet answers its own question:
    every game is offered until one is picked,
    and clean() decides again on the game the
    submit names.
    """
    tracked = tracked_game(library, game)
    return tracked is None or tracked.status == PlayerGameStatus.UNPLAYED
