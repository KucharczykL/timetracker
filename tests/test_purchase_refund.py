"""A purchase is refunded, and its copy ends."""

import uuid
from decimal import Decimal

import pytest
from django.db import transaction
from entries import end_entry_access, record_entry, second_release
from purchases import record_purchase, remove_purchase

from games.commands.endpoint import ActStatement, WayActStatement
from games.commands.libraryentry import (
    CorrectEntryAccessEnd,
    CorrectEntryAcquisition,
    DescribeEntry,
    ResumeEntryAccess,
    VoidEntryAccessEnd,
)
from games.commands.playergame import RemovePlayerGame
from games.commands.playersession import UNSTORABLE_NOTE
from games.commands.purchase import (
    ENTRY_OF_ANOTHER_GAME,
    KIND_UNDER_A_REFUND,
    MOVE_A_REFUNDED_PURCHASE,
    PLAYER_GAME_REMOVED,
    PURCHASE_AFTER_REFUND,
    PURCHASE_REMOVED,
    REFUND_BEFORE_ACQUISITION,
    REFUND_BEFORE_PURCHASE,
    REFUNDED_BEFORE_BOUGHT,
    RELEASE_REMOVED,
    TAKE_REFUND_BACK,
    TOO_PRECISE_AMOUNT,
    CorrectPurchaseRefund,
    DescribePurchase,
    RefundPurchase,
    StatedPrice,
    VoidPurchaseRefund,
)
from games.end_ways import EndWay
from games.events.append import lock_stream
from games.events.dispatch import (
    CommandOutcome,
    CommandRejected,
    CommandResult,
    RowNotHeld,
    dispatch,
)
from games.events.libraryentry import ENTRY_ACCESS_END_EVENTS
from games.events.purchase import PURCHASE_REFUND_EVENTS
from games.events.vocabulary import NewEvent
from games.models import Game, LibraryEvent
from games.reads.purchases import refund_owns_the_end
from games.removal import remove
from games.writes.answers import CommandFailed
from games.writes.purchase import CopyEnd, RestatedPurchase, restate_purchase
from timetracker.temporal import TemporalValue

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.untracked_games]

MARCH = TemporalValue.parse("2021-03-01")
APRIL = TemporalValue.parse("2021-04-01")
MAY = TemporalValue.parse("2021-05-10")
JUNE = TemporalValue.parse("2021-06-03")
JULY = TemporalValue.parse("2021-07-01")
AUGUST = TemporalValue.parse("2021-08-01")
SEPTEMBER = TemporalValue.parse("2021-09-01")


@pytest.fixture
def second_library(django_user_model):
    return django_user_model.objects.create_user(username="second-owner").library


@pytest.fixture
def graph(owned_library, stated_graph):
    return stated_graph(Game(name="Tunic", library=owned_library), owned_library)


@pytest.fixture
def entry(owned_library, graph):
    return record_entry(owned_library, graph.release, acquired=MAY)


@pytest.fixture
def purchase(entry):
    return record_purchase(entry, purchased=MAY)


def _dispatch(library, command) -> CommandResult:
    return dispatch(
        command, actor=library.user, library=library, idempotency_key=str(uuid.uuid7())
    )


def _refused(library, command) -> CommandRejected:
    with pytest.raises(CommandRejected) as refused:
        _dispatch(library, command)
    return refused.value


def _batch(result: CommandResult) -> list[tuple[str, uuid.UUID]]:
    assert result.sequences is not None
    return list(
        LibraryEvent.objects.filter(
            stream_id=result.stream_id,
            sequence__range=(result.sequences.first, result.sequences.last),
        )
        .order_by("sequence")
        .values_list("event_type", "aggregate_id")
    )


def _refund(purchase, when=JUNE, note="") -> RefundPurchase:
    return RefundPurchase(purchase_id=purchase.pk, statement=ActStatement(when, note))


def _correct(purchase, when=JULY, note="") -> CorrectPurchaseRefund:
    return CorrectPurchaseRefund(
        purchase_id=purchase.pk, statement=ActStatement(when, note)
    )


def _void(purchase) -> VoidPurchaseRefund:
    return VoidPurchaseRefund(purchase_id=purchase.pk)


def _fresh(row):
    row.refresh_from_db()
    return row


