"""One Game's default catalog graph."""

from typing import NamedTuple

from games.catalog_writes import EditionState, ReleaseState, state_catalog_graph
from games.models import Edition, EditionKind, Game, Platform, Release, UserLibrary
from timetracker.temporal import TemporalValue


class DefaultGraph(NamedTuple):
    """One Game and the single default graph a test starts from."""

    game: Game
    edition: Edition
    release: Release


def default_graph(
    game: Game,
    library: UserLibrary,
    *,
    platform: Platform | None = None,
    release_date: TemporalValue | None = None,
    edition_kind: EditionKind | None = None,
) -> DefaultGraph:
    """Save the game; state its default graph."""
    game.save()
    written = state_catalog_graph(
        game=game,
        library=library,
        editions=[
            EditionState(
                key="edition-0",
                kind=edition_kind,
                is_default=True,
                releases=(
                    ReleaseState(
                        key="edition-0-release-0",
                        platform=platform,
                        release_date=release_date,
                        is_default=True,
                    ),
                ),
            )
        ],
    )
    entry = written.editions[0]
    return DefaultGraph(written.game, entry.edition, entry.releases[0].release)
