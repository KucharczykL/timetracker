from collections.abc import Callable
from typing import TYPE_CHECKING, NamedTuple

from django.core.exceptions import ValidationError
from django.db import transaction

from games.catalog_writes import save_private_game
from games.external_references import sync_game_wikidata
from games.models import Game, Platform, Release
from timetracker.temporal import TemporalValue

if TYPE_CHECKING:
    from games.forms import GameForm

#: A flat column pair still holds a unique constraint over the
#: library, thus a Release edit can walk one Game onto another's.
LEGACY_IDENTITY_TAKEN = (
    "Another game in your library already has this name, platform and year."
)


class InitialRelease(NamedTuple):
    """The one Release the Add Game form states inline."""

    platform: Platform | None
    release_date: TemporalValue | None


def _default_release(game: Game) -> Release | None:
    """The Release the flat columns shadow."""
    return Release.objects.filter(
        edition__game_id=game.pk,
        edition__is_default=True,
        edition__removed_at__isnull=True,
        is_default=True,
        removed_at__isnull=True,
    ).first()


def mirror_legacy_columns(game: Game) -> None:
    """The flat Game columns follow the graph that now owns them.

    Nothing renders a Game from these any more, but filters, the API
    and the fixture still read them. #889 takes them, and this with
    them.
    """
    release = _default_release(game)
    platform_id = None if release is None else release.platform_id
    date = None if release is None else release.release_date
    year = None if date is None else date.year
    original = game.original_release_date
    collides = (
        Game.objects.filter(
            library_id=game.library_id,
            name=game.name,
            platform_id=platform_id,
            year_released=year,
            removed_at__isnull=True,
        )
        .exclude(pk=game.pk)
        .exists()
    )
    if collides:
        raise ValidationError(LEGACY_IDENTITY_TAKEN)
    Game.objects.filter(pk=game.pk).update(
        platform_id=platform_id,
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


class _LegacyYear(NamedTuple):
    """What the legacy save writes, and what it keeps."""

    value: TemporalValue | None
    year: int | None


class _StoredDates(NamedTuple):
    """What the rows held before the form wrote them."""

    original_release_date: TemporalValue | None
    original_year_released: int | None
    release_date: TemporalValue | None
    year_released: int | None


def _stored_dates(game: Game) -> _StoredDates:
    """Read the persisted pair, before the form's save.

    The default Release is read by each row's own mark, which is
    what `save_private_game()` writes it under.
    """
    persisted = None if game._state.adding else Game.objects.filter(pk=game.pk).first()
    if persisted is None:
        return _StoredDates(None, None, None, None)
    release = Release.objects.filter(
        edition__game_id=persisted.pk,
        edition__is_default=True,
        edition__removed_at__isnull=True,
        is_default=True,
        removed_at__isnull=True,
    ).first()
    return _StoredDates(
        original_release_date=persisted.original_release_date,
        original_year_released=persisted.original_year_released,
        release_date=None if release is None else release.release_date,
        year_released=persisted.year_released,
    )


def _reconcile_year(
    *,
    stored: TemporalValue | None,
    persisted_year: int | None,
    posted_year: int | None,
) -> _LegacyYear:
    """The form owns a bare year, and nothing richer.

    A stored value the persisted year already states is the form's
    to rewrite. Anything else stays, and the year follows it. A
    decade and a range state no year, thus theirs stands as it is:
    the form owns neither the value nor the column beside it.
    """
    if stored is not None and not (
        persisted_year is not None and stored == TemporalValue.from_year(persisted_year)
    ):
        kept = stored.year if stored.has_known_year else persisted_year
        return _LegacyYear(value=stored, year=kept)
    posted = None if posted_year is None else TemporalValue.from_year(posted_year)
    return _LegacyYear(value=posted, year=posted_year)


#: No dispatch here: run_in_transaction refuses to nest.
@transaction.atomic
def save_legacy_game_form(form: GameForm) -> Game:
    game = form.save(commit=False)
    stored = _stored_dates(game)
    original = _reconcile_year(
        stored=stored.original_release_date,
        persisted_year=stored.original_year_released,
        posted_year=game.original_year_released,
    )
    released = _reconcile_year(
        stored=stored.release_date,
        persisted_year=stored.year_released,
        posted_year=game.year_released,
    )
    game.original_year_released = original.year
    game.year_released = released.year
    graph = save_private_game(
        game=game,
        original_release_date=original.value,
        release_date=released.value,
        platform=game.platform,
    )
    sync_game_wikidata(game=graph.game)
    return graph.game
