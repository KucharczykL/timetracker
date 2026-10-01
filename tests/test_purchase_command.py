"""Stating a purchase of a copy."""

import uuid
from decimal import Decimal

import pytest
from entries import record_entry, remove_entry
from purchases import record_purchase, remove_purchase, restore_purchase

from games.commands.endpoint import ActStatement
from games.commands.libraryentry import EntryStatement, RemoveEntry
from games.commands.playergame import RemovePlayerGame
from games.commands.purchase import (
    AMOUNT_WITHOUT_CURRENCY,
    CURRENCY_WITHOUT_AMOUNT,
    ENTRY_OF_ANOTHER_GAME,
    ENTRY_REMOVED,
    ONE_COPY,
    PLAYER_GAME_REMOVED,
    PURCHASE_REMOVED,
    SIGNED_AMOUNT,
    TOO_LARGE_AMOUNT,
    TOO_PRECISE_AMOUNT,
    UNKNOWN_KIND,
    CorrectPurchaseDay,
    DescribePurchase,
    RecordPurchase,
    RemovePurchase,
    RestorePurchase,
    StatedPrice,
)
from games.events.dispatch import (
    CommandOutcome,
    CommandRejected,
    CommandResult,
    RowNotHeld,
    RowUnreadable,
    dispatch,
)
from games.models import Game, LibraryEntry, LibraryEvent, Purchase
from timetracker.temporal import TemporalValue

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.untracked_games]

MAY = TemporalValue.parse("2021-05")
JUNE = TemporalValue.parse("2021-06-03")


@pytest.fixture
def second_library(django_user_model):
    return django_user_model.objects.create_user(username="second-owner").library


@pytest.fixture
def graph(owned_library, stated_graph):
    return stated_graph(Game(name="Tunic", library=owned_library), owned_library)


@pytest.fixture
def entry(owned_library, graph):
    return record_entry(owned_library, graph.release)


def _dispatch(library, command, key: str | None = None) -> CommandResult:
    return dispatch(
        command,
        actor=library.user,
        library=library,
        idempotency_key=str(uuid.uuid7()) if key is None else key,
    )


def _refused(library, command) -> CommandRejected:
    with pytest.raises(CommandRejected) as refused:
        _dispatch(library, command)
    return refused.value


def _event_types(row) -> list[str]:
    return list(
        LibraryEvent.objects.filter(aggregate_id=row.pk)
        .order_by("sequence")
        .values_list("event_type", flat=True)
    )


def _batch_types(result: CommandResult) -> list[str]:
    assert result.sequences is not None
    return list(
        LibraryEvent.objects.filter(
            stream_id=result.stream_id,
            sequence__range=(result.sequences.first, result.sequences.last),
        )
        .order_by("sequence")
        .values_list("event_type", flat=True)
    )


def _record(entry, **facts) -> RecordPurchase:
    return RecordPurchase(kind="game", entry_id=entry.pk, **facts)


# --- recording ------------------------------------------------------------


def test_recording_on_a_held_copy_writes_one_event(owned_library, entry):
    result = _dispatch(
        owned_library,
        _record(
            entry,
            name=" Deluxe ",
            price=StatedPrice(Decimal("12.5"), " eur "),
            note=" gift ",
            purchased=ActStatement(MAY, "store"),
        ),
    )

    assert _batch_types(result) == ["library.purchase.created"]
    purchase = Purchase.objects.get(library=owned_library)
    created = LibraryEvent.objects.get(aggregate_id=purchase.pk)
    assert created.payload["amount"] == "12.50"
    assert created.payload["currency"] == "EUR"
    assert created.payload["entry"]["id"] == str(entry.pk)
    assert (purchase.entry, purchase.kind, purchase.name, purchase.note) == (
        entry,
        "game",
        "Deluxe",
        "gift",
    )
    assert (purchase.amount, purchase.currency) == (Decimal("12.50"), "EUR")
    assert (purchase.purchased, purchase.purchase_note) == (MAY, "store")
    assert purchase.created_at == purchase.purchase_recorded_at == created.recorded_at


def test_an_unknown_price_is_null_and_a_free_one_zero(owned_library, entry):
    unknown = record_purchase(entry, amount=None)
    free = record_purchase(entry, amount=Decimal(0))

    assert (unknown.amount, unknown.currency) == (None, "")
    assert (free.amount, free.currency) == (Decimal("0.00"), "EUR")


def test_a_new_copy_on_a_tracked_game_is_recorded_in_the_same_dispatch(
    owned_library, graph, entry
):
    result = _dispatch(
        owned_library,
        RecordPurchase(
            kind="game",
            new_entry=EntryStatement(graph.release.pk, "owned", "physical"),
        ),
    )

    assert _batch_types(result) == [
        "library.libraryentry.created",
        "library.purchase.created",
    ]
    purchase = Purchase.objects.get(library=owned_library)
    assert purchase.entry != entry
    assert purchase.entry.format == "physical"


