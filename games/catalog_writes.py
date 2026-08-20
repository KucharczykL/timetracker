from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.db import transaction

from games.models import Edition, Game, Platform, Release
from timetracker.temporal import TemporalValue


@dataclass(frozen=True, slots=True)
class PrivateGameGraph:
    game: Game
    edition: Edition
    release: Release


def _validate_platform(game: Game, platform: Platform | None) -> None:
    if game.library_id is None:
        raise ValidationError("A private Game requires a library owner.")
    if platform is not None and platform.library_id not in (None, game.library_id):
        raise ValidationError("Platform belongs to another library.")


@transaction.atomic
def save_private_game(
    *,
    game: Game,
    original_release_date: TemporalValue | None,
    release_date: TemporalValue | None,
    platform: Platform | None,
) -> PrivateGameGraph:
    _validate_platform(game, platform)
    if not game._state.adding:
        Game.objects.select_for_update().get(pk=game.pk)

    game.original_release_date = original_release_date
    game.save()
    edition, _ = Edition.objects.select_for_update().get_or_create(
        game=game,
        is_default=True,
    )
    release, _ = Release.objects.select_for_update().get_or_create(
        edition=edition,
        is_default=True,
    )
    release.platform = platform
    release.release_date = release_date
    release.save(update_fields=("platform", "release_date"))
    return PrivateGameGraph(game=game, edition=edition, release=release)