# --- the statement --------------------------------------------------------


def test_a_game_refund_ends_its_owned_copy_in_one_dispatch(
    owned_library, entry, purchase
):
    result = _dispatch(owned_library, _refund(purchase, note=" store "))

    assert _batch(result) == [
        ("library.purchase.refunded", purchase.pk),
        ("library.libraryentry.access_ended", entry.pk),
    ]
    purchase = _fresh(purchase)
    assert (purchase.refunded, purchase.refund_note) == (JUNE, "store")
    assert purchase.refund_recorded_at is not None
    entry = _fresh(entry)
    assert (entry.access_ended, entry.access_end_way, entry.access_end_note) == (
        JUNE,
        "refunded",
        "",
    )
    assert refund_owns_the_end(owned_library, purchase)


@pytest.mark.parametrize("kind", ("season_pass", "battle_pass", "upgrade"))
def test_an_addon_refund_leaves_the_copy_held(owned_library, entry, kind):
    addon = record_purchase(entry, kind=kind, purchased=MAY)

    result = _dispatch(owned_library, _refund(addon))

    assert _batch(result) == [("library.purchase.refunded", addon.pk)]
    assert _fresh(entry).access_end_recorded_at is None


def test_a_borrowed_copy_is_not_ended(owned_library, graph):
    borrowed = record_entry(owned_library, graph.release, access="borrowed")
    purchase = record_purchase(borrowed)

    result = _dispatch(owned_library, _refund(purchase))

    assert _batch(result) == [("library.purchase.refunded", purchase.pk)]
    assert not refund_owns_the_end(owned_library, _fresh(purchase))


def test_an_ended_copy_keeps_its_end(owned_library, entry, purchase):
    end_entry_access(entry, way=EndWay.SOLD, ended=JULY)

    result = _dispatch(owned_library, _refund(purchase))

    assert _batch(result) == [("library.purchase.refunded", purchase.pk)]
    entry = _fresh(entry)
    assert (entry.access_ended, entry.access_end_way) == (JULY, "sold")


def test_a_repeat_is_unchanged_and_another_refused(owned_library, purchase):
    _dispatch(owned_library, _refund(purchase))

    repeat = _dispatch(owned_library, _refund(purchase))
    assert repeat.outcome is CommandOutcome.UNCHANGED
    _refused(owned_library, _refund(purchase, when=JULY))


def test_a_refund_before_the_purchase_day_is_refused(owned_library, purchase):
    refused = _refused(owned_library, _refund(purchase, when=APRIL))

    assert refused.sentence == REFUND_BEFORE_PURCHASE
    assert not LibraryEvent.objects.filter(aggregate_id=purchase.pk).exclude(
        event_type="library.purchase.created"
    )


def test_a_refund_before_the_acquisition_is_refused_where_the_copy_ends(
    owned_library, graph
):
    owned = record_entry(owned_library, graph.release, acquired=JULY)
    purchase = record_purchase(owned)

    refused = _refused(owned_library, _refund(purchase, when=JUNE))

    assert refused.sentence == REFUND_BEFORE_ACQUISITION


def test_a_refund_before_the_acquisition_passes_where_nothing_ends(
    owned_library, graph
):
    borrowed = record_entry(
        owned_library, graph.release, access="borrowed", acquired=JULY
    )
    purchase = record_purchase(borrowed)

    _dispatch(owned_library, _refund(purchase, when=JUNE))

    assert _fresh(purchase).refunded == JUNE


def test_a_refund_under_a_removed_release_is_refused(owned_library, graph, purchase):
    remove(graph.release)

    assert _refused(owned_library, _refund(purchase)).sentence == RELEASE_REMOVED


def test_a_removed_purchase_is_refused(owned_library, purchase):
    remove_purchase(purchase)

    assert _refused(owned_library, _refund(purchase)).sentence == PURCHASE_REMOVED


def test_another_librarys_purchase_is_absent(second_library, purchase):
    with pytest.raises(RowNotHeld):
        _dispatch(second_library, _refund(purchase))


# --- the correction -------------------------------------------------------


