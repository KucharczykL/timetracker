"""Undo only an endpoint the batch wrote."""

import uuid
from collections.abc import Iterable
from typing import Any, NamedTuple

from games.events.dispatch import CommandRejected
from games.events.endpoint import EndpointEvents
from games.models import LibraryEvent


class UndoSentences(NamedTuple):
    """What a person reads per refusal."""

    not_stated: str
    changed_since: str


def refuse_unless_this_batch_wrote_it(
    events: Iterable[LibraryEvent],
    endpoint_events: EndpointEvents[Any],
    *,
    batch_id: uuid.UUID,
    row_description: str,
    sentences: UndoSentences,
) -> None:
    """Refuse a value another act wrote.

    A latest void passes: the void answers
    already so. Otherwise the batch's own
    statement must still be the latest.
    """
    family = endpoint_events.family
    stated = endpoint_events.stated.event_type
    about = [event for event in events if event.event_type in family]
    if about and about[-1].event_type == endpoint_events.voided.event_type:
        return
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
    if about[-1].sequence != ours[-1].sequence:
        raise CommandRejected(
            f"{row_description} states {about[-1].event_type} at sequence "
            f"{about[-1].sequence}, after batch {batch_id} recorded {stated}",
            sentence=sentences.changed_since,
        )
