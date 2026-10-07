"""Which status a lifecycle act may offer."""

from games.models import Game, PlayerGameStatus, UserLibrary, status_implied_over
from games.reads.playthrough_runs import tracked_game


def played_is_offered(library: UserLibrary, game: Game) -> bool:
    """A render hint; the command decides."""
    tracked = tracked_game(library, game)
    return tracked is None or status_implied_over(
        PlayerGameStatus(tracked.status), PlayerGameStatus.PLAYED
    )