def test_a_correction_moves_the_refunds_end(owned_library, entry, purchase):
    _dispatch(owned_library, _refund(purchase))

    result = _dispatch(owned_library, _correct(purchase, when=JULY, note="late"))

    assert _batch(result) == [
        ("library.purchase.refund_corrected", purchase.pk),
        ("library.libraryentry.access_end_corrected", entry.pk),
    ]
    entry = _fresh(entry)
    assert (entry.access_ended, entry.access_end_way, entry.access_end_note) == (
        JULY,
        "refunded",
        "",
    )
    assert refund_owns_the_end(owned_library, _fresh(purchase))


def test_a_note_only_correction_keeps_the_end_owned(owned_library, entry, purchase):
    _dispatch(owned_library, _refund(purchase))

    result = _dispatch(owned_library, _correct(purchase, when=JUNE, note="receipt"))

    assert _batch(result) == [("library.purchase.refund_corrected", purchase.pk)]
    assert refund_owns_the_end(owned_library, _fresh(purchase))
    _dispatch(owned_library, _void(purchase))
    assert _fresh(entry).access_end_recorded_at is None


def test_a_correction_after_a_hand_correction_leaves_the_end(
    owned_library, entry, purchase
):
    _dispatch(owned_library, _refund(purchase))
    _dispatch(
        owned_library,
        CorrectEntryAccessEnd(
            entry_id=entry.pk,
            statement=WayActStatement(JUNE, EndWay.REFUNDED, "by hand"),
        ),
    )

    result = _dispatch(owned_library, _correct(purchase, when=JULY))

    assert _batch(result) == [("library.purchase.refund_corrected", purchase.pk)]
    assert _fresh(entry).access_ended == JUNE


def test_a_corrected_refund_before_the_purchase_is_refused(owned_library, purchase):
    _dispatch(owned_library, _refund(purchase))

    refused = _refused(owned_library, _correct(purchase, when=APRIL))

    assert refused.sentence == REFUND_BEFORE_PURCHASE


def test_a_corrected_refund_before_the_acquisition_is_refused_where_owned(
    owned_library, entry, purchase
):
    _dispatch(owned_library, _refund(purchase))
    _dispatch(
        owned_library, DescribePurchase(purchase.pk, purchased=ActStatement(None))
    )

    refused = _refused(owned_library, _correct(purchase, when=APRIL))

    assert refused.sentence == REFUND_BEFORE_ACQUISITION


# --- the void -------------------------------------------------------------


def test_a_void_takes_the_refunds_end_back(owned_library, entry, purchase):
    _dispatch(owned_library, _refund(purchase))

    result = _dispatch(owned_library, _void(purchase))

    assert _batch(result) == [
        ("library.purchase.refund_voided", purchase.pk),
        ("library.libraryentry.access_end_voided", entry.pk),
    ]
    purchase = _fresh(purchase)
    assert (purchase.refunded, purchase.refund_recorded_at) == (None, None)
    assert _fresh(entry).access_end_recorded_at is None


def test_a_void_with_no_refund_is_unchanged(owned_library, purchase):
    assert _dispatch(owned_library, _void(purchase)).outcome is (
        CommandOutcome.UNCHANGED
    )


def test_a_void_leaves_a_resumed_copy(owned_library, entry, purchase):
    _dispatch(owned_library, _refund(purchase))
    _dispatch(
        owned_library,
        ResumeEntryAccess(entry_id=entry.pk, statement=ActStatement(JULY)),
    )
    end_entry_access(entry, way=EndWay.SOLD, ended=JULY)

    result = _dispatch(owned_library, _void(purchase))

    assert _batch(result) == [("library.purchase.refund_voided", purchase.pk)]
    assert _fresh(entry).access_end_way == "sold"


def test_a_void_under_a_removed_release_passes(owned_library, graph, entry, purchase):
    _dispatch(owned_library, _refund(purchase))
    remove(graph.release)

    _dispatch(owned_library, _void(purchase))

    assert _fresh(entry).access_end_recorded_at is None


def test_a_second_refund_couples_afresh(owned_library, entry, purchase):
    _dispatch(owned_library, _refund(purchase))
    _dispatch(owned_library, _void(purchase))

    result = _dispatch(owned_library, _refund(purchase, when=JULY))

    assert [event_type for event_type, _ in _batch(result)] == [
        "library.purchase.refunded",
        "library.libraryentry.access_ended",
    ]
    assert _fresh(entry).access_ended == JULY


