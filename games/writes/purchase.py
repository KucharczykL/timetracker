"""Purchase writes; refusals become answers."""

import uuid
from typing import NamedTuple, assert_never

from django.contrib.auth.models import User

from games.commands.endpoint import ActStatement, certainly_reversed
from games.commands.libraryentry import EntryStatement
from games.commands.purchase import (
    PURCHASE_AFTER_REFUND,
    REFUND_BEFORE_ACQUISITION,
    REFUND_BEFORE_PURCHASE,
    CorrectPurchaseRefund,
    DescribePurchase,
    RecordPurchase,
    RefundPurchase,
    RemovePurchase,
    RestorePurchase,
    StatedPrice,
    VoidPurchaseRefund,
    refund_ends_the_copy,
)
from games.endpoints import PURCHASE_REFUND
from games.events.dispatch import (
    Command,
    CommandOutcome,
    CommandRejected,
    CommandResult,
    dispatch,
)
from games.events.idempotency import IdempotencyKey
from games.events.libraryentry import LIBRARYENTRY_CREATED
from games.events.playergame import PLAYERGAME_CREATED
from games.events.purchase import PURCHASE_CREATED, PurchaseKindValue
from games.models import LibraryEntry, Purchase
from games.reads.endpoints import stated
from games.reads.entries import library_entries
from games.reads.events import dispatched_events
from games.reads.purchases import coupled_end
from games.writes.answers import SubjectNoun, answered
from games.writes.endpoint import (
    KEEP,
    Act,
    Correct,
    EndpointMove,
    Keep,
    Nothing,
    Void,
    endpoint_move,
)

SUBJECT: SubjectNoun = "purchase"


class PurchaseDraft(NamedTuple):
    """What a creation states."""

    #: A held copy's key, or a new copy.
    copy: uuid.UUID | EntryStatement
    kind: PurchaseKindValue
    name: str
    price: StatedPrice
    note: str
    purchased: ActStatement


class RecordedPurchase(NamedTuple):
    """What a creation answers."""

    purchase_id: uuid.UUID
    entry_id: uuid.UUID
    #: The dispatch recorded a new copy.
    created_the_entry: bool
    #: The dispatch tracked an untracked game.
    tracked_the_game: bool
    #: A repeated key answered the first dispatch.
    replayed: bool


def _dispatch(
    command: Command,
    *,
    actor: User,
    correlation_id: uuid.UUID,
    idempotency_key: IdempotencyKey | None = None,
) -> CommandResult:
    return dispatch(
        command,
        actor=actor,
        library=actor.library,
        #: Caller's key else fresh; blank refused.
        idempotency_key=(
            str(uuid.uuid7()) if idempotency_key is None else idempotency_key
        ),
        correlation_id=correlation_id,
    )


def record_purchase(
    actor: User,
    draft: PurchaseDraft,
    *,
    correlation_id: uuid.UUID,
    idempotency_key: IdempotencyKey | None = None,
) -> RecordedPurchase:
    """State a purchase; answer its ids."""
    with answered(SUBJECT):
        result = _dispatch(
            RecordPurchase(
                copy=draft.copy,
                kind=draft.kind,
                name=draft.name,
                price=draft.price,
                note=draft.note,
                purchased=draft.purchased,
            ),
            actor=actor,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )
    event_by_type = {event.event_type: event for event in dispatched_events(result)}
    created = event_by_type.get(PURCHASE_CREATED.event_type)
    if created is None:
        raise RuntimeError(
            f"Dispatch {result.stream_id} {result.sequences} appended no "
            f"{PURCHASE_CREATED.event_type}."
        )
    return RecordedPurchase(
        purchase_id=created.aggregate_id,
        entry_id=uuid.UUID(created.payload["entry"]["id"]),
        created_the_entry=LIBRARYENTRY_CREATED.event_type in event_by_type,
        tracked_the_game=PLAYERGAME_CREATED.event_type in event_by_type,
        replayed=result.outcome is CommandOutcome.REPLAYED,
    )


def restate_purchase(
    actor: User,
    purchase: Purchase,
    *,
    kind: PurchaseKindValue | None = None,
    name: str | None = None,
    price: StatedPrice | None = None,
    note: str | None = None,
    entry_id: uuid.UUID | None = None,
    purchased: ActStatement | None = None,
    refund: ActStatement | None | Keep = KEEP,
    correlation_id: uuid.UUID,
) -> bool:
    """Describe and refund; answers whether appended."""
    move: EndpointMove[ActStatement] = (
        Nothing()
        if isinstance(refund, Keep)
        else endpoint_move(stated(purchase, PURCHASE_REFUND), refund)
    )
    with answered(SUBJECT):
        _refuse_a_reversed_draft(
            actor,
            purchase,
            kind=kind,
            entry_id=entry_id,
            purchased=purchased,
            move=move,
        )
    described = any(
        fact is not None for fact in (kind, name, price, note, entry_id, purchased)
    )
    description = (
        DescribePurchase(
            purchase_id=purchase.pk,
            kind=kind,
            name=name,
            price=price,
            note=note,
            entry_id=entry_id,
            purchased=purchased,
        )
        if described
        else None
    )
    refund_command = (
        None if isinstance(refund, Keep) else _refund_command(purchase, move)
    )
    ordered = (
        (description, refund_command)
        if _description_first(purchase, move)
        else (refund_command, description)
    )
    changed = False
    for command in ordered:
        if command is None:
            continue
        with answered(SUBJECT):
            result = _dispatch(command, actor=actor, correlation_id=correlation_id)
        changed = changed or result.outcome is CommandOutcome.APPENDED
    return changed


