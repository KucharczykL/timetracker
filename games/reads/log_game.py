"""What a game already holds, read once."""

from typing import NamedTuple

from django.db.models import F, QuerySet

from games.ids import GameId, ReleaseId
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


class HeldRun(NamedTuple):
    """The newest live ordinary run and what it states."""

    run: Playthrough
    #: Endpoints; None where unstated.
    started: StatedEndpoint | None
    completed: StatedEndpoint | None
    note: str


class HeldFacts(NamedTuple):
    """What a game holds, read once."""

    #: The game these facts were read for.
    game_id: GameId
    #: Library removed the tracked game.
    removed: bool
    #: The tracked status, else none.
    status: PlayerGameStatus | None
    # TODO(#1519): a run picker.
    #: Newest live ordinary run; None if the game has none.
    run: HeldRun | None
    #: Platform of the newest play or copy.
    platform: Platform | None
    mastered: bool


def held_facts(library: UserLibrary, game: Game) -> HeldFacts:
    """Status, newest run's acts, platform, mastery."""
    tracked = tracked_game(library, game)
    if tracked is None:
        removed = PlayerGame.objects.filter(
            library=library, game=game, removed_at__isnull=False
        ).exists()
        return HeldFacts(
            game_id=game.pk,
            removed=removed,
            status=None,
            run=None,
            platform=None,
            mastered=False,
        )
    run = live_ordinary_runs(library, tracked).last()
    return HeldFacts(
        game_id=game.pk,
        removed=False,
        status=PlayerGameStatus(tracked.status),
        run=None if run is None else _held_run(run),
        platform=_held_platform(library, game),
        mastered=tracked.mastered,
    )


def _held_run(run: Playthrough) -> HeldRun:
    return HeldRun(
        run=run,
        started=stated_start(run),
        completed=stated_completion(run),
        note=run.note,
    )


def _live_releases(library: UserLibrary, game: Game) -> QuerySet[Release, Release]:
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
    """Live copy's Release there; newest play breaks ties."""
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
