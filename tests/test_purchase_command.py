"""Stating a purchase of a copy."""

import uuid
from decimal import Decimal
from typing import Any, cast

import pytest
from entries import record_entry, remove_entry, second_release
from purchases import record_purchase, remove_purchase, restore_purchase

from games.commands.endpoint import ActStatement
from games.commands.libraryentry import EntryStatement, RemoveEntry
from games.commands.playergame import RemovePlayerGame, RestorePlayerGame
from games.commands.playersession import UNSTORABLE_NOTE
from games.commands.purchase import (
    AMOUNT_WITHOUT_CURRENCY,
    CURRENCY_WITHOUT_AMOUNT,
    ENTRY_OF_ANOTHER_GAME,
    ENTRY_REMOVED,
    LONG_NAME,
    NOT_AN_AMOUNT,
    PLAYER_GAME_REMOVED,
    PURCHASE_REMOVED,
    RELEASE_REMOVED,
    SIGNED_AMOUNT,
    TOO_LARGE_AMOUNT,
    TOO_PRECISE_AMOUNT,
    UNKNOWN_KIND,
    UNSTORABLE_NAME,
    DescribePurchase,
    RecordPurchase,
    RemovePurchase,
    RestorePurchase,
    StatedPrice,
    check_price,
    purchase_creation_events,
)
from games.events.dispatch import (
    CommandContext,
    CommandOutcome,
    CommandRejected,
    CommandResult,
    RowNotHeld,
    RowUnreadable,
    dispatch,
)
from games.models import Game, LibraryEntry, LibraryEvent, Purchase
from games.reads.referrers import PURCHASE_RECORDED
from games.removal import remove
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


@pytest.fixture
def other_game_entry(owned_library, stated_graph):
    """A copy of another game, same library."""
    elsewhere = stated_graph(Game(name="Hades", library=owned_library), owned_library)
    return record_entry(owned_library, elsewhere.release)


@pytest.fixture
def their_graph(second_library, stated_graph):
    return stated_graph(Game(name="Hades", library=second_library), second_library)


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
    return RecordPurchase(copy=entry.pk, kind="game", **facts)


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
    assert created.payload["price"] == {"amount": "12.50", "currency": "EUR"}
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
            copy=EntryStatement(
                release_id=graph.release.pk, access="owned", format="physical"
            ),
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
            kind="game",
            copy=EntryStatement(
                release_id=graph.release.pk, access="owned", format="digital"
            ),
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
    command = RecordPurchase(copy=entry.pk, kind=cast(Any, "loot_box"))

    assert _refused(owned_library, command).sentence == UNKNOWN_KIND


@pytest.mark.parametrize(
    ("price", "sentence"),
    (
        (StatedPrice(Decimal("-1.00"), "EUR"), SIGNED_AMOUNT),
        (StatedPrice(Decimal("-0.00"), "EUR"), SIGNED_AMOUNT),
        (StatedPrice(Decimal("12.345"), "EUR"), TOO_PRECISE_AMOUNT),
        (StatedPrice(Decimal("10000000000.00"), "EUR"), TOO_LARGE_AMOUNT),
        (StatedPrice(Decimal("1E+30"), "EUR"), TOO_LARGE_AMOUNT),
        (
            StatedPrice(Decimal("123456789012345678901234567890.00"), "EUR"),
            TOO_LARGE_AMOUNT,
        ),
        (StatedPrice(Decimal("12.00"), ""), AMOUNT_WITHOUT_CURRENCY),
        (StatedPrice(Decimal("12.00"), "EURO"), AMOUNT_WITHOUT_CURRENCY),
        (StatedPrice(None, "EUR"), CURRENCY_WITHOUT_AMOUNT),
    ),
)
def test_a_price_rule_is_refused(owned_library, entry, price, sentence):
    assert _refused(owned_library, _record(entry, price=price)).sentence == sentence
    assert not Purchase.objects.exists()


def test_an_infinite_amount_is_no_number():
    with pytest.raises(CommandRejected) as refused:
        check_price(StatedPrice(Decimal("Infinity"), "EUR"))

    assert refused.value.sentence == NOT_AN_AMOUNT


def test_a_long_name_is_refused_on_record_and_describe(owned_library, entry):
    long_name = "x" * 256
    purchase = record_purchase(entry)

    recorded = _refused(owned_library, _record(entry, name=long_name))
    described = _refused(
        owned_library, DescribePurchase(purchase_id=purchase.pk, name=long_name)
    )

    assert recorded.sentence == described.sentence == LONG_NAME


