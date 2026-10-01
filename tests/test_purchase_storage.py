"""The purchase events, table, reads and writes."""

import uuid
from decimal import Decimal
from typing import get_args

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone
from entries import record_entry
from purchases import record_purchase, remove_purchase

from games.commands.endpoint import ActStatement
from games.commands.libraryentry import EntryStatement
from games.commands.purchase import TOO_PRECISE_AMOUNT, StatedPrice
from games.events.purchase import (
    PURCHASE_CREATED,
    PURCHASE_PRICE_CHANGED,
    PurchaseKindValue,
    amount_text,
)
from games.events.references import Reference
from games.events.vocabulary import DEFAULT_EVENT_TYPES, PayloadInvalid
from games.models import (
    Game,
    LibraryEntry,
    LibraryEvent,
    PlayerGame,
    Purchase,
    PurchaseKind,
)
from games.reads.purchases import library_purchases, readable_purchases
from games.removal import remove
from games.writes.answers import CommandFailed
from games.writes.purchase import PurchaseDraft, restate_purchase
from games.writes.purchase import record_purchase as record_purchase_write
from timetracker.temporal import TemporalValue

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.untracked_games]


def test_the_payload_spells_every_stored_kind():
    assert set(get_args(PurchaseKindValue.__value__)) == set(PurchaseKind.values)


def _created_payload(**changes) -> dict:
    return {
        "entry": Reference(
            kind="libraryentry", id=str(uuid.uuid7()), label="Tunic", detail=""
        ),
        "kind": "game",
        "name": "",
        "price": {"amount": "12.50", "currency": "EUR"},
        "note": "",
        "purchase_note": "",
    } | changes


@pytest.mark.parametrize(
    "changes",
    (
        {"price": {"amount": "12.5", "currency": "EUR"}},
        {"price": {"amount": "-1.00", "currency": "EUR"}},
        {"price": {"amount": "1E+2", "currency": "EUR"}},
        {"price": {"amount": "12345678901.00", "currency": "EUR"}},
        {"price": {"amount": 12.5, "currency": "EUR"}},
        {"price": {"amount": "12.50", "currency": "eur"}},
        {"price": {"amount": "12.50", "currency": ""}},
        {"price": {"amount": "12.50"}},
        {"name": "x" * 256},
        {"kind": "loot_box"},
        {"colour": "black"},
    ),
)
def test_the_created_payload_refuses_another_spelling(changes):
    with pytest.raises(PayloadInvalid):
        DEFAULT_EVENT_TYPES.validate(
            PURCHASE_CREATED.event_type, _created_payload(**changes)
        )


def test_an_unknown_price_travels_as_null():
    payload = {"price": None}

    assert (
        DEFAULT_EVENT_TYPES.validate(PURCHASE_PRICE_CHANGED.event_type, payload)
        == payload
    )


@pytest.mark.parametrize(
    ("amount", "text"),
    ((Decimal("1E+2"), "100.00"), (Decimal("12.5"), "12.50")),
)
def test_amount_text_writes_two_places(amount, text):
    assert amount_text(amount) == text


# --- the table ------------------------------------------------------------


@pytest.fixture
def entry(owned_library, stated_graph):
    graph = stated_graph(Game(name="Tunic", library=owned_library), owned_library)
    return record_entry(owned_library, graph.release)


@pytest.mark.parametrize(
    "columns",
    (
        {"kind": "loot_box"},
        {"amount": Decimal("-1.00")},
        {"amount": Decimal("1.00"), "currency": ""},
        {"amount": Decimal("1.00"), "currency": "eur"},
        {"amount": None, "currency": "EUR"},
    ),
)
def test_a_check_refuses_a_row_no_command_states(entry, columns):
    stated = {
        "id": uuid.uuid7(),
        "library": entry.library,
        "entry": entry,
        "kind": "game",
        "amount": Decimal("1.00"),
        "currency": "EUR",
        "purchase_recorded_at": timezone.now(),
        "created_at": timezone.now(),
    } | columns

    with pytest.raises(IntegrityError), transaction.atomic():
        Purchase._base_manager.create(**stated)


# --- the reads ------------------------------------------------------------


