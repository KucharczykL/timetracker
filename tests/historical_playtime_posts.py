"""What the historical playtime form posts."""

import uuid
from collections.abc import Iterable

from games.models import HistoricalPlaytimeProvenance
from timetracker.temporal import temporal_input_name

type MultiValuePost = dict[str, str | list[str]]
type WhenYear = str  # e.g. "2005"


def posted_record(
    run_ids: Iterable[uuid.UUID],
    *,
    hours: str = "100",
    minutes: str = "0",
    when_year: WhenYear | None = None,
    **overrides: str | list[str],
) -> MultiValuePost:
    """A whole submit; a year when given, else unknown."""
    data: MultiValuePost = {
        "playthroughs": [str(run_id) for run_id in run_ids],
        "duration_hours": hours,
        "duration_minutes": minutes,
        temporal_input_name("when", "kind"): "unknown",
        "provenance": HistoricalPlaytimeProvenance.ESTIMATED.value,
        "device": "",
        "note": "",
        "submission": str(uuid.uuid7()),
    }
    if when_year is not None:
        data[temporal_input_name("when", "kind")] = "date"
        data[temporal_input_name("when", "start_year")] = when_year
    data.update(overrides)
    return data
