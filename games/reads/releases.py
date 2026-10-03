"""Release reads: catalog, held, played."""

from datetime import datetime
from typing import NamedTuple

from django.db.models import Q, QuerySet

from games.end_ways import EndWay
from games.ids import ReleaseId
from games.models import (
    Edition,
    EditionKind,
    Game,
    Release,
    UserLibrary,
    game_display_order_through,
)
from games.reads.entries import library_entries
from games.reads.historical_playtime_records import library_records
from games.reads.player_sessions import library_sessions
from games.reads.unscoped import require_library

UNSPECIFIED_PLATFORM = "Unspecified"


def platform_words(release: Release) -> str:
    """Its platform's name, else Unspecified."""
    return UNSPECIFIED_PLATFORM if release.platform is None else release.platform.name


def edition_words(edition: Edition) -> str:
    """Its name, else Prerelease, else nothing."""
    if edition.name:
        return edition.name
    if edition.kind == EditionKind.PRERELEASE:
        return EditionKind.PRERELEASE.label
    return ""


def game_releases(library: UserLibrary, game: Game) -> QuerySet[Release]:
    """One Game's live Releases this library sees."""
    library = require_library(library)
    return (
        Release.objects.visible_to(library)
        .filter(edition__game=game)
        .select_related("edition", "platform")
        .order_by("-edition__is_default", "-is_default", "platform__name", "id")
    )


def held_releases(library: UserLibrary) -> QuerySet[Release]:
    """Releases a live copy of this library names."""
    return Release.objects.filter(pk__in=library_entries(library).values("release_id"))


def held_game_releases(library: UserLibrary, game: Game) -> QuerySet[Release]:
    """One Game's Releases a live copy names."""
    return game_releases(library, game).filter(pk__in=held_releases(library))


class LatestEnd(NamedTuple):
    """A copy's end: when recorded, which way."""

    recorded_at: datetime
    way: str


def ended_copy_ways(
    library: UserLibrary, release_ids: list[ReleaseId]
) -> dict[ReleaseId, EndWay]:
    """Latest-recorded end's way, all copies ended."""
    copies = library_entries(library).filter(release_id__in=release_ids)
    latest: dict[ReleaseId, LatestEnd] = {}
    unended: set[ReleaseId] = set()
    for release_id, way, ended_at in copies.values_list(
        "release_id", "access_end_way", "access_end_recorded_at"
    ):
        if ended_at is None:
            unended.add(release_id)
        elif release_id not in latest or ended_at > latest[release_id].recorded_at:
            latest[release_id] = LatestEnd(ended_at, way)
    return {
        release_id: EndWay(end.way)
        for release_id, end in latest.items()
        if release_id not in unended
    }


def played_releases(library: UserLibrary, query: str = "") -> QuerySet[Release]:
    """Releases a live session or record names."""
    named = Q(pk__in=library_sessions(library).values("release_id")) | Q(
        pk__in=library_records(library).values("release_id")
    )
    text = query.strip()
    matching = (
        Q(platform__name__icontains=text)
        | Q(edition__name__icontains=text)
        | Q(edition__game__name__icontains=text)
        if text
        else Q()
    )
    return (
        Release.objects.filter(named, matching)
        .select_related("edition__game", "platform")
        .order_by(
            *game_display_order_through("edition__game"),
            "-edition__is_default",
            "-is_default",
            "platform__name",
            "id",
        )
    )


def matching_releases(releases: QuerySet[Release], query: str) -> QuerySet[Release]:
    """Releases whose platform or edition match."""
    text = query.strip()
    if not text:
        return releases
    return releases.filter(
        Q(platform__name__icontains=text) | Q(edition__name__icontains=text)
    )


def played_release_label(release: Release) -> str:
    """The game's name, then the Release."""
    return f"{release.edition.game.name} · {release_label(release)}"


def release_label(release: Release) -> str:
    """Platform, edition words, then year."""
    parts = [platform_words(release)]
    if words := edition_words(release.edition):
        parts.append(words)
    if release.release_date is not None and release.release_date.year is not None:
        parts.append(str(release.release_date.year))
    return " · ".join(parts)
