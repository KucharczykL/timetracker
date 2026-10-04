"""Undo only an endpoint the batch wrote."""

import uuid
from dataclasses import dataclass

from games.events.dispatch import CommandRejected
from games.events.endpoint import EndpointEvents, ResumableEndpointEvents
from games.events.vocabulary import EventType
from games.models import UserLibrary
from games.reads.events import aggregate_events

#: What a person reads.
type Sentence = str
#: Names a row in a log line.
type RowDescription = str  # "LibraryEntry <id> of library <id>"


@dataclass(frozen=True, slots=True, kw_only=True)
class UndoSentences:
    """One sentence per refusal."""

    not_stated: Sentence
    changed_since: Sentence


def _unstating[PayloadT](endpoint_events: EndpointEvents[PayloadT]) -> set[EventType]:
    """Acts after which no end stands."""
    unstating = {endpoint_events.voided.event_type}
    if isinstance(endpoint_events, ResumableEndpointEvents):
        unstating.add(endpoint_events.resumed.event_type)
    return unstating


def refuse_unless_this_batch_wrote_it[PayloadT](
    library: UserLibrary,
    aggregate_id: uuid.UUID,
    endpoint_events: EndpointEvents[PayloadT],
    *,
    batch_id: uuid.UUID,
    row_description: RowDescription,
    sentences: UndoSentences,
) -> None:
    """Refuse a value another act wrote.

    Call under the dispatch lock. A latest
    void or resume after ours passes: the
    void then answers already so.
    """
    family = endpoint_events.family
    stated = endpoint_events.stated.event_type
    about = [
        event
        for event in aggregate_events(library, aggregate_id)
        if event.event_type in family
    ]
    ours = [
        event
        for event in about
        if event.correlation_id == batch_id and event.event_type == stated
    ]
    if not ours:
        raise CommandRejected(
            f"batch {batch_id} recorded no {stated} of {row_description}",
            sentence=sentences.not_stated,
        )
    latest = about[-1]
    if latest.sequence == ours[-1].sequence:
        return
    if latest.event_type in _unstating(endpoint_events):
        return
    raise CommandRejected(
        f"{row_description} states {latest.event_type} at sequence "
        f"{latest.sequence}, after batch {batch_id} recorded {stated}",
        sentence=sentences.changed_since,
    )
