"""What still names a departing platform."""

from typing import NamedTuple

from django.db.models import OuterRef, QuerySet

from games.models import Game, Platform, Release, UserLibrary
from games.reads.game_departures import counted
from games.reads.purchases import library_purchases

#: The annotations `with_platform_departures` adds.
GAMES = "naming_games"
RELEASES = "naming_releases"
PURCHASES = "naming_purchases"


class PlatformDepartures(NamedTuple):
    """One platform's counts."""

    games: int
    releases: int
    purchases: int


def with_platform_departures(
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
            #: Through the copy's Release.
            PURCHASES: counted(
                library_purchases(library).filter(
                    entry__release__platform=OuterRef("pk")
                )
            ),
        }
    )


def platform_departures_of(platform: Platform) -> PlatformDepartures:
    """The counts one annotated platform carries."""
    return PlatformDepartures(
        games=getattr(platform, GAMES),
        releases=getattr(platform, RELEASES),
        purchases=getattr(platform, PURCHASES),
    )


def platform_departures(library: UserLibrary, platform: Platform) -> PlatformDepartures:
    """One platform's counts, for one row."""
    return platform_departures_of(
        with_platform_departures(Platform.objects.filter(pk=platform.pk), library).get()
    )
