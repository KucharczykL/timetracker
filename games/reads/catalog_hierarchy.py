"""The Editions and Releases one library sees under one Game."""

from typing import NamedTuple
from uuid import UUID

from django.db.models import F
from django.db.models.functions import Lower

from games.models import Edition, Game, Release, UserLibrary


class EditionEntry(NamedTuple):
    """One Edition and the Releases under it."""

    edition: Edition
    releases: tuple[Release, ...]


def game_hierarchy(game: Game, library: UserLibrary) -> tuple[EditionEntry, ...]:
    """This Game's visible Editions, each with its Releases.

    Two queries, and no reverse accessor: a shared Game's
    accessors reach every library that ever wrote under it.
    `visible_to()` calls `alive()`, thus a removed row and the
    children of one both drop out.
    """
    editions = list(
        Edition.objects.visible_to(library)
        .filter(game=game)
        .select_related("game")
        .order_by("-is_default", Lower("name"), "pk")
    )
    releases = (
        Release.objects.visible_to(library)
        .filter(edition__in=editions)
        .select_related("platform")
        #: The default first, then the earliest day anyone knows.
        .order_by(
            "-is_default",
            F("release_date_lower").asc(nulls_last=True),
            "pk",
        )
    )
    grouped: dict[UUID, list[Release]] = {edition.pk: [] for edition in editions}
    for release in releases:
        grouped[release.edition_id].append(release)
    return tuple(
        EditionEntry(edition, tuple(grouped[edition.pk])) for edition in editions
    )
