"""The Editions and Releases under one Game."""

from typing import NamedTuple
from uuid import UUID

from django.db.models.functions import Coalesce, Lower

from games.models import Edition, Game, Release, UserLibrary


class EditionEntry(NamedTuple):
    """One Edition and the Releases under it."""

    edition: Edition
    releases: tuple[Release, ...]


def game_hierarchy(game: Game, library: UserLibrary) -> tuple[EditionEntry, ...]:
    """This Game's visible Editions, each with Releases.

    No reverse accessor: a shared Game's accessors reach every
    library that ever wrote under it.
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
        #: Default first, then the earliest known day.
        .order_by(
            "-is_default",
            #: An open start knows no lower bound, but is dated.
            Coalesce("release_date_lower", "release_date_upper").asc(nulls_last=True),
            "pk",
        )
    )
    grouped: dict[UUID, list[Release]] = {edition.pk: [] for edition in editions}
    for release in releases:
        grouped[release.edition_id].append(release)
    return tuple(
        EditionEntry(edition, tuple(grouped[edition.pk])) for edition in editions
    )
