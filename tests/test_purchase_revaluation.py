"""A purchase write requests a run; the recovery finds what it lost."""

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import Mock

import pytest
from django.db import DatabaseError
from entries import record_entry
from purchases import record_purchase as record_purchase_event
from purchases import remove_purchase as remove_purchase_event
from purchases import request_run

from games import conversion, tasks
from games.commands.calendar import SetCalendarDayZone
from games.commands.endpoint import ActStatement
from games.commands.purchase import StatedPrice
from games.events.dispatch import dispatch
from games.events.purchase import (
    PURCHASE_ENTRY_CHANGED,
    PURCHASE_KIND_CHANGED,
    PURCHASE_NAME_CHANGED,
    PURCHASE_NOTE_CHANGED,
    PURCHASE_REFUND_EVENTS,
    PURCHASE_REMOVED,
    VALUATION_EVENTS,
)
from games.events.vocabulary import DEFAULT_EVENT_TYPES
from games.models import Game, Purchase, PurchaseConversionState
from games.reads.purchases import stale_purchases
from games.writes import revaluation
from games.writes.answers import CommandFailed
from games.writes.libraryentry import remove_entry, restore_entry
from games.writes.playergame import remove_from_library, restore_to_library
from games.writes.purchase import (
    PurchaseDraft,
    record_purchase,
    remove_purchase,
    restate_purchase,
    restore_purchase,
)
from timetracker.temporal import TemporalValue

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.untracked_games]


@pytest.fixture(autouse=True)
def queued(monkeypatch):
    queue = Mock()
    monkeypatch.setattr(conversion, "async_task", queue)
    return queue


@pytest.fixture
def graph(owned_library, stated_graph):
    return stated_graph(Game(name="Tunic", library=owned_library), owned_library)


@pytest.fixture
def entry(owned_library, graph):
    return record_entry(owned_library, graph.release)


@pytest.fixture
def purchase(entry):
    return record_purchase_event(entry, amount=Decimal("5.00"), currency="EUR")


def _requested(library) -> tuple[int, str]:
    state = PurchaseConversionState.objects.get(library=library)
    return state.requested_version, state.requested_currency


def _draft(copy) -> PurchaseDraft:
    return PurchaseDraft(
        copy=copy,
        kind="game",
        name="",
        price=StatedPrice(Decimal("5.00"), "EUR"),
        note="",
        purchased=ActStatement(None, ""),
    )


def test_a_creation_requests_at_the_row_s_target(owned_library, entry):
    PurchaseConversionState.objects.filter(library=owned_library).update(
        requested_currency="USD"
    )
    version, _ = _requested(owned_library)

    record_purchase(owned_library.user, _draft(entry.pk), correlation_id=uuid.uuid7())

    assert _requested(owned_library) == (version + 1, "USD")


@pytest.mark.parametrize(
    "statement",
    [
        {"price": StatedPrice(Decimal("6.00"), "EUR")},
        {"purchased": ActStatement(TemporalValue.parse("2021-03-01"), "")},
    ],
    ids=["price", "day"],
)
def test_a_restatement_that_moves_the_value_requests(
    owned_library, purchase, statement
):
    version, _ = _requested(owned_library)

    restate_purchase(
        owned_library.user, purchase, correlation_id=uuid.uuid7(), **statement
    )

    assert _requested(owned_library)[0] == version + 1


@pytest.mark.parametrize(
    "statement",
    [
        {"name": "Deluxe"},
        {"note": "gift"},
        {"kind": "upgrade"},
        {"refund": ActStatement(TemporalValue.parse("2030-01-01"), "")},
    ],
    ids=["name", "note", "kind", "refund"],
)
def test_a_description_requests_nothing(owned_library, purchase, statement):
    version, _ = _requested(owned_library)

    restate_purchase(
        owned_library.user, purchase, correlation_id=uuid.uuid7(), **statement
    )

    assert _requested(owned_library)[0] == version


def test_a_move_to_another_copy_requests_nothing(owned_library, graph, purchase):
    sibling = record_entry(owned_library, graph.release)
    version, _ = _requested(owned_library)

    restate_purchase(
        owned_library.user, purchase, entry_id=sibling.pk, correlation_id=uuid.uuid7()
    )

    assert _requested(owned_library)[0] == version


