"""A write's revaluation request."""

import logging

from django.contrib.auth.models import User
from django.db import DatabaseError

from games.conversion import request_revaluation
from games.events.dispatch import CommandOutcome, CommandResult
from games.events.purchase import VALUATION_EVENTS
from games.events.vocabulary import EventType
from games.reads.events import dispatched_events

logger = logging.getLogger("games")


def appended_types(result: CommandResult) -> frozenset[EventType]:
    if result.outcome is not CommandOutcome.APPENDED:
        return frozenset()
    return frozenset(event.event_type for event in dispatched_events(result))


def revalue_after(actor: User, event_types: frozenset[EventType]) -> None:
    """Request a run; recovery catches a loss.

    The write already committed, so a database
    failure is logged, never answered.
    """
    if VALUATION_EVENTS.isdisjoint(event_types):
        return
    try:
        request_revaluation(actor.library)
    except DatabaseError:
        logger.exception(
            "Revaluation request lost for library %s after %s; "
            "the daily recovery requests it.",
            actor.library.pk,
            sorted(event_types),
        )
