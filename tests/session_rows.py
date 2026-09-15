"""Session rows written by hand for reads."""

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

#: The zone both twins read days in.
TWIN_ZONE = ZoneInfo("Europe/Prague")


def tracked_run(library: UserLibrary, game: Game) -> Playthrough:
    """The library's ordinary run, made when missing."""
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


def session_row(
    game: Game,
    *,
    started_at: datetime,
    ended_at: datetime | None = None,
    duration_manual: timedelta | None = None,
    library: UserLibrary | None = None,
    **columns: object,
) -> PlayerSession:
    """A projection row shaped like a legacy create.

    Manual time alone is a Duration-only row on the start's day; manual
    time beside an end is a Corrected row stating the legacy total.
    """
    library = library or game.library
    if library is None:
        raise ValueError("a shared catalog game needs the library stated")
    run = tracked_run(library, game)
    manual = duration_manual or timedelta(0)
    if manual and ended_at is None:
        day = started_at.astimezone(TWIN_ZONE).date()
        return duration_only_row(run, day, manual, **columns)
    if manual and ended_at is not None:
        return corrected_row(
            run,
            started_at,
            ended_at,
            (ended_at - started_at) + manual,
            day_zone=TWIN_ZONE.key,
            **columns,
        )
    return timed_row(run, started_at, ended_at, day_zone=TWIN_ZONE.key, **columns)


class Twin(NamedTuple):
    """A legacy session and its projection row."""

    legacy: Session
    projection: PlayerSession


def timed_twin(
    library: UserLibrary,
    game: Game,
    started_at: datetime,
    ended_at: datetime | None,
) -> Twin:
    """Finished with an end, running without one."""
    return Twin(
        Session.objects.create(
            game=game, timestamp_start=started_at, timestamp_end=ended_at
        ),
        timed_row(
            tracked_run(library, game),
            started_at,
            ended_at,
            day_zone=TWIN_ZONE.key,
        ),
    )


def duration_only_twin(
    library: UserLibrary, game: Game, day: date, duration: timedelta
) -> Twin:
    """No end, a manual duration, noon start."""
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
    """Legacy adds manual time; projection states totals."""
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