def test_a_lost_request_still_answers_the_write(
    owned_library, entry, monkeypatch, capture_games_logger
):
    def lose(library):
        raise DatabaseError("connection lost")

    monkeypatch.setattr(revaluation, "request_revaluation", lose)

    with capture_games_logger() as caplog:
        recorded = record_purchase(
            owned_library.user, _draft(entry.pk), correlation_id=uuid.uuid7()
        )

    assert Purchase.objects.filter(pk=recorded.purchase_id).exists()
    assert "Revaluation request lost" in caplog.text


def test_a_missing_state_row_is_a_defect(owned_library, entry):
    PurchaseConversionState.objects.filter(library=owned_library).delete()

    with pytest.raises(PurchaseConversionState.DoesNotExist):
        record_purchase(
            owned_library.user, _draft(entry.pk), correlation_id=uuid.uuid7()
        )


def test_a_repeated_creation_requests_nothing(owned_library, entry):
    key = str(uuid.uuid7())
    record_purchase(
        owned_library.user,
        _draft(entry.pk),
        correlation_id=uuid.uuid7(),
        idempotency_key=key,
    )
    version, _ = _requested(owned_library)

    record_purchase(
        owned_library.user,
        _draft(entry.pk),
        correlation_id=uuid.uuid7(),
        idempotency_key=key,
    )

    assert _requested(owned_library)[0] == version


def test_an_unchanged_or_refused_restatement_requests_nothing(owned_library, purchase):
    version, _ = _requested(owned_library)

    restate_purchase(
        owned_library.user,
        purchase,
        price=StatedPrice(Decimal("5.00"), "EUR"),
        correlation_id=uuid.uuid7(),
    )
    with pytest.raises(CommandFailed):
        restate_purchase(
            owned_library.user,
            purchase,
            price=StatedPrice(Decimal("5.001"), "EUR"),
            correlation_id=uuid.uuid7(),
        )

    assert _requested(owned_library)[0] == version


def test_a_restore_requests_and_a_removal_does_not(owned_library, purchase):
    version, _ = _requested(owned_library)

    remove_purchase(owned_library.user, purchase, correlation_id=uuid.uuid7())
    assert _requested(owned_library)[0] == version

    restore_purchase(owned_library.user, purchase, correlation_id=uuid.uuid7())
    assert _requested(owned_library)[0] == version + 1


def test_a_copy_restore_requests_for_its_purchases(owned_library, entry, purchase):
    version, _ = _requested(owned_library)

    remove_entry(owned_library.user, entry, correlation_id=uuid.uuid7())
    assert _requested(owned_library)[0] == version

    entry.refresh_from_db()
    restore_entry(owned_library.user, entry, correlation_id=uuid.uuid7())
    assert _requested(owned_library)[0] == version + 1


# The recovery


def _at_rest(library) -> int:
    state = PurchaseConversionState.objects.get(library=library)
    PurchaseConversionState.objects.filter(library=library).update(
        published_version=state.requested_version,
        status=PurchaseConversionState.Status.COMPLETE,
    )
    return state.requested_version


def test_the_recovery_requests_a_stale_library_at_rest(owned_library, purchase, queued):
    PurchaseConversionState.objects.filter(library=owned_library).update(
        requested_currency="USD"
    )
    version = _at_rest(owned_library)

    tasks.recover_library_price_conversions()

    assert _requested(owned_library) == (version + 1, "USD")
    queued.assert_called_once_with(
        "games.tasks.convert_library_prices", str(owned_library.pk), version + 1
    )


def test_the_recovery_requests_a_restored_game(owned_library, graph, purchase):
    remove_from_library(owned_library.user, graph.game, correlation_id=uuid.uuid7())
    version = _at_rest(owned_library)
    tasks.recover_library_price_conversions()
    assert _requested(owned_library)[0] == version

    restore_to_library(owned_library.user, graph.game, correlation_id=uuid.uuid7())
    tasks.recover_library_price_conversions()

    assert _requested(owned_library)[0] == version + 1