@pytest.mark.parametrize(
    ("facts", "sentence"),
    (
        ({"name": "a\x00b"}, UNSTORABLE_NAME),
        ({"name": "a\ud800b"}, UNSTORABLE_NAME),
        ({"note": "a\x00b"}, UNSTORABLE_NOTE),
        ({"purchased": ActStatement(None, "a\x00b")}, UNSTORABLE_NOTE),
    ),
)
def test_text_no_record_can_store_is_refused(owned_library, entry, facts, sentence):
    purchase = record_purchase(entry)

    recorded = _refused(owned_library, _record(entry, **facts))
    described = _refused(
        owned_library, DescribePurchase(purchase_id=purchase.pk, **facts)
    )

    assert recorded.sentence == described.sentence == sentence


def test_a_new_copys_note_is_checked_too(owned_library, graph):
    command = RecordPurchase(
        copy=EntryStatement(
            release_id=graph.release.pk,
            access="owned",
            format="digital",
            note="a\x00b",
        ),
        kind="game",
    )

    assert _refused(owned_library, command).sentence == UNSTORABLE_NOTE


def test_a_copy_under_a_removed_release_is_refused(owned_library, graph, entry):
    remove(graph.release)

    assert _refused(owned_library, _record(entry)).sentence == RELEASE_REMOVED


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
        "library.purchase.price_changed",
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


def test_a_move_onto_a_removed_copy_is_refused(owned_library, graph, entry):
    purchase = record_purchase(entry)
    other = remove_entry(record_entry(owned_library, graph.release))

    refused = _refused(
        owned_library, DescribePurchase(purchase_id=purchase.pk, entry_id=other.pk)
    )

    assert refused.sentence == ENTRY_REMOVED
    purchase.refresh_from_db()
    assert purchase.entry == entry


def test_a_removed_purchase_names_itself_before_the_copy(
    owned_library, entry, other_game_entry
):
    purchase = remove_purchase(record_purchase(entry))

    refused = _refused(
        owned_library,
        DescribePurchase(purchase_id=purchase.pk, entry_id=other_game_entry.pk),
    )

    assert refused.sentence == PURCHASE_REMOVED


def test_a_description_and_a_day_are_one_dispatch(owned_library, entry):
    purchase = record_purchase(entry)

    result = _dispatch(
        owned_library,
        DescribePurchase(
            purchase_id=purchase.pk, name="Deluxe", purchased=ActStatement(JUNE, "")
        ),
    )

    assert _batch_types(result) == [
        "library.purchase.name_changed",
        "library.purchase.purchase_corrected",
    ]


def test_a_copy_of_another_game_is_refused(owned_library, entry, other_game_entry):
    purchase = record_purchase(entry)

    refused = _refused(
        owned_library,
        DescribePurchase(purchase_id=purchase.pk, entry_id=other_game_entry.pk),
    )

    assert refused.sentence == ENTRY_OF_ANOTHER_GAME


def test_another_librarys_copy_is_absent_on_a_move(
    owned_library, second_library, their_graph, entry
):
    purchase = record_purchase(entry)
    their_entry = record_entry(second_library, their_graph.release)

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


def test_a_purchase_whose_copy_drifted_is_unreadable(owned_library, their_graph, entry):
    purchase = record_purchase(entry)
    LibraryEntry.objects.filter(pk=entry.pk).update(release=their_graph.release)

    with pytest.raises(RowUnreadable):
        _dispatch(owned_library, DescribePurchase(purchase_id=purchase.pk, name="x"))


def test_a_purchase_naming_another_librarys_copy_is_unreadable(
    owned_library, second_library, their_graph, entry
):
    purchase = record_purchase(entry)
    their_entry = record_entry(second_library, their_graph.release)
    Purchase.objects.filter(pk=purchase.pk).update(entry=their_entry)

    with pytest.raises(RowUnreadable):
        _dispatch(owned_library, DescribePurchase(purchase_id=purchase.pk, name="x"))


# --- the day --------------------------------------------------------------


def test_a_day_correction_moves_the_day_not_the_marker(owned_library, entry):
    purchase = record_purchase(entry, purchased=MAY)

    _dispatch(
        owned_library,
        DescribePurchase(purchase_id=purchase.pk, purchased=ActStatement(JUNE, "n")),
    )
    same = _dispatch(
        owned_library,
        DescribePurchase(purchase_id=purchase.pk, purchased=ActStatement(JUNE, "n")),
    )

    recorded_at = purchase.purchase_recorded_at
    purchase.refresh_from_db()
    assert (purchase.purchased, purchase.purchase_note) == (JUNE, "n")
    assert purchase.purchase_recorded_at == recorded_at
    assert _event_types(purchase)[-1] == "library.purchase.purchase_corrected"
    assert same.outcome is CommandOutcome.UNCHANGED


