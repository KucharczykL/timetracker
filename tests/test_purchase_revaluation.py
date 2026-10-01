"""A purchase write requests a run; the recovery finds what it lost."""

import uuid
from decimal import Decimal
from unittest.mock import Mock

import pytest
from entries import record_entry
from purchases import record_purchase as record_purchase_event
from purchases import remove_purchase as remove_purchase_event

from games import conversion, tasks
from games.commands.endpoint import ActStatement
from games.commands.purchase import StatedPrice
from games.models import Game, PurchaseConversionState
from games.writes.answers import CommandFailed
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
def entry(owned_library, stated_graph):
    graph = stated_graph(Game(name="Tunic", library=owned_library), owned_library)
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
    [{"name": "Deluxe"}, {"note": "gift"}, {"kind": "upgrade"}],
    ids=["name", "note", "kind"],
)
def test_a_description_requests_nothing(owned_library, purchase, statement):
    version, _ = _requested(owned_library)

    restate_purchase(
        owned_library.user, purchase, correlation_id=uuid.uuid7(), **statement
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


# The recovery


def _at_rest(library) -> int:
    state = PurchaseConversionState.objects.get(library=library)
    PurchaseConversionState.objects.filter(library=library).update(
        published_version=state.requested_version,
        status=PurchaseConversionState.Status.COMPLETE,
    )
    return state.requested_version


def test_the_recovery_requests_a_stale_library_at_rest(owned_library, purchase):
    version = _at_rest(owned_library)

    tasks.recover_library_price_conversions()

    assert _requested(owned_library)[0] == version + 1


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
