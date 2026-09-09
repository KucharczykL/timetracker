"""Which status a lifecycle act may offer."""

from games.models import Game, PlayerGameStatus, UserLibrary
from games.reads.playthrough_runs import tracked_game


def played_is_offered(library: UserLibrary, game: Game | None) -> bool:
    """True where a start would newly make the game Played.

    A game completed once stays completed, so a start
    states nothing about it and the box does not render.
    An untracked game counts: recording a run tracks it,
    and a game tracked by this submit was Unplayed a
    moment ago. No game at all is the generic Add form
    before one is picked, which decides again at clean
    time against the game the submit names.
    """
    if game is None:
        return True
    tracked = tracked_game(library, game)
    return tracked is None or tracked.status == PlayerGameStatus.UNPLAYED
