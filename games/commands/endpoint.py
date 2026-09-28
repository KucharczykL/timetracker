"""State, correct and void any endpoint."""

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
    never carries it: a row that never reached the endpoint
    states no ActStatement at all.

    A NamedTuple, so the idempotency fingerprint encodes it
    as an array and the TemporalValue inside reaches the
    encoder that knows it.
    """

    #: None is a day nobody wrote down.
    when: TemporalValue | None
    note: str = ""


class WayActStatement(NamedTuple):
    """An act in one way, and its note.

    Not a third ActStatement field: a NamedTuple encodes as
    an array, so that field would move every fingerprint.
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


type Statement = ActStatement | WayActStatement


def _payload(endpoint: Endpoint, statement: Statement) -> dict[str, Any]:
    """The payload; its shape must match."""
    match statement:
        case WayActStatement() if endpoint.way is not None:
            return {"way": statement.way.value, "note": statement.note}
        case ActStatement() if endpoint.way is None:
            return {"note": statement.note}
    raise TypeError(
        f"Endpoint {endpoint.name!r} takes a "
        f"{'WayActStatement' if endpoint.way else 'ActStatement'}."
    )


def _states_it(row: models.Model, endpoint: Endpoint, statement: Statement) -> bool:
    held = stated(row, endpoint)
    if held is None:
        return False
    way = statement.way if isinstance(statement, WayActStatement) else None
    return (held.when, held.note, held.way) == (statement.when, statement.note, way)


def state_endpoint(
    row: models.Model,
    endpoint: Endpoint,
    statement: Statement,
    *,
    sentences: EndpointSentences,
    before_event: BeforeEvent = _nothing,
) -> Sequence[NewEvent] | Unchanged:
    """The act; a repeat unchanged, another refused."""
    payload = _payload(endpoint, statement)
    if stated(row, endpoint) is not None:
        if _states_it(row, endpoint, statement):
            return Unchanged(sentences.same_statement)
        raise sentences.already_stated.raised()
    before_event()
    return [
        endpoint.events.stated.new(
            aggregate_id=row.pk, effective_time=statement.when, payload=payload
        )
    ]


def correct_endpoint(
    row: models.Model,
    endpoint: Endpoint,
    statement: Statement,
    *,
    sentences: EndpointSentences,
    before_event: BeforeEvent = _nothing,
) -> Sequence[NewEvent] | Unchanged:
    """A better statement of a stated act.

    Unstated is refused before comparing: without ways it
    holds the values a correction to no day states.
    """
    payload = _payload(endpoint, statement)
    if stated(row, endpoint) is None:
        raise sentences.nothing_to_correct.raised()
    if _states_it(row, endpoint, statement):
        return Unchanged(sentences.same_correction)
    before_event()
    return [
        endpoint.events.corrected.new(
            aggregate_id=row.pk, effective_time=statement.when, payload=payload
        )
    ]


def void_endpoint(
    row: models.Model,
    endpoint: Endpoint,
    *,
    sentences: EndpointSentences,
    before_event: BeforeEvent = _nothing,
) -> Sequence[NewEvent] | Unchanged:
    """The record taken back; repeats answer first."""
    if stated(row, endpoint) is None:
        return Unchanged(sentences.nothing_to_void)
    before_event()
    return [endpoint.events.voided.new(aggregate_id=row.pk, payload={})]