def test_a_new_copy_on_an_untracked_game_tracks_it(owned_library, graph):
    result = _dispatch(
        owned_library,
        RecordPurchase(
            kind="game", new_entry=EntryStatement(graph.release.pk, "owned", "digital")
        ),
    )

    assert _batch_types(result) == [
        "library.playergame.created",
        "library.playthrough.created",
        "library.libraryentry.created",
        "library.purchase.created",
    ]
    purchase = Purchase.objects.get(library=owned_library)
    assert purchase.entry.player_game.game == graph.game


@pytest.mark.parametrize("both", (True, False))
def test_one_copy_is_named(owned_library, graph, entry, both):
    statement = EntryStatement(graph.release.pk, "owned", "digital")
    command = RecordPurchase(
        kind="game",
        entry_id=entry.pk if both else None,
        new_entry=statement if both else None,
    )

    assert _refused(owned_library, command).sentence == ONE_COPY


def test_a_removed_copy_is_refused(owned_library, entry):
    remove_entry(entry)

    assert _refused(owned_library, _record(entry)).sentence == ENTRY_REMOVED


def test_a_copy_under_a_removed_game_is_refused(owned_library, entry):
    _dispatch(owned_library, RemovePlayerGame(game_id=entry.player_game.game_id))

    assert _refused(owned_library, _record(entry)).sentence == PLAYER_GAME_REMOVED


def test_another_librarys_copy_is_absent(second_library, entry):
    with pytest.raises(RowNotHeld):
        _dispatch(second_library, _record(entry))


def test_an_unknown_kind_is_refused(owned_library, entry):
    command = RecordPurchase(kind="loot_box", entry_id=entry.pk)

    assert _refused(owned_library, command).sentence == UNKNOWN_KIND


@pytest.mark.parametrize(
    ("price", "sentence"),
    (
        (StatedPrice(Decimal("-1.00"), "EUR"), SIGNED_AMOUNT),
        (StatedPrice(Decimal("-0.00"), "EUR"), SIGNED_AMOUNT),
        (StatedPrice(Decimal("12.345"), "EUR"), TOO_PRECISE_AMOUNT),
        (StatedPrice(Decimal("10000000000.00"), "EUR"), TOO_LARGE_AMOUNT),
        (StatedPrice(Decimal("12.00"), ""), AMOUNT_WITHOUT_CURRENCY),
        (StatedPrice(Decimal("12.00"), "EURO"), AMOUNT_WITHOUT_CURRENCY),
        (StatedPrice(None, "EUR"), CURRENCY_WITHOUT_AMOUNT),
    ),
)
def test_a_price_rule_is_refused(owned_library, entry, price, sentence):
    assert _refused(owned_library, _record(entry, price=price)).sentence == sentence
    assert not Purchase.objects.exists()


def test_trailing_zeros_and_the_largest_amount_are_admitted(owned_library, entry):
    _dispatch(owned_library, _record(entry, price=StatedPrice(Decimal("1.500"), "EUR")))
    _dispatch(
        owned_library,
        _record(entry, price=StatedPrice(Decimal("9999999999.99"), "EUR")),
    )

    assert sorted(Purchase.objects.values_list("amount", flat=True)) == [
        Decimal("1.50"),
        Decimal("9999999999.99"),
    ]


def test_a_repeat_under_one_key_appends_once(owned_library, entry):
    first = _dispatch(owned_library, _record(entry), key="once")
    again = _dispatch(owned_library, _record(entry), key="once")

    assert first.outcome is CommandOutcome.APPENDED
    assert again.outcome is CommandOutcome.REPLAYED
    assert Purchase.objects.count() == 1


# --- describing -----------------------------------------------------------


def test_each_differing_fact_is_one_event(owned_library, entry):
    purchase = record_purchase(entry)

    _dispatch(
        owned_library,
        DescribePurchase(
            purchase_id=purchase.pk,
            kind="upgrade",
            name="Deluxe",
            price=StatedPrice(None, ""),
            note="later",
        ),
    )

    assert _event_types(purchase)[1:] == [
        "library.purchase.kind_changed",
        "library.purchase.name_changed",
        "library.purchase.amount_changed",
        "library.purchase.note_changed",
    ]
    purchase.refresh_from_db()
    assert (purchase.kind, purchase.name, purchase.note) == (
        "upgrade",
        "Deluxe",
        "later",
    )
    assert (purchase.amount, purchase.currency) == (None, "")


def test_the_same_price_in_another_spelling_is_unchanged(owned_library, entry):
    purchase = record_purchase(entry, amount=Decimal("19.99"), currency="EUR")

    result = _dispatch(
        owned_library,
        DescribePurchase(
            purchase_id=purchase.pk, price=StatedPrice(Decimal("19.990"), "eur")
        ),
    )

    assert result.outcome is CommandOutcome.UNCHANGED


def test_a_copy_of_the_same_game_moves_the_purchase(owned_library, graph, entry):
    purchase = record_purchase(entry)
    other = record_entry(owned_library, graph.release, format="physical")

    _dispatch(
        owned_library, DescribePurchase(purchase_id=purchase.pk, entry_id=other.pk)
    )

    purchase.refresh_from_db()
    assert purchase.entry == other
    assert _event_types(purchase)[-1] == "library.purchase.entry_changed"


