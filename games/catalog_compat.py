from collections.abc import Callable
from typing import NamedTuple

from django.core.exceptions import ValidationError
from django.db import transaction

from games.models import Game, Platform, Release
from timetracker.temporal import TemporalValue

#: A flat column pair still holds a unique constraint over the
#: library, thus a Release edit can walk one Game onto another's.
LEGACY_IDENTITY_TAKEN = (
    "Another game in your library already has this name, platform and year."
)


class MirroredIdentity(NamedTuple):
    """The two flat columns the marked Release shadows.

    The Game's own unique constraint reads them beside its name,
    thus one submit writes all three at once.
    """

    platform: Platform | None
    year_released: int | None


def mirrored_identity(
    platform: Platform | None, release_date: TemporalValue | None
) -> MirroredIdentity:
    """What the flat columns read for one marked Release.

    Storage states it after the write and the form states it
    before, thus both say the same thing.
    """
    return MirroredIdentity(
        platform, None if release_date is None else release_date.year
    )


def _default_release(game: Game) -> Release | None:
    """The Release the flat columns shadow."""
    return (
        Release.objects.select_related("platform")
        .filter(
            edition__game_id=game.pk,
            edition__is_default=True,
            edition__removed_at__isnull=True,
            is_default=True,
            removed_at__isnull=True,
        )
        .first()
    )


def _collides(game: Game, platform: Platform | None, year: int | None) -> bool:
    """Another live Game of this library already reads the same."""
    return (
        Game.objects.filter(
            library_id=game.library_id,
            name=game.name,
            platform=platform,
            year_released=year,
            removed_at__isnull=True,
        )
        .exclude(pk=game.pk)
        .exists()
    )


def mirror_legacy_columns(game: Game) -> None:
    """The flat Game columns follow the graph that now owns them.

    Nothing renders a Game from these any more, but filters, the API
    and the fixture still read them. #889 takes them, and this with
    them.
    """
    release = _default_release(game)
    platform, year = mirrored_identity(
        None if release is None else release.platform,
        None if release is None else release.release_date,
    )
    original = game.original_release_date
    if _collides(game, platform, year):
        raise ValidationError(LEGACY_IDENTITY_TAKEN)
    Game.objects.filter(pk=game.pk).update(
        platform=platform,
        year_released=year,
        original_year_released=None if original is None else original.year,
    )
    game.refresh_from_db(fields=("platform", "year_released", "original_year_released"))


@transaction.atomic
def write_and_mirror[T](game: Game, write: Callable[[], T]) -> T:
    """One write to the graph, then the columns that shadow it."""
    result = write()
    mirror_legacy_columns(game)
    return result
