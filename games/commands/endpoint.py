"""The three acts on a stated endpoint, over any row.

Each aggregate keeps its own command classes, fields and resolve, so
a command's fingerprint stays its own; these functions decide, in one
order, what the resolved row answers to a statement.
"""

from collections.abc import Callable, Sequence
from typing import Any, NamedTuple

from django.db import models

from games.end_ways import EndWay
from games.endpoints import Endpoint
from games.events.dispatch import CommandRejected
from games.events.vocabulary import NewEvent, Unchanged
from games.reads.endpoints import stated
from timetracker.temporal import TemporalValue


class ActStatement(NamedTuple):
    """An act that happened, and its note.

    The act is this object's existence, so the day inside
    never carries it: a run that never reached the endpoint
    states no ActStatement at all.

    A NamedTuple, so the idempotency fingerprint encodes it
    as an array and the TemporalValue inside reaches the
    encoder that knows it.
    """

    #: None is a day nobody wrote down.
    when: TemporalValue | None
    note: str = ""


class WayActStatement(NamedTuple):
    """An act that happened in one way, and its note.

    Not ActStatement with a third field: a NamedTuple encodes as an
    array, so one more field would move the fingerprint of every
    command carrying an ActStatement.
    """

    when: TemporalValue | None
    way: EndWay
    note: str = ""


class Rejection(NamedTuple):
    """A refusal's two sentences: the log's and the person's."""

    message: str
    sentence: str

    def raised(self) -> CommandRejected:
        return CommandRejected(self.message, sentence=self.sentence)


class EndpointSentences(NamedTuple):
    """What one aggregate says about one endpoint."""

    already_stated: Rejection
    nothing_to_correct: Rejection
    #: Each Unchanged's log line.
    same_statement: str
    same_correction: str
    nothing_to_void: str


type BeforeEvent = Callable[[], None]


def _nothing() -> None:
    return None


def _payload(endpoint: Endpoint, note: str, way: EndWay | None) -> dict[str, Any]:
    if endpoint.way is None:
        return {"note": note}
    if way is None:
        raise TypeError(f"Endpoint {endpoint.name!r} states every act in a way.")
    return {"way": way.value, "note": note}


def _states_it(
    row: models.Model,
    endpoint: Endpoint,
    when: TemporalValue | None,
    note: str,
    way: EndWay | None,
) -> bool:
    held = stated(row, endpoint)
    return held is not None and (held.when, held.note, held.way) == (
        when,
        note,
        way,
    )


def state_endpoint(
    row: models.Model,
    endpoint: Endpoint,
    *,
    when: TemporalValue | None,
    note: str,
    way: EndWay | None = None,
    sentences: EndpointSentences,
    before_event: BeforeEvent = _nothing,
) -> Sequence[NewEvent] | Unchanged:
    """The act, where the row states none.

    The same statement again is a repeat; another is refused,
    because a second act would say it happened twice.
    """
    if stated(row, endpoint) is not None:
        if _states_it(row, endpoint, when, note, way):
            return Unchanged(sentences.same_statement)
        raise sentences.already_stated.raised()
    before_event()
    return [
        endpoint.events.stated.new(
            aggregate_id=row.pk,
            effective_time=when,
            payload=_payload(endpoint, note, way),
        )
    ]


def correct_endpoint(
    row: models.Model,
    endpoint: Endpoint,
    *,
    when: TemporalValue | None,
    note: str,
    way: EndWay | None = None,
    sentences: EndpointSentences,
    before_event: BeforeEvent = _nothing,
) -> Sequence[NewEvent] | Unchanged:
    """A better statement of an act the row states.

    The unstated endpoint is refused ahead of the comparison: it
    holds the very values a correction to no day and no note states.
    """
    if stated(row, endpoint) is None:
        raise sentences.nothing_to_correct.raised()
    if _states_it(row, endpoint, when, note, way):
        return Unchanged(sentences.same_correction)
    before_event()
    return [
        endpoint.events.corrected.new(
            aggregate_id=row.pk,
            effective_time=when,
            payload=_payload(endpoint, note, way),
        )
    ]


def void_endpoint(
    row: models.Model,
    endpoint: Endpoint,
    *,
    sentences: EndpointSentences,
    before_event: BeforeEvent = _nothing,
) -> Sequence[NewEvent] | Unchanged:
    """The record taken back.

    The repeat first, so it succeeds whatever `before_event` refuses.
    """
    if stated(row, endpoint) is None:
        return Unchanged(sentences.nothing_to_void)
    before_event()
    return [endpoint.events.voided.new(aggregate_id=row.pk, payload={})]
