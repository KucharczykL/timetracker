"""State, correct and void any endpoint."""

from collections.abc import Callable, Sequence
from typing import Any, NamedTuple, overload

from django.db import models

from games.end_ways import EndWay
from games.endpoint_fields import EndpointColumnsBase
from games.endpoints import Endpoint, OpeningEndpoint
from games.events.dispatch import CommandRejected
from games.events.vocabulary import NewEvent, Unchanged
from games.reads.endpoints import stated
from timetracker.temporal import TemporalQualifier, TemporalValue, stated_date


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
    #: Only an endpoint that resumes states it.
    nothing_to_resume: Rejection | None = None


type BeforeEvent = Callable[[], None]


def _nothing() -> None:
    return None


type Statement = ActStatement | WayActStatement


@overload
def normalized(statement: ActStatement) -> ActStatement: ...
@overload
def normalized(statement: WayActStatement) -> WayActStatement: ...
def normalized(statement: Statement) -> Statement:
    """One spelling, so restatements fingerprint alike."""
    return statement._replace(
        when=stated_date(statement.when), note=statement.note.strip()
    )


def _bounding_qualifier(
    value: TemporalValue, *, at_start: bool
) -> TemporalQualifier | None:
    """The qualifier on the end the comparison reads.

    A range states no qualifier of its own; each endpoint states one.
    Only the end that produced the bound in hand can excuse it, so the
    far end is not consulted -- it says nothing about that day.
    """
    if not value.is_range:
        return value.qualifier
    endpoint = value.start if at_start else value.end
    return None if endpoint is None else endpoint.qualifier


def certainly_reversed(
    *, earlier: TemporalValue | None, later: TemporalValue | None
) -> bool:
    """Whether `later` cannot follow `earlier`.

    Keyword-only, because the two arguments share a type and the order
    is the whole meaning: a swap is silent on every pair but the one
    this exists to catch.

    Only the certainly-impossible. A bound is unknown for two reasons:
    no date at all, or a range whose end is open or unknown --
    `../2024-06` and `2024-01/` both bound nothing below and above
    respectively -- and a window with no edge contradicts nothing.

    A qualifier leaves the bounds where the bare value put them, so
    `2024-05-10~` bounds to that day exactly. Refusing a later day on
    the 9th would refuse what `~` was written to say.
    """
    if earlier is None or later is None:
        return False
    if _bounding_qualifier(earlier, at_start=True) is not None:
        return False
    if _bounding_qualifier(later, at_start=False) is not None:
        return False
    if earlier.lower_bound is None or later.upper_bound is None:
        return False
    return later.upper_bound < earlier.lower_bound


def _payload(endpoint: EndpointColumnsBase, statement: Statement) -> dict[str, Any]:
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


def _states_it(
    row: models.Model, endpoint: EndpointColumnsBase, statement: Statement
) -> bool:
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


def resume_endpoint(
    row: models.Model,
    endpoint: Endpoint,
    statement: ActStatement,
    *,
    sentences: EndpointSentences,
    before_event: BeforeEvent = _nothing,
) -> Sequence[NewEvent]:
    """Access again after a standing end.

    No Unchanged: a row with no end did not resume.
    """
    resumed = endpoint.events.resumed_spec()
    if sentences.nothing_to_resume is None:
        raise TypeError(f"Endpoint {endpoint.name!r} states no resume sentence.")
    if stated(row, endpoint) is None:
        raise sentences.nothing_to_resume.raised()
    before_event()
    return [
        resumed.new(
            aggregate_id=row.pk,
            effective_time=statement.when,
            payload={"note": statement.note},
        )
    ]


def correct_opening_endpoint(
    row: models.Model,
    endpoint: OpeningEndpoint,
    statement: ActStatement,
    *,
    same_correction: str,
    before_event: BeforeEvent = _nothing,
) -> Sequence[NewEvent] | Unchanged:
    """Restate the creation's day and note."""
    payload = _payload(endpoint, statement)
    if _states_it(row, endpoint, statement):
        return Unchanged(same_correction)
    before_event()
    return [
        endpoint.events.corrected.new(
            aggregate_id=row.pk, effective_time=statement.when, payload=payload
        )
    ]
