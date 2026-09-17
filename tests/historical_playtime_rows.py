"""Historical playtime rows written by hand for reads."""

import uuid
from collections.abc import Sequence
from datetime import timedelta

from django.utils import timezone

from games.models import (
    Device,
    HistoricalPlaytime,
    HistoricalPlaytimeProvenance,
    HistoricalPlaytimeRun,
    Playthrough,
)

type CanonicalWhen = str  # e.g. "2020/2022"


def record_row(
    runs: Sequence[Playthrough],
    *,
    duration: timedelta = timedelta(hours=1),
    when: CanonicalWhen | None = None,
    provenance: HistoricalPlaytimeProvenance = HistoricalPlaytimeProvenance.ESTIMATED,
    device: Device | None = None,
    emulated: bool = False,
    note: str = "",
) -> HistoricalPlaytime:
    """One record naming these runs, all of one tracked game."""
    first = runs[0]
    record = HistoricalPlaytime.objects.create(
        id=uuid.uuid7(),
        library=first.library,
        player_game=first.player_game,
        duration=duration,
        when=when,
        provenance=provenance,
        device=device,
        emulated=emulated,
        note=note,
        created_at=timezone.now(),
    )
    for run in runs:
        HistoricalPlaytimeRun.objects.create(
            id=uuid.uuid7(), library=first.library, record=record, playthrough=run
        )
    return record