def test_an_access_change_keeps_the_end_the_refunds(owned_library, entry, purchase):
    _dispatch(owned_library, _refund(purchase))
    _dispatch(owned_library, DescribeEntry(entry_id=entry.pk, access="borrowed"))

    _dispatch(owned_library, _void(purchase))

    assert _fresh(entry).access_end_recorded_at is None


# --- the purchase around it -----------------------------------------------


def test_a_refunded_purchase_does_not_move(owned_library, graph, purchase):
    elsewhere = record_entry(
        owned_library, second_release(owned_library, graph.release)
    )
    _dispatch(owned_library, _refund(purchase))

    refused = _refused(
        owned_library, DescribePurchase(purchase.pk, entry_id=elsewhere.pk)
    )

    assert refused.sentence == MOVE_A_REFUNDED_PURCHASE


def test_a_refunded_purchase_keeps_its_kind(owned_library, purchase):
    _dispatch(owned_library, _refund(purchase))

    refused = _refused(owned_library, DescribePurchase(purchase.pk, kind="upgrade"))

    assert refused.sentence == KIND_UNDER_A_REFUND


def test_a_kind_changes_beside_the_refunds_void(owned_library, entry, purchase):
    _dispatch(owned_library, _refund(purchase))

    _dispatch(
        owned_library,
        DescribePurchase(purchase.pk, kind="upgrade", refund=TAKE_REFUND_BACK),
    )

    assert _fresh(purchase).kind == "upgrade"
    assert _fresh(entry).access_end_recorded_at is None


def test_a_refunded_purchase_restates_its_own_kind(owned_library, purchase):
    _dispatch(owned_library, _refund(purchase))

    result = _dispatch(owned_library, DescribePurchase(purchase.pk, kind="game"))

    assert result.outcome is CommandOutcome.UNCHANGED


def test_a_kind_change_beside_a_refund_correction_is_refused(owned_library, purchase):
    _dispatch(owned_library, _refund(purchase))

    refused = _refused(
        owned_library,
        DescribePurchase(purchase.pk, kind="upgrade", refund=ActStatement(JULY)),
    )

    assert refused.sentence == KIND_UNDER_A_REFUND


def test_a_kind_changes_once_the_refund_is_void(owned_library, purchase):
    _dispatch(owned_library, _refund(purchase))
    _dispatch(owned_library, _void(purchase))

    _dispatch(owned_library, DescribePurchase(purchase.pk, kind="upgrade"))

    assert _fresh(purchase).kind == "upgrade"


def test_a_pass_becoming_a_game_leaves_a_stated_end(owned_library, entry):
    season_pass = record_purchase(entry, kind="season_pass", purchased=MAY)
    end_entry_access(entry, way=EndWay.SOLD, ended=JULY)
    _dispatch(owned_library, _refund(season_pass))

    _dispatch(
        owned_library,
        DescribePurchase(season_pass.pk, kind="game", refund=TAKE_REFUND_BACK),
    )

    assert _fresh(season_pass).kind == "game"
    assert _fresh(entry).access_end_way == "sold"


def test_a_purchase_day_after_the_refund_is_refused(owned_library, purchase):
    _dispatch(owned_library, _refund(purchase))

    refused = _refused(
        owned_library, DescribePurchase(purchase.pk, purchased=ActStatement(JULY))
    )

    assert refused.sentence == PURCHASE_AFTER_REFUND


def test_removing_a_refunded_purchase_leaves_the_end(owned_library, entry, purchase):
    _dispatch(owned_library, _refund(purchase))

    remove_purchase(purchase)

    assert _fresh(purchase).removed_at is not None
    assert _fresh(entry).access_end_way == "refunded"


# --- one PATCH -------------------------------------------------------------


def _restate(purchase, **facts) -> RestatedPurchase:
    return restate_purchase(
        purchase.library.user,
        _fresh(purchase),
        correlation_id=uuid.uuid7(),
        **facts,
    )


def _library_event_count(purchase) -> int:
    return LibraryEvent.objects.filter(library=purchase.library).count()


