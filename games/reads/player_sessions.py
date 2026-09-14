"""The sessions a library counts."""

from games.models import PlayerSession, PlayerSessionQuerySet, UserLibrary


def library_sessions(library: UserLibrary) -> PlayerSessionQuerySet:
    """Every live session this library counts.

    The one scope every session read states. The library is
    stated beside the run's, never inferred: a session may name
    another library's run, which is the drift
    `audit_library_ownership` reports.

    All four marks read here. `alive()` holds three; the catalog
    game's stays out of it so `blocking_referrer` still sees the
    sessions of a removed game. No `kind`: a session in the
    imported-history bucket is still playtime.
    """
    return PlayerSession.objects.filter(
        library=library,
        playthrough__library=library,
        removed_at__isnull=True,
        playthrough__removed_at__isnull=True,
        playthrough__player_game__removed_at__isnull=True,
        playthrough__player_game__game__removed_at__isnull=True,
    )
