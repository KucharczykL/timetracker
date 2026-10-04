"""Whether figures and lists hold prerelease play."""

from django.db.models import Q, QuerySet

from games.models import EditionKind, Release, UserLibrary
from timetracker.settings_resolver import resolve_for_user

#: Play on a prerelease Edition.
PRERELEASE_PLAY = Q(release__edition__kind=EditionKind.PRERELEASE)


def prerelease_releases() -> QuerySet[Release, Release]:
    """Every Release of a prerelease Edition."""
    return Release.objects.filter(edition__kind=EditionKind.PRERELEASE)


def shows_prerelease_play(library: UserLibrary) -> bool:
    """The library owner's setting, resolved."""
    return resolve_for_user(library.user, "SHOW_PRERELEASE_PLAY") == "show"


def shown_play(library: UserLibrary) -> Q:
    """Sessions or records the library's figures hold.

    Hidden, a row naming no Release stays: NULL NOT IN
    answers NULL. Not the join of `PRERELEASE_PLAY`: two
    joins on every subquery cost the statistics a quarter.
    """
    if shows_prerelease_play(library):
        return Q()
    return Q(release__isnull=True) | ~Q(
        release_id__in=prerelease_releases().values("pk")
    )