def test_both_days_forward_land(owned_library, entry, purchase):
    _dispatch(owned_library, _refund(purchase))

    assert _restate(
        purchase,
        purchased=ActStatement(AUGUST),
        refund=ActStatement(SEPTEMBER),
    )

    purchase = _fresh(purchase)
    assert (purchase.purchased, purchase.refunded) == (AUGUST, SEPTEMBER)
    assert _fresh(entry).access_ended == SEPTEMBER


def test_both_days_back_land(owned_library, entry, purchase):
    _dispatch(owned_library, _refund(purchase))
    _dispatch(
        owned_library,
        CorrectEntryAcquisition(entry_id=entry.pk, statement=ActStatement(None)),
    )

    assert _restate(purchase, purchased=ActStatement(MARCH), refund=ActStatement(APRIL))

    purchase = _fresh(purchase)
    assert (purchase.purchased, purchase.refunded) == (MARCH, APRIL)
    assert _fresh(entry).access_ended == APRIL


def test_a_first_refund_reads_the_stated_kind(owned_library, entry, purchase):
    _restate(purchase, kind="season_pass", refund=ActStatement(JUNE))

    assert _fresh(purchase).refunded == JUNE
    assert _fresh(entry).access_end_recorded_at is None


def test_a_first_refund_ends_the_copy_it_moves_to(owned_library, graph, purchase):
    elsewhere = record_entry(
        owned_library, second_release(owned_library, graph.release)
    )

    _restate(purchase, entry_id=elsewhere.pk, refund=ActStatement(JUNE))

    assert _fresh(elsewhere).access_end_way == "refunded"
    assert _fresh(purchase.entry).access_end_recorded_at is None


def test_a_void_lets_the_purchase_move(owned_library, graph, entry, purchase):
    elsewhere = record_entry(
        owned_library, second_release(owned_library, graph.release)
    )
    _dispatch(owned_library, _refund(purchase))

    _restate(purchase, entry_id=elsewhere.pk, refund=None)

    assert _fresh(purchase).entry_id == elsewhere.pk
    assert _fresh(entry).access_end_recorded_at is None


def test_a_reversed_body_appends_nothing(owned_library, purchase):
    before = _library_event_count(purchase)

    with pytest.raises(CommandFailed) as refused:
        _restate(purchase, name="Deluxe", refund=ActStatement(APRIL))

    assert refused.value.message == REFUND_BEFORE_PURCHASE
    assert _library_event_count(purchase) == before


def test_a_purchase_day_past_the_standing_refund_appends_nothing(
    owned_library, purchase
):
    _dispatch(owned_library, _refund(purchase))
    before = _library_event_count(purchase)

    with pytest.raises(CommandFailed) as refused:
        _restate(purchase, name="Deluxe", purchased=ActStatement(JULY))

    assert refused.value.message == PURCHASE_AFTER_REFUND
    assert _library_event_count(purchase) == before


def test_a_refund_before_the_target_copys_acquisition_appends_nothing(
    owned_library, graph, purchase
):
    elsewhere = record_entry(
        owned_library, second_release(owned_library, graph.release), acquired=JULY
    )
    before = _library_event_count(purchase)

    with pytest.raises(CommandFailed) as refused:
        _restate(purchase, entry_id=elsewhere.pk, refund=ActStatement(JUNE))

    assert refused.value.message == REFUND_BEFORE_ACQUISITION
    assert _library_event_count(purchase) == before


def test_a_refused_move_keeps_the_refund(owned_library, stated_graph, entry, purchase):
    elsewhere = stated_graph(Game(name="Hades", library=owned_library), owned_library)
    other_game_copy = record_entry(owned_library, elsewhere.release)
    _dispatch(owned_library, _refund(purchase))
    before = _library_event_count(purchase)

    with pytest.raises(CommandFailed) as refused:
        _restate(purchase, entry_id=other_game_copy.pk, refund=None)

    assert refused.value.message == ENTRY_OF_ANOTHER_GAME
    assert _library_event_count(purchase) == before
    assert _fresh(purchase).refunded == JUNE
    assert _fresh(entry).access_end_way == "refunded"


