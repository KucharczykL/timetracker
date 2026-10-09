"""A Release made from a typed platform.

Stated through `state_catalog_graph`, so the Game form's rules refuse
here too.
"""

from typing import NamedTuple

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models.functions import Lower, Trim
from django.http import Http404

from games.api_creation import RowRefused
from games.catalog_compat import write_and_mirror
from games.catalog_writes import EditionState, ReleaseState, state_catalog_graph
from games.events.dispatch import RowNotHeld
from games.models import Edition, Game, Platform, Release, UserLibrary
from games.writes.answers import absent_as_404

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
    """The one Platform the text names."""
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


NO_DEFAULT_EDITION = (
    "This game has several editions and none is the default. "
    "Pick one on the Edit game page first."
)


def _default_edition(game: Game) -> Edition | None:
    """The default Edition, else the lone one."""
    editions = list(Edition.objects.filter(game=game).alive().order_by("-is_default"))
    if not editions:
        return None
    if editions[0].is_default or len(editions) == 1:
        return editions[0]
    raise RowRefused(NO_DEFAULT_EDITION)


def _standing(edition: Edition | None, platform: Platform) -> Release | None:
    if edition is None:
        return None
    return (
        Release.objects.filter(edition=edition, platform=platform)
        .alive()
        .order_by("-is_default", "id")
        .first()
    )


def release_on_platform(
    library: UserLibrary, game_id: object, platform_name: str
) -> PlatformRelease:
    """That Platform's live Release, stated if absent."""
    game = Game.objects.visible_to(library).filter(pk=game_id).first()
    if game is None:
        raise Http404("No such game.")
    if game.library_id is None:
        raise RowRefused(SHARED_GAME_RELEASE)
    return release_on(library, game, _platform_named(library, platform_name.strip()))


def _landing_refusal(game: Game) -> str | None:
    """Why no new Release can land."""
    return SHARED_GAME_RELEASE if game.library_id is None else None


def platform_refusal(game: Game, platform: Platform) -> str | None:
    """Why a new copy's Release can't land."""
    try:
        edition = _default_edition(game)
    except RowRefused as refusal:
        return refusal.sentence
    if _standing(edition, platform) is not None:
        return None
    return _landing_refusal(game)


def standing_release_on(game: Game, platform: Platform) -> Release | None:
    """Default Edition's live Release on that platform."""
    return _standing(_default_edition(game), platform)


def release_on(library: UserLibrary, game: Game, platform: Platform) -> PlatformRelease:
    """That platform's live Release, stated if absent."""
    if game.library_id is None:
        raise RowRefused(SHARED_GAME_RELEASE)

    def state() -> PlatformRelease:
        #: Concurrent creates make one Release.
        if Game.objects.select_for_update().filter(pk=game.pk).first() is None:
            raise RowNotHeld(
                f"Game {game.pk} is gone before library {library.pk}'s lock."
            )
        edition = _default_edition(game)
        standing = _standing(edition, platform)
        if standing is not None:
            return PlatformRelease(standing, created=False)
        statement = EditionState(
            key="edition",
            edition=edition,
            name="" if edition is None else edition.name,
            is_default=edition is None,
            releases=(ReleaseState(key="release", platform=platform),),
        )
        written = state_catalog_graph(game=game, library=library, editions=[statement])
        return PlatformRelease(written.editions[0].releases[0].release, created=True)

    with absent_as_404("game"):
        try:
            with transaction.atomic():
                reached = write_and_mirror(game, state)
        except ValidationError as error:
            raise RowRefused(" ".join(error.messages)) from error
        release = (
            Release.objects.select_related("edition", "platform")
            .filter(pk=reached.release.pk)
            .first()
        )
        #: A Release goes only with its Game.
        if release is None:
            raise RowNotHeld(
                f"Release {reached.release.pk} of Game {game.pk} is gone; "
                f"library {library.pk} stated it."
            )
    return PlatformRelease(release, created=reached.created)
