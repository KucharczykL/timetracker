"""Whether figures and lists hold prerelease play."""

from django.db.models import Q

from games.models import EditionKind, Release, UserLibrary
from timetracker.settings_registry import PrereleasePlay
from timetracker.settings_resolver import resolve_str_for_user

#: Play on a prerelease Edition.
PRERELEASE_PLAY = Q(release__edition__kind=EditionKind.PRERELEASE)


def shows_prerelease_play(library: UserLibrary) -> bool:
    """The owner's setting; another word raises."""
    word = resolve_str_for_user(library.user, "SHOW_PRERELEASE_PLAY")
    return PrereleasePlay(word) is PrereleasePlay.SHOW


def shown_play(library: UserLibrary) -> Q:
    """The predicate figures and lists apply.

    Not the join of `PRERELEASE_PLAY`: two joins on every
    subquery cost the statistics a quarter. A row naming
    no Release stays: Django adds IS NOT NULL.
    """
    if shows_prerelease_play(library):
        return Q()
    prerelease = Release.objects.filter(edition__kind=EditionKind.PRERELEASE)
    return ~Q(release_id__in=prerelease.values("pk"))