@pytest.mark.parametrize(
    "hide",
    (
        lambda purchase: remove_purchase(purchase),
        lambda purchase: LibraryEntry.objects.filter(pk=purchase.entry_id).update(
            removed_at=timezone.now()
        ),
        lambda purchase: PlayerGame.objects.filter(
            pk=purchase.entry.player_game_id
        ).update(removed_at=timezone.now()),
        lambda purchase: remove(purchase.entry.release),
        lambda purchase: remove(purchase.entry.release.edition),
        lambda purchase: remove(purchase.entry.release.edition.game),
    ),
)
def test_each_mark_hides_a_purchase(owned_library, entry, hide):
    purchase = record_purchase(entry)
    assert list(readable_purchases(owned_library)) == [purchase]

    hide(purchase)

    assert not library_purchases(owned_library).exists()


def test_another_librarys_purchase_is_never_listed(
    owned_library, django_user_model, entry
):
    record_purchase(entry)
    second = django_user_model.objects.create_user(username="second").library

    assert not library_purchases(second).exists()


@pytest.mark.parametrize("drift", ("entry", "player_game"))
def test_a_drifted_purchase_is_never_listed(
    owned_library, django_user_model, stated_graph, entry, drift
):
    purchase = record_purchase(entry)
    second = django_user_model.objects.create_user(username="drift").library
    theirs = record_entry(
        second, stated_graph(Game(name="Hades", library=second), second).release
    )
    if drift == "entry":
        Purchase.objects.filter(pk=purchase.pk).update(entry=theirs)
    else:
        LibraryEntry.objects.filter(pk=entry.pk).update(player_game=theirs.player_game)

    assert not library_purchases(owned_library).exists()


# --- the writes -----------------------------------------------------------


def _draft(copy, **changes) -> PurchaseDraft:
    return PurchaseDraft(
        copy=copy,
        kind="game",
        name="",
        price=StatedPrice(Decimal("5.00"), "EUR"),
        note="",
        purchased=ActStatement(None, ""),
    )._replace(**changes)


def test_record_answers_what_the_dispatch_created(owned_library, stated_graph):
    graph = stated_graph(Game(name="Hades", library=owned_library), owned_library)
    copy = EntryStatement(release_id=graph.release.pk, access="owned", format="digital")

    recorded = record_purchase_write(
        owned_library.user, _draft(copy), correlation_id=uuid.uuid7()
    )

    purchase = Purchase.objects.get(pk=recorded.purchase_id)
    assert purchase.entry_id == recorded.entry_id
    assert (recorded.created_the_entry, recorded.tracked_the_game) == (True, True)


def test_record_of_a_new_copy_on_a_tracked_game_tracks_nothing(owned_library, entry):
    copy = EntryStatement(
        release_id=entry.release_id, access="owned", format="physical"
    )

    recorded = record_purchase_write(
        owned_library.user, _draft(copy), correlation_id=uuid.uuid7()
    )

    assert (recorded.created_the_entry, recorded.tracked_the_game) == (True, False)


def test_record_on_a_held_copy_creates_nothing_else(owned_library, entry):
    recorded = record_purchase_write(
        owned_library.user, _draft(entry.pk), correlation_id=uuid.uuid7()
    )

    assert recorded.entry_id == entry.pk
    assert (recorded.created_the_entry, recorded.tracked_the_game) == (False, False)


def test_a_refused_price_is_an_answer(owned_library, entry):
    with pytest.raises(CommandFailed) as failed:
        record_purchase_write(
            owned_library.user,
            _draft(entry.pk, price=StatedPrice(Decimal("1.234"), "EUR")),
            correlation_id=uuid.uuid7(),
        )

    assert (failed.value.message, failed.value.status_code) == (TOO_PRECISE_AMOUNT, 409)


def test_restate_describes_then_corrects_under_one_correlation(owned_library, entry):
    purchase = record_purchase(entry)
    correlation_id = uuid.uuid7()
    day = TemporalValue.parse("2021-05")

    changed = restate_purchase(
        owned_library.user,
        purchase,
        name="Deluxe",
        purchased=ActStatement(day, ""),
        correlation_id=correlation_id,
    )

    assert changed
    assert list(
        LibraryEvent.objects.filter(correlation_id=correlation_id)
        .order_by("sequence")
        .values_list("event_type", flat=True)
    ) == ["library.purchase.name_changed", "library.purchase.purchase_corrected"]
    assert not restate_purchase(
        owned_library.user, purchase, name="Deluxe", correlation_id=uuid.uuid7()
    )
