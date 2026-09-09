"""Which status a lifecycle act may offer."""

from games.models import Game, PlayerGameStatus, UserLibrary
from games.reads.playthrough_runs import tracked_game


def played_is_offered(library: UserLibrary, game: Game | None) -> bool:
    """True where a start would newly make Played.

    No game is the Add form before one
    is picked; clean() decides again on the
    game the submit names.
    """
    if game is None:
        return True
    tracked = tracked_game(library, game)
    return tracked is None or tracked.status == PlayerGameStatus.UNPLAYED
