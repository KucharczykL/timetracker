"""A Release on one Platform, made from the name a person typed.

The Release picker's create row states a platform name and a
Game. The graph is stated through `state_catalog_graph`, so the
Game form's rules refuse here too.
"""

from typing import NamedTuple

from django.core.exceptions import ValidationError
from django.db.models.functions import Lower, Trim
from django.http import Http404

from games.api_creation import RowRefused
from games.catalog_compat import write_and_mirror
from games.catalog_writes import EditionState, ReleaseState, state_catalog_graph
from games.models import Edition, Game, Platform, Release, UserLibrary

SHARED_GAME_RELEASE = "Record this game as your own game to add a release to it."


class PlatformRelease(NamedTuple):
    """The Release the name resolved to."""

    release: Release
    created: bool


def _no_platform(name: str) -> str:
    return f"No platform is named “{name}”. Add it on the Platforms page first."


def _platform_owner(platform: Platform) -> str:
    owner = "shared" if platform.library_id is None else "yours"
    return f"{platform.name} ({owner}, {platform.group or 'no group'})"


def _several_platforms(name: str, platforms: list[Platform]) -> str:
    named = "; ".join(_platform_owner(platform) for platform in platforms)
    return f"Several platforms are named “{name}”: {named}. Pick the release there."


def _platform_named(library: UserLibrary, name: str) -> Platform:
    """The one visible live Platform the text names, case ignored."""
    matches = list(
        Platform.objects.visible_to(library)
        .annotate(key=Lower(Trim("name")))
        .filter(key=name.lower())
        .order_by("library_id", "group", "id")
    )
    if not matches:
        raise RowRefused(_no_platform(name))
    if len(matches) > 1:
        raise RowRefused(_several_platforms(name, matches))
    return matches[0]


def _default_edition(game: Game) -> Edition | None:
    """The default Edition, else the lone one."""
    editions = list(Edition.objects.filter(game=game).alive().order_by("-is_default"))
    if not editions:
        return None
    if editions[0].is_default or len(editions) == 1:
        return editions[0]
    return None


def release_on_platform(
    library: UserLibrary, game_id: object, platform_name: str
) -> PlatformRelease:
    """The live Release on that Platform, stated if none stands."""
    game = Game.objects.visible_to(library).filter(pk=game_id).first()
    if game is None:
        raise Http404("No such game.")
    if game.library_id is None:
        raise RowRefused(SHARED_GAME_RELEASE)
    name = platform_name.strip()
    platform = _platform_named(library, name)
    edition = _default_edition(game)
    if edition is not None:
        standing = (
            Release.objects.filter(edition=edition, platform=platform)
            .alive()
            .order_by("-is_default", "id")
            .first()
        )
        if standing is not None:
            return PlatformRelease(standing, created=False)
    statement = EditionState(
        key="edition",
        edition=edition,
        name="" if edition is None else edition.name,
        is_default=edition is None,
        releases=(ReleaseState(key="release", platform=platform),),
    )
    try:
        written = write_and_mirror(
            game,
            lambda: state_catalog_graph(
                game=game, library=library, editions=[statement]
            ),
        )
    except ValidationError as error:
        raise RowRefused(" ".join(error.messages)) from error
    release = written.editions[0].releases[0].release
    return PlatformRelease(
        Release.objects.select_related("edition", "platform").get(pk=release.pk),
        created=True,
    )
