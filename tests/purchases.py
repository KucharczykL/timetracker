"""Test purchases via append_command; dispatch cannot nest."""

import uuid
from decimal import Decimal

from django.db import transaction

from games.commands.endpoint import ActStatement
from games.commands.purchase import (
    RecordPurchase,
    RefundPurchase,
    RemovePurchase,
    RestorePurchase,
    StatedPrice,
)
from games.events.dispatch import Command, CommandResult, append_command
from games.events.purchase import PURCHASE_CREATED, PurchaseKindValue
from games.models import (
    LibraryEntry,
    LibraryEvent,
    Purchase,
    PurchaseConversionState,
    UserLibrary,
)
from timetracker.temporal import TemporalValue


def _state(library: UserLibrary, command: Command) -> CommandResult:
    with transaction.atomic():
        return append_command(
            command,
            actor=library.user,
            library=library,
            idempotency_key=str(uuid.uuid7()),
            correlation_id=uuid.uuid7(),
        )


def record_purchase(
    entry: LibraryEntry,
    *,
    kind: PurchaseKindValue = "game",
    name: str = "",
    amount: Decimal | None = Decimal("19.99"),
    currency: str = "EUR",
    note: str = "",
    purchased: TemporalValue | None = None,
    purchase_note: str = "",
) -> Purchase:
    """A live purchase of a held copy."""
    result = _state(
        entry.library,
        RecordPurchase(
            kind=kind,
            copy=entry.pk,
            name=name,
            price=StatedPrice(amount, currency if amount is not None else ""),
            note=note,
            purchased=ActStatement(purchased, purchase_note),
        ),
    )
    assert result.sequences is not None
    created = LibraryEvent.objects.get(
        stream_id=result.stream_id,
        sequence=result.sequences.last,
        event_type=PURCHASE_CREATED.event_type,
    )
    return Purchase.objects.get(pk=created.aggregate_id)


def remove_purchase(purchase: Purchase) -> Purchase:
    _state(purchase.library, RemovePurchase(purchase_id=purchase.pk))
    purchase.refresh_from_db()
    return purchase


def restore_purchase(purchase: Purchase) -> Purchase:
    _state(purchase.library, RestorePurchase(purchase_id=purchase.pk))
    purchase.refresh_from_db()
    return purchase


def request_run(library: UserLibrary, currency: str = "CZK") -> int:
    """Request a conversion version without enqueueing it."""
    state = PurchaseConversionState.objects.get(library=library)
    state.requested_version += 1
    state.requested_currency = currency
    state.status = PurchaseConversionState.Status.PENDING
    state.save()
    return state.requested_version


def refund_purchase(
    purchase: Purchase, refunded: TemporalValue | None, note: str = ""
) -> Purchase:
    _state(
        purchase.library,
        RefundPurchase(purchase_id=purchase.pk, statement=ActStatement(refunded, note)),
    )
    purchase.refresh_from_db()
    return purchase
