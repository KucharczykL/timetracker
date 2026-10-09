"""What a game already holds, read once."""

from typing import NamedTuple

from django.db.models import F

from games.ids import ReleaseId
from games.models import (
    Game,
    Platform,
    PlayerGame,
    PlayerGameStatus,
    Playthrough,
    Release,
    UserLibrary,
)
from games.reads.endpoints import StatedEndpoint
from games.reads.entries import library_entries
from games.reads.historical_playtime_records import library_records
from games.reads.player_sessions import library_sessions
from games.reads.playthrough_endpoints import stated_completion, stated_start
from games.reads.playthrough_runs import live_ordinary_runs, tracked_game


class HeldFacts(NamedTuple):
    """What a game holds, read once."""

    #: Library removed the tracked game.
    removed: bool
    #: The tracked status, else none.
    status: PlayerGameStatus | None
    #: Newest live run; a placeholder rule.
    run: Playthrough | None
    #: Run's endpoints; None where unstated.
    started: StatedEndpoint | None
    completed: StatedEndpoint | None
    #: Platform of the newest play or copy.
    platform: Platform | None
    mastered: bool
    note: str


def held_facts(library: UserLibrary, game: Game) -> HeldFacts:
    """Status, newest run's acts, platform, mastery."""
    tracked = tracked_game(library, game)
    if tracked is None:
        removed = PlayerGame.objects.filter(
            library=library, game=game, removed_at__isnull=False
        ).exists()
        return HeldFacts(
            removed=removed,
            status=None,
            run=None,
            started=None,
            completed=None,
            platform=None,
            mastered=False,
            note="",
        )
    run = live_ordinary_runs(library, tracked).last()
    return HeldFacts(
        removed=False,
        status=PlayerGameStatus(tracked.status),
        run=run,
        started=None if run is None else stated_start(run),
        completed=None if run is None else stated_completion(run),
        platform=_held_platform(library, game),
        mastered=tracked.mastered,
        note="" if run is None else run.note,
    )


def _live_releases(library: UserLibrary, game: Game):
    """Releases this library sees for a game."""
    return Release.objects.visible_to(library).filter(
        edition__game=game,
        platform__in=Platform.objects.visible_to(library),
    )


def _held_platform(library: UserLibrary, game: Game) -> Platform | None:
    """Newest session, else record, else copy."""
    releases = _live_releases(library, game)
    named = (
        library_sessions(library)
        .filter(playthrough__player_game__game=game, release__in=releases)
        .order_by("-sort_instant", "-id")
        .values_list("release_id", flat=True)
        .first()
    )
    if named is None:
        named = (
            library_records(library)
            .filter(player_game__game=game, release__in=releases)
            .order_by(F("when_upper").desc(nulls_last=True), "-id")
            .values_list("release_id", flat=True)
            .first()
        )
    if named is None:
        named = (
            library_entries(library)
            .filter(release__edition__game=game, release__in=releases)
            .order_by("-created_at", "-id")
            .values_list("release_id", flat=True)
            .first()
        )
    if named is None:
        return None
    return releases.select_related("platform").get(pk=named).platform


def copy_release_for(
    library: UserLibrary, game: Game, platform: Platform | None
) -> Release | None:
    """Live copy's Release on that platform."""
    copies = (
        library_entries(library)
        .filter(release__edition__game=game, release__platform=platform)
        .select_related("release")
        .order_by("-created_at", "-id")
    )
    releases: dict[ReleaseId, Release] = {}
    for copy in copies:
        releases.setdefault(copy.release_id, copy.release)
    if not releases:
        return None
    if len(releases) == 1:
        return next(iter(releases.values()))
    named = (
        library_sessions(library)
        .filter(playthrough__player_game__game=game, release_id__in=list(releases))
        .order_by("-sort_instant", "-id")
        .values_list("release_id", flat=True)
        .first()
    )
    if named in releases:
        return releases[named]
    return next(iter(releases.values()))