def test_a_copy_of_another_game_is_refused(owned_library, stated_graph, entry):
    purchase = record_purchase(entry)
    elsewhere = stated_graph(Game(name="Hades", library=owned_library), owned_library)
    other = record_entry(owned_library, elsewhere.release)

    refused = _refused(
        owned_library, DescribePurchase(purchase_id=purchase.pk, entry_id=other.pk)
    )

    assert refused.sentence == ENTRY_OF_ANOTHER_GAME


def test_another_librarys_copy_is_absent_on_a_move(
    owned_library, second_library, stated_graph, entry
):
    purchase = record_purchase(entry)
    theirs = stated_graph(Game(name="Hades", library=second_library), second_library)
    their_entry = record_entry(second_library, theirs.release)

    with pytest.raises(RowNotHeld):
        _dispatch(
            owned_library,
            DescribePurchase(purchase_id=purchase.pk, entry_id=their_entry.pk),
        )


def test_a_removed_purchase_answers_unchanged_before_refusing(owned_library, entry):
    purchase = remove_purchase(record_purchase(entry, name="Deluxe"))

    same = _dispatch(
        owned_library, DescribePurchase(purchase_id=purchase.pk, name="Deluxe")
    )
    refused = _refused(
        owned_library, DescribePurchase(purchase_id=purchase.pk, name="Other")
    )

    assert same.outcome is CommandOutcome.UNCHANGED
    assert refused.sentence == PURCHASE_REMOVED


def test_another_librarys_purchase_is_absent(second_library, entry):
    purchase = record_purchase(entry)

    with pytest.raises(RowNotHeld):
        _dispatch(second_library, DescribePurchase(purchase_id=purchase.pk, name="x"))


def test_a_purchase_naming_another_librarys_copy_is_unreadable(
    owned_library, second_library, stated_graph, entry
):
    purchase = record_purchase(entry)
    theirs = stated_graph(Game(name="Hades", library=second_library), second_library)
    their_entry = record_entry(second_library, theirs.release)
    Purchase.objects.filter(pk=purchase.pk).update(entry=their_entry)

    with pytest.raises(RowUnreadable):
        _dispatch(owned_library, DescribePurchase(purchase_id=purchase.pk, name="x"))


# --- the day --------------------------------------------------------------


def test_a_correction_moves_the_day(owned_library, entry):
    purchase = record_purchase(entry, purchased=MAY)

    _dispatch(
        owned_library,
        CorrectPurchaseDay(purchase_id=purchase.pk, statement=ActStatement(JUNE, "n")),
    )
    same = _dispatch(
        owned_library,
        CorrectPurchaseDay(purchase_id=purchase.pk, statement=ActStatement(JUNE, "n")),
    )

    purchase.refresh_from_db()
    assert (purchase.purchased, purchase.purchase_note) == (JUNE, "n")
    assert _event_types(purchase)[-1] == "library.purchase.purchase_corrected"
    assert same.outcome is CommandOutcome.UNCHANGED


def test_a_correction_of_a_removed_purchase_is_refused(owned_library, entry):
    purchase = remove_purchase(record_purchase(entry))

    refused = _refused(
        owned_library,
        CorrectPurchaseDay(purchase_id=purchase.pk, statement=ActStatement(JUNE, "")),
    )

    assert refused.sentence == PURCHASE_REMOVED


# --- removal --------------------------------------------------------------


def test_removal_and_restore_answer_unchanged_on_a_repeat(owned_library, entry):
    purchase = record_purchase(entry)

    assert remove_purchase(purchase).removed_at is not None
    again = _dispatch(owned_library, RemovePurchase(purchase_id=purchase.pk))
    assert restore_purchase(purchase).removed_at is None
    live = _dispatch(owned_library, RestorePurchase(purchase_id=purchase.pk))

    assert again.outcome is live.outcome is CommandOutcome.UNCHANGED


def test_a_restore_under_a_removed_copy_is_refused(owned_library, entry):
    purchase = remove_purchase(record_purchase(entry))
    LibraryEntry.objects.filter(pk=entry.pk).update(removed_at=purchase.removed_at)

    refused = _refused(owned_library, RestorePurchase(purchase_id=purchase.pk))

    assert refused.sentence == ENTRY_REMOVED


def test_a_live_purchase_keeps_its_copy(owned_library, entry):
    purchase = record_purchase(entry)

    refused = _refused(owned_library, RemoveEntry(entry_id=entry.pk))
    remove_purchase(purchase)
    _dispatch(owned_library, RemoveEntry(entry_id=entry.pk))

    assert refused.sentence == "A purchase names this copy. Remove the purchase first."
    entry.refresh_from_db()
    assert entry.removed_at is not None


def test_alive_reads_the_copy_and_the_game(owned_library, entry):
    purchase = record_purchase(entry)
    assert list(Purchase.objects.alive()) == [purchase]

    LibraryEntry.objects.filter(pk=entry.pk).update(removed_at=purchase.created_at)
    assert not Purchase.objects.alive().exists()
