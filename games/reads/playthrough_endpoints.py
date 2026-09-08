"""What a run states about its two endpoints."""

from dataclasses import dataclass
from datetime import date, datetime
from typing import NamedTuple

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


def days_to_finish(run: Playthrough) -> int | None:
    """Days the run touched, both ends counted.

    A same-day run reads 1. An absent bound and a
    completion before the start read nothing, so the
    count never reads 0.
    """
    started = run.started_lower
    completed = run.completed_upper
    if started is None or completed is None:
        return None
    days = (completed - started).days + 1
    return days if days >= 1 else None


class StatedDays(NamedTuple):
    """A run's two endpoints, as plain days."""

    #: None where the endpoint states no day, or no act.
    started: date | None
    ended: date | None


def restatable_days(run: Playthrough) -> StatedDays | None:
    """The run's endpoints as days, or nothing.

    Nothing where either endpoint states a value a day
    field cannot hold. Both request paths state whole days,
    so seeding one from such a value and posting it back
    would flatten what the run states. #1015 owns the
    screen that reads the richer value.
    """
    days: list[date | None] = []
    for stated in (stated_start(run), stated_completion(run)):
        if stated is None or stated.when is None:
            days.append(None)
            continue
        day = stated.when.lower_bound
        #: Equal serializations is the whole test: a month,
        #: a decade, a range and a qualified day all spell
        #: themselves differently from the bare day beneath.
        if day is None or stated.when.serialize() != day.isoformat():
            return None
        days.append(day)
    return StatedDays(days[0], days[1])
