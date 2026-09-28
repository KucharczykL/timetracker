"""What still names a platform the library takes out.

Each count is a correlated subquery scoped on the library, live rows
only, as the game's departures are.
"""

from typing import NamedTuple

from django.db.models import OuterRef, QuerySet

from games.models import Game, Platform, Purchase, Release, UserLibrary
from games.reads.game_departures import counted

#: The annotations `with_departures` adds.
GAMES = "naming_games"
RELEASES = "naming_releases"
PURCHASES = "naming_purchases"


class PlatformDepartures(NamedTuple):
    """One platform's counts, as its confirmation states them."""

    games: int
    releases: int
    purchases: int


def with_departures(
    platforms: QuerySet[Platform], library: UserLibrary
) -> QuerySet[Platform]:
    """Each platform with the live rows that name it."""
    return platforms.annotate(
        **{
            GAMES: counted(
                Game.objects.for_library(library).filter(platform=OuterRef("pk"))
            ),
            RELEASES: counted(
                Release.objects.for_library(library).filter(platform=OuterRef("pk"))
            ),
            PURCHASES: counted(
                Purchase.objects.for_library(library).filter(platform=OuterRef("pk"))
            ),
        }
    )


def departures_of(platform: Platform) -> PlatformDepartures:
    """The counts one annotated platform carries."""
    return PlatformDepartures(
        games=getattr(platform, GAMES),
        releases=getattr(platform, RELEASES),
        purchases=getattr(platform, PURCHASES),
    )


def platform_departures(library: UserLibrary, platform: Platform) -> PlatformDepartures:
    """One platform's counts, read the way the batch reads them."""
    return departures_of(
        with_departures(Platform.objects.filter(pk=platform.pk), library).get()
    )
