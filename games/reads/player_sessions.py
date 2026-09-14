"""The sessions a library counts."""

from games.models import PlayerSession, PlayerSessionQuerySet, UserLibrary


def library_sessions(library: UserLibrary) -> PlayerSessionQuerySet:
    """Every live session this library counts.

    A copy of `library_runs` breaks this quietly. Its `kind`
    condition drops the sessions of the imported-history bucket.
    `alive()` alone keeps the sessions of a removed catalog game.
    The run's library is stated too: a session can name the run
    of another library.
    """
    return PlayerSession.objects.filter(
        library=library,
        playthrough__library=library,
        removed_at__isnull=True,
        playthrough__removed_at__isnull=True,
        playthrough__player_game__removed_at__isnull=True,
        playthrough__player_game__game__removed_at__isnull=True,
    )
