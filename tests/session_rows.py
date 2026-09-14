"""Session rows a playtime read counts, written by hand.

A projection row is written the way the projector writes it, so a
read test states its columns rather than an event stream. A twin
is a legacy row beside the projection row it converts to.
"""

import uuid
from datetime import date, datetime, time, timedelta
from typing import NamedTuple
from zoneinfo import ZoneInfo

from django.utils import timezone

from games.models import (
    Game,
    PlayerGame,
    PlayerSession,
    PlayerSessionTimingMode,
    Playthrough,
    PlaythroughKind,
    Session,
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


class Twin(NamedTuple):
    """A legacy session and the projection row it converts to."""

    legacy: Session
    projection: PlayerSession


#: The zone a twin's day is read in on both sides.
TWIN_ZONE = ZoneInfo("Europe/Prague")


def timed_twin(
    library: UserLibrary,
    game: Game,
    started_at: datetime,
    ended_at: datetime | None,
    **columns: object,
) -> Twin:
    """Finished when it has an end, running when it has none."""
    return Twin(
        Session.objects.create(
            game=game, timestamp_start=started_at, timestamp_end=ended_at
        ),
        timed_row(
            tracked_run(library, game),
            started_at,
            ended_at,
            day_zone=TWIN_ZONE.key,
            **columns,
        ),
    )


def duration_only_twin(
    library: UserLibrary, game: Game, day: date, duration: timedelta
) -> Twin:
    """No end, a manual duration, started at noon of the day."""
    return Twin(
        Session.objects.create(
            game=game,
            timestamp_start=datetime.combine(day, time(12), tzinfo=TWIN_ZONE),
            duration_manual=duration,
        ),
        duration_only_row(tracked_run(library, game), day, duration),
    )


def corrected_twin(
    library: UserLibrary,
    game: Game,
    started_at: datetime,
    ended_at: datetime,
    manual: timedelta,
) -> Twin:
    """Legacy adds the manual part; the projection states the total."""
    legacy = Session.objects.create(
        game=game,
        timestamp_start=started_at,
        timestamp_end=ended_at,
        duration_manual=manual,
    )
    return Twin(
        legacy,
        corrected_row(
            tracked_run(library, game),
            started_at,
            ended_at,
            (ended_at - started_at) + manual,
            day_zone=TWIN_ZONE.key,
        ),
    )