def test_one_failing_library_leaves_the_others(
    owned_library, purchase, django_user_model, stated_graph, monkeypatch
):
    other = django_user_model.objects.create_user(username="other").library
    record_purchase_event(
        record_entry(
            other, stated_graph(Game(name="Hades", library=other), other).release
        )
    )
    _at_rest(owned_library)
    version = _at_rest(other)
    real = tasks.request_revaluation

    def fail_for_the_owner(library):
        if library.pk == owned_library.pk:
            raise DatabaseError("lock timeout")
        return real(library)

    monkeypatch.setattr(tasks, "request_revaluation", fail_for_the_owner)

    tasks.recover_library_price_conversions()

    assert _requested(other)[0] == version + 1


def test_the_recovery_leaves_a_current_library(owned_library, entry, queued):
    record_purchase_event(entry, amount=None)
    version = _at_rest(owned_library)

    tasks.recover_library_price_conversions()

    assert _requested(owned_library)[0] == version
    queued.assert_not_called()


def test_the_recovery_enqueues_a_pending_library_once(
    owned_library, purchase, monkeypatch
):
    PurchaseConversionState.objects.filter(library=owned_library).update(
        requested_version=3,
        published_version=2,
        status=PurchaseConversionState.Status.PENDING,
    )
    enqueued = Mock()
    monkeypatch.setattr(tasks, "async_task", enqueued)

    tasks.recover_library_price_conversions()

    enqueued.assert_called_once_with(
        "games.tasks.convert_library_prices", str(owned_library.pk), 3
    )
    assert _requested(owned_library)[0] == 3


def test_the_recovery_skips_a_removed_purchase(owned_library, purchase):
    remove_purchase_event(purchase)
    version = _at_rest(owned_library)

    tasks.recover_library_price_conversions()

    assert _requested(owned_library)[0] == version


#: Purchase events that move no valuation input.
NOT_VALUATION_EVENTS = {
    PURCHASE_KIND_CHANGED.event_type,
    PURCHASE_NAME_CHANGED.event_type,
    PURCHASE_NOTE_CHANGED.event_type,
    PURCHASE_ENTRY_CHANGED.event_type,
    PURCHASE_REMOVED.event_type,
    *PURCHASE_REFUND_EVENTS.family,
}


def test_every_purchase_event_is_classified():
    purchase_events = DEFAULT_EVENT_TYPES.event_types_for("purchase")

    assert VALUATION_EVENTS.isdisjoint(NOT_VALUATION_EVENTS)
    assert VALUATION_EVENTS | NOT_VALUATION_EVENTS == purchase_events


def test_a_zone_change_stales_the_recorded_year(owned_library, entry):
    purchase = record_purchase_event(entry, amount=Decimal(5), currency="CZK")
    Purchase.objects.filter(pk=purchase.pk).update(
        purchase_recorded_at=datetime(2025, 12, 31, 12, tzinfo=UTC)
    )
    _at_rest(owned_library)
    request_run(owned_library)
    tasks.convert_library_prices(str(owned_library.pk), _requested(owned_library)[0])
    version = _requested(owned_library)[0]
    assert not stale_purchases(owned_library).exists()

    dispatch(
        SetCalendarDayZone(day_zone="Pacific/Kiritimati"),
        actor=owned_library.user,
        library=owned_library,
        idempotency_key=str(uuid.uuid7()),
    )
    tasks.recover_library_price_conversions()

    assert [row.pk for row in stale_purchases(owned_library)] == [purchase.pk]
    assert _requested(owned_library)[0] == version + 1


def test_one_failing_enqueue_leaves_the_others(
    owned_library, django_user_model, monkeypatch
):
    other = django_user_model.objects.create_user(username="other").library
    for library in (owned_library, other):
        PurchaseConversionState.objects.filter(library=library).update(
            requested_version=2,
            published_version=1,
            status=PurchaseConversionState.Status.PENDING,
        )

    enqueued: list[str] = []

    def fail_for_the_owner(name, library_id, version):
        if library_id == str(owned_library.pk):
            raise RuntimeError("broker down")
        enqueued.append(library_id)

    monkeypatch.setattr(tasks, "async_task", fail_for_the_owner)

    tasks.recover_library_price_conversions()

    assert enqueued == [str(other.pk)]


def test_the_recovery_skips_a_blank_target(owned_library, purchase, queued):
    PurchaseConversionState.objects.filter(library=owned_library).update(
        requested_currency="", published_currency=""
    )
    version = _at_rest(owned_library)

    tasks.recover_library_price_conversions()

    assert _requested(owned_library)[0] == version
    queued.assert_not_called()
