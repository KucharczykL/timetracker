"""Write a private Game's Editions and Releases.

Each verb is one transaction, and each refuses a write it must not
make. Nothing here destroys a row: a removal is a stamp.
"""

from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import QuerySet

from games.models import Edition, Game, Platform, Release, UserLibrary
from timetracker.temporal import TemporalValue

#: The words an Edition presents under.
type EditionName = str

SHARED_GAME = "This is a shared game, and a shared game is read-only."
FOREIGN_GAME = "This game belongs to another library."
REMOVED_GAME = "This game is removed. Put it back before you change it."
REMOVED_EDITION = "This edition is removed. Put it back before you change it."
REMOVED_RELEASE = "This release is removed. Put it back before you change it."
FOREIGN_PLATFORM = "Platform belongs to another library."
DUPLICATE_EDITION_NAME = "Another edition of this game already has that name."
LAST_EDITION = "A game keeps one edition. Add another one before you remove this."
DEFAULT_EDITION_HELD = (
    "This is the default edition. Make another one the default first."
)
DEFAULT_RELEASE_HELD = (
    "This is the default release. Make another one the default first."
)
DEMOTED_EDITION = "A game keeps one default edition. Make another one the default."
DEMOTED_RELEASE = "An edition keeps one default release. Make another one the default."


@dataclass(frozen=True, slots=True)
class PrivateGameGraph:
    game: Game
    edition: Edition
    release: Release


def _refuse_foreign_platform(library_id, platform: Platform | None) -> None:
    """A Platform is shared, or it is this library's."""
    if platform is not None and platform.library_id not in (None, library_id):
        raise ValidationError(FOREIGN_PLATFORM)


def _validate_platform(game: Game, platform: Platform | None) -> None:
    if game.library_id is None:
        raise ValidationError("A private Game requires a library owner.")
    _refuse_foreign_platform(game.library_id, platform)


def _writable_game(game_id, library: UserLibrary) -> Game:
    """The Game this library may write, locked for the transaction."""
    game = Game.objects.select_for_update().get(pk=game_id)
    if game.library_id is None:
        raise ValidationError(SHARED_GAME)
    if game.library_id != library.pk:
        raise ValidationError(FOREIGN_GAME)
    if game.removed_at is not None:
        raise ValidationError(REMOVED_GAME)
    return game


def _live_editions(game_id) -> QuerySet[Edition]:
    """One Game's Editions, by their own mark.

    The row's own mark, not `alive()`: it is what the constraints
    here are conditional on, and the Game is already known live.
    """
    return Edition.objects.filter(game_id=game_id, removed_at__isnull=True)


def _clear_default_edition(game_id) -> None:
    """The old default steps down before the new one stands."""
    _live_editions(game_id).filter(is_default=True).update(is_default=False)


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


@transaction.atomic
def add_edition(
    *,
    game: Game,
    library: UserLibrary,
    name: EditionName = "",
    is_default: bool = False,
) -> Edition:
    """Add one Edition to a private Game.

    The same name twice gives back the Edition already there, thus
    a repeated write leaves one row.
    """
    owner = _writable_game(game.pk, library)
    wanted = name.strip()
    standing = _live_editions(owner.pk).filter(name__iexact=wanted).first()
    becomes_default = (
        is_default or not _live_editions(owner.pk).filter(is_default=True).exists()
    )
    if standing is not None:
        if becomes_default and not standing.is_default:
            _clear_default_edition(owner.pk)
            standing.is_default = True
            standing.save(update_fields=("is_default",))
        return standing
    if becomes_default:
        _clear_default_edition(owner.pk)
    return Edition.objects.create(game=owner, name=wanted, is_default=becomes_default)