def test_a_refused_price_keeps_the_refund_as_it_was(owned_library, entry, purchase):
    _dispatch(owned_library, _refund(purchase))
    before = _library_event_count(purchase)

    with pytest.raises(CommandFailed) as refused:
        _restate(
            purchase,
            price=StatedPrice(Decimal("1.234"), "EUR"),
            refund=ActStatement(JULY),
        )

    assert refused.value.message == TOO_PRECISE_AMOUNT
    assert _library_event_count(purchase) == before
    assert _fresh(entry).access_ended == JUNE


def test_an_unstorable_refund_note_keeps_the_description(owned_library, purchase):
    before = _library_event_count(purchase)

    with pytest.raises(CommandFailed) as refused:
        _restate(purchase, name="Deluxe", refund=ActStatement(JUNE, "bad\x00"))

    assert refused.value.message == UNSTORABLE_NOTE
    assert _library_event_count(purchase) == before


def test_a_first_refund_onto_another_games_copy_names_the_game(
    owned_library, stated_graph, purchase
):
    elsewhere = stated_graph(Game(name="Hades", library=owned_library), owned_library)
    other_game_copy = record_entry(owned_library, elsewhere.release, acquired=JULY)

    with pytest.raises(CommandFailed) as refused:
        _restate(purchase, entry_id=other_game_copy.pk, refund=ActStatement(JUNE))

    assert refused.value.message == ENTRY_OF_ANOTHER_GAME


def test_both_days_reversed_name_both(owned_library, purchase):
    with pytest.raises(CommandFailed) as refused:
        _restate(purchase, purchased=ActStatement(JULY), refund=ActStatement(JUNE))

    assert refused.value.message == REFUNDED_BEFORE_BOUGHT


def test_a_corrected_refund_before_the_acquisition_appends_nothing(
    owned_library, entry, purchase
):
    _dispatch(owned_library, _refund(purchase))
    before = _library_event_count(purchase)

    with pytest.raises(CommandFailed) as refused:
        _restate(purchase, purchased=ActStatement(MARCH), refund=ActStatement(APRIL))

    assert refused.value.message == REFUND_BEFORE_ACQUISITION
    assert _library_event_count(purchase) == before


def test_a_kind_stated_as_game_ends_the_copy(owned_library, entry):
    addon = record_purchase(entry, kind="season_pass", purchased=MAY)

    _restate(addon, kind="game", refund=ActStatement(JUNE))

    assert _fresh(entry).access_end_way == "refunded"


def test_a_second_purchases_refund_never_moves_the_first_ones_end(
    owned_library, entry, purchase
):
    second = record_purchase(entry, purchased=MAY)
    _dispatch(owned_library, _refund(purchase))
    _dispatch(owned_library, _refund(second))

    corrected = _dispatch(owned_library, _correct(second, when=JULY))
    voided = _dispatch(owned_library, _void(second))

    assert _batch(corrected) == [("library.purchase.refund_corrected", second.pk)]
    assert _batch(voided) == [("library.purchase.refund_voided", second.pk)]
    assert _fresh(entry).access_ended == JUNE


def test_a_correction_after_a_resume_leaves_the_copy_held(
    owned_library, entry, purchase
):
    _dispatch(owned_library, _refund(purchase))
    _dispatch(
        owned_library,
        ResumeEntryAccess(entry_id=entry.pk, statement=ActStatement(JULY)),
    )

    result = _dispatch(owned_library, _correct(purchase, when=JULY))

    assert _batch(result) == [("library.purchase.refund_corrected", purchase.pk)]
    assert _fresh(entry).access_end_recorded_at is None


def test_a_correction_under_a_removed_release_is_refused(
    owned_library, graph, purchase
):
    _dispatch(owned_library, _refund(purchase))
    remove(graph.release)

    refused = _refused(owned_library, _correct(purchase, when=JULY))

    assert refused.sentence == RELEASE_REMOVED


@pytest.mark.parametrize("command", (_correct, _void))
def test_a_removed_purchases_refund_stays(owned_library, purchase, command):
    _dispatch(owned_library, _refund(purchase))
    remove_purchase(purchase)

    refused = _refused(owned_library, command(purchase))

    assert refused.sentence == PURCHASE_REMOVED


def test_a_void_under_a_removed_game_is_refused(owned_library, entry, purchase):
    _dispatch(owned_library, _refund(purchase))
    _dispatch(owned_library, RemovePlayerGame(game_id=entry.player_game.game_id))

    assert _refused(owned_library, _void(purchase)).sentence == PLAYER_GAME_REMOVED


