"""What a fixed game already holds, read once for Log a game."""

from games.log_forms import HeldFacts
from games.models import Game, PlayerGameStatus, Release, UserLibrary
from games.reads.entries import access_summaries
from games.reads.playthrough_runs import sole_ordinary_run, tracked_game
from games.reads.playtime import game_playtime
from games.reads.releases import edition_words, platform_words


def held_facts(library: UserLibrary, game: Game) -> HeldFacts:
    """The copies had now, the sole run, the playtime, the mastery."""
    summary = access_summaries(library, [game.pk]).get(game.pk)
    copies = () if summary is None else summary.held
    tracked = tracked_game(library, game)
    return HeldFacts(
        copies=tuple(_release_words(entry.release) for entry in copies),
        run=sole_ordinary_run(library, game),
        status=None if tracked is None else PlayerGameStatus(tracked.status),
        mastered=tracked is not None and tracked.mastered,
        playtime=game_playtime(library, game).total,
    )


def _release_words(release: Release) -> str:
    parts = [platform_words(release)]
    if words := edition_words(release.edition):
        parts.append(words)
    return " · ".join(parts)
