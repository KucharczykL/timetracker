"""What a run states about its two endpoints."""

from datetime import date
from typing import NamedTuple

from games.endpoints import PLAYTHROUGH_COMPLETION, PLAYTHROUGH_START
from games.models import Playthrough
from games.reads import endpoints
from games.reads.endpoints import StatedEndpoint


def stated_start(run: Playthrough) -> StatedEndpoint | None:
    """What the run states about its start, or nothing."""
    return endpoints.stated(run, PLAYTHROUGH_START)


def stated_completion(run: Playthrough) -> StatedEndpoint | None:
    """What the run states about its completion, or nothing."""
    return endpoints.stated(run, PLAYTHROUGH_COMPLETION)


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
    field cannot hold. The form states whole days, so
    seeding one from such a value and posting it back
    would flatten what the run states. The API states every
    value the grammar knows; no screen does yet.
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
