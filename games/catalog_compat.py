from collections.abc import Callable

from django.core.exceptions import ValidationError
from django.db import transaction

from games.models import Game, Platform, Release

#: A flat column pair still holds a unique constraint over the
#: library, thus a Release edit can walk one Game onto another's.
LEGACY_IDENTITY_TAKEN = (
    "Another game in your library already has this name, platform and year."
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
    platform = None if release is None else release.platform
    date = None if release is None else release.release_date
    year = None if date is None else date.year
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
