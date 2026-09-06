"""What a run states about its two endpoints."""

from dataclasses import dataclass
from datetime import datetime

from games.models import Playthrough
from timetracker.temporal import TemporalValue


@dataclass(frozen=True, slots=True)
class StatedEndpoint:
    """An act that occurred, and what was said about it.

    The act is this object's existence, which is why the date never
    has to carry it: `when` is None for a day nobody knows, and a run
    that never reached this endpoint has no `StatedEndpoint` at all.
    """

    recorded_at: datetime
    when: TemporalValue | None
    note: str


def stated_start(run: Playthrough) -> StatedEndpoint | None:
    """What the run states about its start, or nothing."""
    if run.start_recorded_at is None:
        return None
    return StatedEndpoint(run.start_recorded_at, run.started, run.start_note)


def stated_completion(run: Playthrough) -> StatedEndpoint | None:
    """What the run states about its completion, or nothing."""
    if run.completion_recorded_at is None:
        return None
    return StatedEndpoint(
        run.completion_recorded_at, run.completed, run.completion_note
    )
