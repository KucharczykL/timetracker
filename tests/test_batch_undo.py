"""The rule an endpoint's batch Undo reads."""

import uuid
from datetime import date

import pytest
from django.db import transaction
from entries import record_entry

from games.commands.batch_undo import UndoSentences, refuse_unless_this_batch_wrote_it
from games.commands.endpoint import ActStatement, WayActStatement
from games.commands.libraryentry import (
    CorrectEntryAccessEnd,
    EndEntryAccess,
    ResumeEntryAccess,
    VoidEntryAccessEnd,
)
from games.end_ways import EndWay
from games.events.dispatch import Command, CommandRejected, append_command
from games.events.libraryentry import ENTRY_ACCESS_END_EVENTS
from games.models import Game, LibraryEntry, Platform, UserLibrary
from timetracker.temporal import TemporalValue

pytestmark = pytest.mark.django_db

SENTENCES = UndoSentences(not_stated="not ours", changed_since="changed since")
ENDED = WayActStatement(TemporalValue.from_day(date(2024, 5, 1)), EndWay.SOLD, "")


@pytest.fixture
def copy(owned_library, stated_graph) -> LibraryEntry:
    graph = stated_graph(
        Game(name="Tunic", library=owned_library),
        owned_library,
        platform=Platform.objects.create(name="PS5", group="Sony"),
    )
    return record_entry(owned_library, graph.release)


def _state(library: UserLibrary, command: Command, batch: uuid.UUID) -> None:
    with transaction.atomic():
        append_command(
            command,
            actor=library.user,
            library=library,
            idempotency_key=str(uuid.uuid7()),
            correlation_id=batch,
        )


def _judge(library: UserLibrary, copy: LibraryEntry, batch: uuid.UUID) -> None:
    refuse_unless_this_batch_wrote_it(
        library,
        copy.pk,
        ENTRY_ACCESS_END_EVENTS,
        batch_id=batch,
        row_description=f"entry {copy.pk}",
        sentences=SENTENCES,
    )


def test_the_batchs_own_end_still_latest_passes(owned_library, copy):
    batch = uuid.uuid7()
    _state(owned_library, EndEntryAccess(entry_id=copy.pk, statement=ENDED), batch)

    _judge(owned_library, copy, batch)


def test_an_end_already_voided_passes(owned_library, copy):
    batch = uuid.uuid7()
    _state(owned_library, EndEntryAccess(entry_id=copy.pk, statement=ENDED), batch)
    _state(owned_library, VoidEntryAccessEnd(entry_id=copy.pk), uuid.uuid7())

    _judge(owned_library, copy, batch)


def test_an_end_the_batch_never_wrote_is_refused(owned_library, copy):
    _state(
        owned_library, EndEntryAccess(entry_id=copy.pk, statement=ENDED), uuid.uuid7()
    )

    with pytest.raises(CommandRejected) as refused:
        _judge(owned_library, copy, uuid.uuid7())

    assert refused.value.sentence == "not ours"


def test_a_row_with_no_end_event_is_refused(owned_library, copy):
    with pytest.raises(CommandRejected) as refused:
        _judge(owned_library, copy, uuid.uuid7())

    assert refused.value.sentence == "not ours"


def test_a_correction_since_is_refused(owned_library, copy):
    batch = uuid.uuid7()
    _state(owned_library, EndEntryAccess(entry_id=copy.pk, statement=ENDED), batch)
    corrected = WayActStatement(ENDED.when, EndWay.LOST, "")
    _state(
        owned_library,
        CorrectEntryAccessEnd(entry_id=copy.pk, statement=corrected),
        uuid.uuid7(),
    )

    with pytest.raises(CommandRejected) as refused:
        _judge(owned_library, copy, batch)

    assert refused.value.sentence == "changed since"


def test_a_resume_since_passes(owned_library, copy):
    """The copy is held again: already so."""
    batch = uuid.uuid7()
    _state(owned_library, EndEntryAccess(entry_id=copy.pk, statement=ENDED), batch)
    _state(
        owned_library,
        ResumeEntryAccess(
            entry_id=copy.pk,
            statement=ActStatement(TemporalValue.from_day(date(2024, 6, 1)), ""),
        ),
        uuid.uuid7(),
    )

    _judge(owned_library, copy, batch)


def test_a_void_the_batch_never_preceded_is_refused(owned_library, copy):
    _state(
        owned_library, EndEntryAccess(entry_id=copy.pk, statement=ENDED), uuid.uuid7()
    )
    _state(owned_library, VoidEntryAccessEnd(entry_id=copy.pk), uuid.uuid7())

    with pytest.raises(CommandRejected) as refused:
        _judge(owned_library, copy, uuid.uuid7())

    assert refused.value.sentence == "not ours"


def test_a_later_end_is_refused(owned_library, copy):
    batch = uuid.uuid7()
    _state(owned_library, EndEntryAccess(entry_id=copy.pk, statement=ENDED), batch)
    _state(
        owned_library,
        ResumeEntryAccess(
            entry_id=copy.pk,
            statement=ActStatement(TemporalValue.from_day(date(2024, 6, 1)), ""),
        ),
        uuid.uuid7(),
    )
    later = WayActStatement(TemporalValue.from_day(date(2024, 7, 1)), EndWay.SOLD, "")
    _state(
        owned_library, EndEntryAccess(entry_id=copy.pk, statement=later), uuid.uuid7()
    )

    with pytest.raises(CommandRejected) as refused:
        _judge(owned_library, copy, batch)

    assert refused.value.sentence == "changed since"
