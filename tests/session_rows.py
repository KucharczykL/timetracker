"""Session rows a playtime read counts, written by hand.

A projection row is written the way the projector writes it, so a
read test states its columns rather than an event stream.
"""

import uuid
from datetime import date, datetime, timedelta

from django.utils import timezone

from games.models import (
    Game,
    PlayerGame,
    PlayerSession,
    PlayerSessionTimingMode,
    Playthrough,
    PlaythroughKind,
    UserLibrary,
)


def tracked_run(library: UserLibrary, game: Game) -> Playthrough:
    """The ordinary run this library tracks the game with.

    Made where missing: a shared catalog game is tracked by no
    fixture.
    """
    player_game, _ = PlayerGame.objects.get_or_create(
        library=library,
        game=game,
        defaults={"pk": uuid.uuid7(), "tracked_at": timezone.now()},
    )
    run = Playthrough.objects.filter(
        library=library, player_game=player_game, kind=PlaythroughKind.ORDINARY
    ).first()
    if run is not None:
        return run
    return Playthrough.objects.create(
        pk=uuid.uuid7(),
        library=library,
        player_game=player_game,
        kind=PlaythroughKind.ORDINARY,
        created_at=timezone.now(),
    )


def projection_row(run: Playthrough, **columns: object) -> PlayerSession:
    """One row, every column stated."""
    stated: dict[str, object] = {
        "id": uuid.uuid7(),
        "library": run.library,
        "playthrough": run,
        "device": None,
        "timing_mode": PlayerSessionTimingMode.TIMED,
        "started_at": None,
        "started_at_zone": None,
        "ended_at": None,
        "ended_at_zone": None,
        "stated_day": None,
        "stated_duration": None,
        "day_zone": None,
        "note": "",
        "emulated": False,
        "created_at": timezone.now(),
    } | columns
    return PlayerSession.objects.create(**stated)


def timed_row(
    run: Playthrough,
    started_at: datetime,
    ended_at: datetime | None,
    *,
    day_zone: str = "Europe/Prague",
    **columns: object,
) -> PlayerSession:
    return projection_row(
        run,
        timing_mode=PlayerSessionTimingMode.TIMED,
        started_at=started_at,
        ended_at=ended_at,
        day_zone=day_zone,
        **columns,
    )


def duration_only_row(
    run: Playthrough, stated_day: date, stated_duration: timedelta, **columns: object
) -> PlayerSession:
    return projection_row(
        run,
        timing_mode=PlayerSessionTimingMode.DURATION_ONLY,
        stated_day=stated_day,
        stated_duration=stated_duration,
        **columns,
    )


def corrected_row(
    run: Playthrough,
    started_at: datetime,
    ended_at: datetime,
    stated_duration: timedelta,
    *,
    day_zone: str = "Europe/Prague",
    **columns: object,
) -> PlayerSession:
    return projection_row(
        run,
        timing_mode=PlayerSessionTimingMode.CORRECTED,
        started_at=started_at,
        ended_at=ended_at,
        stated_duration=stated_duration,
        day_zone=day_zone,
        **columns,
    )