# --- what the copy's end answers ------------------------------------------


def test_the_write_answers_what_the_copy_end_did(owned_library, entry, purchase):
    assert _restate(purchase, refund=ActStatement(JUNE)).copy_end is CopyEnd.ENDED
    assert _restate(purchase, refund=ActStatement(JULY)).copy_end is CopyEnd.MOVED
    assert _restate(purchase, refund=None).copy_end is CopyEnd.TAKEN_BACK
    assert _restate(purchase, name="Deluxe").copy_end is None


def test_the_write_answers_a_copy_end_left_alone(owned_library, entry, purchase):
    end_entry_access(entry, way=EndWay.SOLD, ended=JULY)

    restated = _restate(purchase, refund=ActStatement(JUNE))

    assert (restated.appended, restated.copy_end) == (True, CopyEnd.LEFT)


# --- the key a refund reads -----------------------------------------------


def _append(library, events, key: str) -> None:
    with transaction.atomic():
        lock_stream(library).append(
            events, actor=None, correlation_id=uuid.uuid7(), idempotency_key=key
        )


def _end_event(entry, *, way: EndWay, ended: TemporalValue) -> NewEvent:
    return ENTRY_ACCESS_END_EVENTS.stated.new(
        aggregate_id=entry.pk,
        effective_time=ended,
        payload={"way": way.value, "note": ""},
    )


def test_a_reused_key_lends_no_hand_end_to_the_refund(owned_library, graph):
    borrowed = record_entry(owned_library, graph.release, access="borrowed")
    purchase = record_purchase(borrowed)
    result = _dispatch(owned_library, _refund(purchase))
    (refunded,) = LibraryEvent.objects.filter(
        aggregate_id=purchase.pk, event_type="library.purchase.refunded"
    )
    _dispatch(owned_library, DescribePurchase(purchase.pk, name="Deluxe"))

    hand_end = _end_event(borrowed, way=EndWay.SOLD, ended=JULY)
    _append(owned_library, [hand_end], refunded.idempotency_key)

    assert result.outcome is CommandOutcome.APPENDED
    assert not refund_owns_the_end(owned_library, _fresh(purchase))


def test_one_append_of_a_refund_and_its_end_owns_it(owned_library, entry, purchase):
    _append(
        owned_library,
        [
            PURCHASE_REFUND_EVENTS.stated.new(
                aggregate_id=purchase.pk, effective_time=JUNE, payload={"note": ""}
            ),
            _end_event(entry, way=EndWay.REFUNDED, ended=JUNE),
        ],
        "converted-refund",
    )

    assert refund_owns_the_end(owned_library, _fresh(purchase))


# --- the rest of the refusals ---------------------------------------------


def test_a_void_after_a_hand_void_leaves_the_copy(owned_library, entry, purchase):
    _dispatch(owned_library, _refund(purchase))
    _dispatch(owned_library, VoidEntryAccessEnd(entry_id=entry.pk))

    result = _dispatch(owned_library, _void(purchase))

    assert _batch(result) == [("library.purchase.refund_voided", purchase.pk)]


def test_a_correction_without_a_refund_is_refused(owned_library, purchase):
    refused = _refused(owned_library, _correct(purchase))

    assert refused.sentence == (
        "This purchase has no refund to correct. Record the refund first."
    )


@pytest.mark.parametrize("command", (_refund, _correct))
def test_a_refund_under_a_removed_game_is_refused(
    owned_library, entry, purchase, command
):
    if command is _correct:
        _dispatch(owned_library, _refund(purchase))
    _dispatch(owned_library, RemovePlayerGame(game_id=entry.player_game.game_id))

    assert _refused(owned_library, command(purchase)).sentence == PLAYER_GAME_REMOVED


def test_a_restated_refund_names_the_purchase_day(owned_library, purchase):
    _dispatch(owned_library, _refund(purchase))

    with pytest.raises(CommandFailed) as refused:
        _restate(purchase, purchased=ActStatement(JULY), refund=ActStatement(JUNE))

    assert refused.value.message == PURCHASE_AFTER_REFUND