def _refund_command(purchase: Purchase, move: EndpointMove[ActStatement]) -> Command:
    """The act; a void always dispatches.

    The command decides under the lock, so a refund a racer
    stated is voided rather than dropped.
    """
    match move:
        case Act(statement):
            return RefundPurchase(purchase_id=purchase.pk, statement=statement)
        case Correct(statement):
            return CorrectPurchaseRefund(purchase_id=purchase.pk, statement=statement)
        case Void() | Nothing():
            return VoidPurchaseRefund(purchase_id=purchase.pk)
        case unhandled:
            assert_never(unhandled)


def _description_first(purchase: Purchase, move: EndpointMove[ActStatement]) -> bool:
    """Whether the description must land first.

    A first refund reads the kind and copy the description
    states, and no refund stands for a day to contradict. A
    correction goes first unless its day falls before the
    purchase day the row holds; a void always goes first.
    """
    match move:
        case Act():
            return True
        case Correct(statement):
            return certainly_reversed(earlier=purchase.purchased, later=statement.when)
    return False


def _refuse_a_reversed_draft(
    actor: User,
    purchase: Purchase,
    *,
    kind: PurchaseKindValue | None,
    entry_id: uuid.UUID | None,
    purchased: ActStatement | None,
    move: EndpointMove[ActStatement],
) -> None:
    """Refuse up front: a committed act stays."""
    match move:
        case Act(statement) | Correct(statement):
            refunded, refund_is_new = statement.when, True
        case Nothing() if stated(purchase, PURCHASE_REFUND) is not None:
            refunded, refund_is_new = purchase.refunded, False
        case _:
            return
    purchase_day = purchase.purchased if purchased is None else purchased.when
    if (refund_is_new or purchased is not None) and certainly_reversed(
        earlier=purchase_day, later=refunded
    ):
        if refund_is_new and purchased is not None:
            sentence = (
                "This purchase was refunded before it was bought. Check the days."
            )
        elif refund_is_new:
            sentence = REFUND_BEFORE_PURCHASE
        else:
            sentence = PURCHASE_AFTER_REFUND
        raise CommandRejected(
            f"The statement about purchase {purchase.pk} refunds it before it "
            "was bought.",
            sentence=sentence,
        )
    copy = _copy_the_refund_ends(
        actor, purchase, kind=kind, entry_id=entry_id, move=move
    )
    if copy is not None and certainly_reversed(earlier=copy.acquired, later=refunded):
        raise CommandRejected(
            f"The statement about purchase {purchase.pk} ends entry {copy.pk} "
            "before it was acquired.",
            sentence=REFUND_BEFORE_ACQUISITION,
        )


def _copy_the_refund_ends(
    actor: User,
    purchase: Purchase,
    *,
    kind: PurchaseKindValue | None,
    entry_id: uuid.UUID | None,
    move: EndpointMove[ActStatement],
) -> LibraryEntry | None:
    """The copy whose end the refund appends."""
    match move:
        case Act():
            copy = (
                purchase.entry
                if entry_id is None
                else library_entries(actor.library).filter(pk=entry_id).first()
            )
            #: An absent copy is the command's 404.
            if copy is None:
                return None
            final_kind = purchase.kind if kind is None else kind
            return copy if refund_ends_the_copy(final_kind, copy) else None
        case Correct(statement) if statement.when != purchase.refunded:
            owned = coupled_end(actor.library, purchase) is not None
            return purchase.entry if owned else None
    return None


def remove_purchase(
    actor: User,
    purchase: Purchase,
    *,
    correlation_id: uuid.UUID,
    idempotency_key: IdempotencyKey | None = None,
) -> CommandResult:
    """Take a purchase out of the library."""
    with answered(SUBJECT):
        return _dispatch(
            RemovePurchase(purchase_id=purchase.pk),
            actor=actor,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )


def restore_purchase(
    actor: User,
    purchase: Purchase,
    *,
    correlation_id: uuid.UUID,
    idempotency_key: IdempotencyKey | None = None,
) -> CommandResult:
    """Put a removed purchase back."""
    with answered(SUBJECT):
        return _dispatch(
            RestorePurchase(purchase_id=purchase.pk),
            actor=actor,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )
