"""A refund under the caller's key, and its latest act."""

import uuid

import pytest
from entries import record_entry
from purchases import record_purchase, refund_purchase, void_refund

from games.commands.endpoint import ActStatement
from games.events.purchase import PURCHASE_REFUND_EVENTS
from games.models import Game, LibraryEvent
from games.reads.purchases import latest_refund_act
from games.writes.answers import CommandFailed
from games.writes.purchase import CopyEnd, restate_purchase
from games.writes.purchase import refund_purchase as refund_now
from timetracker.temporal import TemporalValue

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.untracked_games]

JUNE = TemporalValue.parse("2021-06-03")
JULY = TemporalValue.parse("2021-07-01")


@pytest.fixture
def entry(owned_library, stated_graph):
    graph = stated_graph(Game(name="Tunic", library=owned_library), owned_library)
    return record_entry(owned_library, graph.release)


def _refund(library, purchase, key: str):
    return refund_now(
        library.user,
        purchase,
        ActStatement(JUNE, ""),
        correlation_id=uuid.uuid7(),
        idempotency_key=key,
    )


def test_a_game_refund_answers_its_own_sequence(owned_library, entry):
    purchase = record_purchase(entry)

    refunded = _refund(owned_library, purchase, str(uuid.uuid7()))

    event = LibraryEvent.objects.get(sequence=refunded.sequence, library=owned_library)
    assert event.event_type == PURCHASE_REFUND_EVENTS.stated.event_type
    assert event.aggregate_id == purchase.pk
    assert refunded.copy_end is CopyEnd.ENDED
    #: The copy's end follows it.
    assert LibraryEvent.objects.filter(
        library=owned_library, sequence=refunded.sequence + 1, aggregate_id=entry.pk
    ).exists()


def test_a_repeated_key_replays_the_same_answer(owned_library, entry):
    purchase = record_purchase(entry)
    key = str(uuid.uuid7())

    first = _refund(owned_library, purchase, key)
    purchase.refresh_from_db()
    again = _refund(owned_library, purchase, key)

    assert again == first


def test_a_second_press_appends_nothing(owned_library, entry):
    purchase = record_purchase(entry)
    _refund(owned_library, purchase, str(uuid.uuid7()))
    purchase.refresh_from_db()

    again = _refund(owned_library, purchase, str(uuid.uuid7()))

    assert again.sequence is None


def test_another_day_on_a_refunded_purchase_is_refused(owned_library, entry):
    purchase = refund_purchase(record_purchase(entry), JULY)

    with pytest.raises(CommandFailed):
        _refund(owned_library, purchase, str(uuid.uuid7()))


def test_the_latest_refund_act_follows_each_act(owned_library, entry):
    purchase = record_purchase(entry)
    assert latest_refund_act(owned_library, purchase.pk) is None

    refund_purchase(purchase, JUNE)
    stated = latest_refund_act(owned_library, purchase.pk)
    restate_purchase(
        owned_library.user,
        purchase,
        refund=ActStatement(JULY, ""),
        correlation_id=uuid.uuid7(),
    )
    corrected = latest_refund_act(owned_library, purchase.pk)
    void_refund(purchase)
    voided = latest_refund_act(owned_library, purchase.pk)

    assert [act.event_type for act in (stated, corrected, voided)] == [
        PURCHASE_REFUND_EVENTS.stated.event_type,
        PURCHASE_REFUND_EVENTS.corrected.event_type,
        PURCHASE_REFUND_EVENTS.voided.event_type,
    ]
