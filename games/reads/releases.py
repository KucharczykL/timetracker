"""The Releases a copy may name."""

from django.db.models import Q, QuerySet

from games.models import Game, Release, UserLibrary
from games.reads.unscoped import require_library

UNSPECIFIED_PLATFORM = "Unspecified"


def platform_words(release: Release) -> str:
    """Its platform's name, else Unspecified."""
    return UNSPECIFIED_PLATFORM if release.platform is None else release.platform.name


def game_releases(library: UserLibrary, game: Game) -> QuerySet[Release]:
    """One Game's live Releases this library sees."""
    library = require_library(library)
    return (
        Release.objects.visible_to(library)
        .filter(edition__game=game)
        .select_related("edition", "platform")
        .order_by("-edition__is_default", "-is_default", "platform__name", "id")
    )


def matching_releases(releases: QuerySet[Release], query: str) -> QuerySet[Release]:
    """Releases whose platform or edition match."""
    text = query.strip()
    if not text:
        return releases
    return releases.filter(
        Q(platform__name__icontains=text) | Q(edition__name__icontains=text)
    )


def release_label(release: Release) -> str:
    """Platform, named edition, then year."""
    parts = [
        UNSPECIFIED_PLATFORM if release.platform is None else release.platform.name
    ]
    if release.edition.name:
        parts.append(release.edition.name)
    if release.release_date is not None and release.release_date.year is not None:
        parts.append(str(release.release_date.year))
    return " · ".join(parts)