def test_a_correction_of_a_removed_purchase_is_refused(owned_library, entry):
    purchase = remove_purchase(record_purchase(entry))

    refused = _refused(
        owned_library,
        DescribePurchase(purchase_id=purchase.pk, purchased=ActStatement(JUNE, "")),
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
    remove_entry(entry)

    refused = _refused(owned_library, RestorePurchase(purchase_id=purchase.pk))

    assert refused.sentence == ENTRY_REMOVED


def test_a_restore_under_a_removed_release_is_refused(owned_library, graph, entry):
    purchase = remove_purchase(record_purchase(entry))
    remove(graph.release)

    refused = _refused(owned_library, RestorePurchase(purchase_id=purchase.pk))

    assert refused.sentence == RELEASE_REMOVED


def test_a_purchase_leaves_under_a_removed_release(owned_library, graph, entry):
    purchase = record_purchase(entry)
    remove(graph.release)

    result = _dispatch(owned_library, RemovePurchase(purchase_id=purchase.pk))

    assert result.outcome is CommandOutcome.APPENDED


def test_a_restore_under_a_removed_game_is_refused(owned_library, entry):
    purchase = remove_purchase(record_purchase(entry))
    _dispatch(owned_library, RemovePlayerGame(game_id=entry.player_game.game_id))

    refused = _refused(owned_library, RestorePurchase(purchase_id=purchase.pk))

    assert refused.sentence == PLAYER_GAME_REMOVED


def test_a_hidden_current_copy_refuses_before_the_target(owned_library, graph, entry):
    purchase = record_purchase(entry)
    sibling = record_entry(owned_library, second_release(owned_library, graph.release))
    remove(graph.release)

    refused = _refused(
        owned_library, DescribePurchase(purchase_id=purchase.pk, entry_id=sibling.pk)
    )

    assert refused.sentence == RELEASE_REMOVED
    purchase.refresh_from_db()
    assert purchase.entry == entry


def test_a_removed_game_holds_its_purchases_still(owned_library, entry):
    purchase = record_purchase(entry)
    game_id = entry.player_game.game_id
    _dispatch(owned_library, RemovePlayerGame(game_id=game_id))

    removal = _refused(owned_library, RemovePurchase(purchase_id=purchase.pk))
    correction = _refused(
        owned_library,
        DescribePurchase(purchase_id=purchase.pk, purchased=ActStatement(JUNE, "")),
    )
    _dispatch(owned_library, RestorePlayerGame(game_id=game_id))
    again = _dispatch(owned_library, RemovePurchase(purchase_id=purchase.pk))

    assert removal.sentence == correction.sentence == PLAYER_GAME_REMOVED
    assert again.outcome is CommandOutcome.APPENDED


def test_a_live_purchase_keeps_its_copy(owned_library, entry):
    purchase = record_purchase(entry)

    refused = _refused(owned_library, RemoveEntry(entry_id=entry.pk))
    remove_purchase(purchase)
    _dispatch(owned_library, RemoveEntry(entry_id=entry.pk))

    assert refused.sentence == PURCHASE_RECORDED
    entry.refresh_from_db()
    assert entry.removed_at is not None


@pytest.mark.parametrize("mark", ("copy", "game"))
def test_alive_reads_the_copy_and_the_game(owned_library, entry, mark):
    purchase = record_purchase(entry)
    assert list(Purchase.objects.alive()) == [purchase]

    if mark == "copy":
        #: A live purchase blocks RemoveEntry.
        LibraryEntry.objects.filter(pk=entry.pk).update(removed_at=purchase.created_at)
    else:
        _dispatch(owned_library, RemovePlayerGame(game_id=entry.player_game.game_id))

    assert not Purchase.objects.alive().exists()


def test_creation_events_take_a_given_key_or_mint_one(owned_library, entry):
    context = CommandContext(library=owned_library, actor=owned_library.user)
    key = uuid.uuid7()
    given = purchase_creation_events(
        context, copy=entry.pk, kind="game", purchase_id=key
    )
    minted = purchase_creation_events(context, copy=entry.pk, kind="game")
    assert given[-1].aggregate_id == key
    assert minted[-1].aggregate_id not in {key, None}


def test_creation_events_refuse_what_the_command_refuses(owned_library, entry):
    context = CommandContext(library=owned_library, actor=owned_library.user)
    with pytest.raises(CommandRejected) as refusal:
        purchase_creation_events(
            context,
            copy=entry.pk,
            kind="game",
            price=StatedPrice(Decimal("1.234"), "EUR"),
        )
    assert refusal.value.sentence == TOO_PRECISE_AMOUNT
    remove_entry(entry)
    with pytest.raises(CommandRejected) as refusal:
        purchase_creation_events(context, copy=entry.pk, kind="game")
    assert refusal.value.sentence == ENTRY_REMOVED
