"""Historical playtime rows written by hand for reads."""

import uuid
from datetime import timedelta

from django.utils import timezone

from games.models import (
    HistoricalPlaytime,
    HistoricalPlaytimeProvenance,
    HistoricalPlaytimeRun,
    Playthrough,
)


def record_join(record: HistoricalPlaytime, run: Playthrough) -> HistoricalPlaytimeRun:
    return HistoricalPlaytimeRun.objects.create(
        id=uuid.uuid7(), library=record.library, record=record, playthrough=run
    )


def record_row(
    run: Playthrough,
    *,
    duration: timedelta,
    when: str | None,
    provenance: HistoricalPlaytimeProvenance = HistoricalPlaytimeProvenance.ESTIMATED,
    **columns: object,
) -> HistoricalPlaytime:
    """One record naming `run`, every column stated."""
    stated: dict[str, object] = {
        "id": uuid.uuid7(),
        "library": run.library,
        "player_game": run.player_game,
        "duration": duration,
        "when": when,
        "provenance": provenance,
        "device": None,
        "emulated": False,
        "note": "",
        "created_at": timezone.now(),
    } | columns
    record = HistoricalPlaytime.objects.create(**stated)
    record_join(record, run)
    return record
