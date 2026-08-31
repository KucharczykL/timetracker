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
    if not game._state.adding:
        persisted_game = Game.objects.select_for_update().get(pk=game.pk)
        if persisted_game.library_id != game.library_id:
            raise ValidationError("A persisted Game cannot change library owner.")
    _validate_platform(game, platform)

    game.original_release_date = original_release_date
    game.save()
    #: A removed child is not adopted back.
    #:
    #: The lookup reads the row's own mark, which is what the
    #: default-slot constraint is conditional on. Reading `alive()`
    #: would ask about the Game as well, and a second live default
    #: under a removed Game is what the constraint refuses.
    edition, _ = (
        Edition.objects.select_for_update()
        .filter(removed_at__isnull=True)
        .get_or_create(game=game, is_default=True)
    )
    release, _ = (
        Release.objects.select_for_update()
        .filter(removed_at__isnull=True)
        .get_or_create(edition=edition, is_default=True)
    )
    release.platform = platform
    release.release_date = release_date
    release.save(update_fields=("platform", "release_date"))
    return PrivateGameGraph(game=game, edition=edition, release=release)
