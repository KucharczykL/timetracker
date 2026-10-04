"""Commands keep their recorded fingerprints."""

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from games.commands.device import CreateDevice
from games.commands.endpoint import WayActStatement
from games.commands.historical_playtime import (
    HistoricalPlaytimeStatement,
    RecordHistoricalPlaytime,
)
from games.commands.libraryentry import (
    CorrectEntryAccessEnd,
    CorrectEntryAcquisition,
    DescribeEntry,
    EndEntryAccess,
    EntryStatement,
    RecordEntry,
    RemoveEntry,
    RestoreEntry,
    ResumeEntryAccess,
    VoidEntryAccessEnd,
)
from games.commands.playersession import (
    CorrectedTiming,
    CreateSession,
    DescribeSession,
    DurationOnlyTiming,
    StatedDevice,
    StatedRelease,
    TimedTiming,
)
from games.commands.playthrough import (
    ActStatement,
    CompletePlaythrough,
    CorrectPlaythroughCompletion,
    CorrectPlaythroughStart,
    CreatePlaythrough,
    StartPlaythrough,
    VoidPlaythroughCompletion,
    VoidPlaythroughStart,
)
from games.commands.purchase import (
    TAKE_REFUND_BACK,
    CorrectPurchaseRefund,
    DescribePurchase,
    RecordPurchase,
    RefundPurchase,
    RemovePurchase,
    RestorePurchase,
    StatedPrice,
    UndoPurchaseRefund,
    VoidPurchaseRefund,
)
from games.end_ways import EndWay
from games.events.dispatch import Command, canonical_command_input
from games.events.idempotency import fingerprint_command_input
from games.models import HistoricalPlaytimeProvenance
from timetracker.temporal import TemporalValue

RUN = uuid.UUID("01890000-0000-7000-8000-000000000001")
GAME = uuid.UUID("01890000-0000-7000-8000-000000000002")
RELEASE = uuid.UUID("01890000-0000-7000-8000-000000000003")
ENTRY = uuid.UUID("01890000-0000-7000-8000-000000000004")
PURCHASE = uuid.UUID("01890000-0000-7000-8000-000000000005")
SESSION = uuid.UUID("01890000-0000-7000-8000-000000000006")
DEVICE = uuid.UUID("01890000-0000-7000-8000-000000000007")
MAY = TemporalValue.parse("2021-05")
NOON = datetime(2021, 5, 1, 12, tzinfo=UTC)

COMMANDS: dict[str, Command] = {
    "start": StartPlaythrough(playthrough_id=RUN, when=MAY, note="began"),
    "complete": CompletePlaythrough(playthrough_id=RUN, when=None, note=""),
    "correct_start": CorrectPlaythroughStart(playthrough_id=RUN, when=MAY, note=""),
    "correct_completion": CorrectPlaythroughCompletion(
        playthrough_id=RUN, when=MAY, note="done"
    ),
    "void_start": VoidPlaythroughStart(playthrough_id=RUN),
    "void_completion": VoidPlaythroughCompletion(playthrough_id=RUN),
    #: Moved when CreateDevice gained access_end.
    "create_device": CreateDevice(name="Deck", type="Handheld"),
    "create": CreatePlaythrough(
        game_id=GAME,
        started=ActStatement(MAY, "began"),
        completed=ActStatement(None, ""),
        note="run",
    ),
    "record_entry": RecordEntry(
        release_id=RELEASE,
        access="owned",
        format="digital",
        note="gift",
        acquired=ActStatement(MAY, "birthday"),
    ),
    "describe_entry": DescribeEntry(entry_id=ENTRY, access="borrowed"),
    "correct_entry_acquisition": CorrectEntryAcquisition(
        entry_id=ENTRY, statement=ActStatement(None, "")
    ),
    "remove_entry": RemoveEntry(entry_id=ENTRY),
    "restore_entry": RestoreEntry(entry_id=ENTRY),
    "end_entry_access": EndEntryAccess(
        entry_id=ENTRY, statement=WayActStatement(MAY, EndWay.RETURNED, "lent")
    ),
    "correct_entry_access_end": CorrectEntryAccessEnd(
        entry_id=ENTRY, statement=WayActStatement(None, EndWay.EXPIRED, "")
    ),
    "void_entry_access_end": VoidEntryAccessEnd(entry_id=ENTRY),
    "resume_entry_access": ResumeEntryAccess(
        entry_id=ENTRY, statement=ActStatement(MAY, "back")
    ),
    "record_purchase": RecordPurchase(
        kind="game",
        copy=ENTRY,
        name="Deluxe",
        price=StatedPrice(Decimal("12.50"), "EUR"),
        note="gift",
        purchased=ActStatement(MAY, "sale"),
    ),
    "record_purchase_new_copy": RecordPurchase(
        kind="season_pass",
        copy=EntryStatement(
            release_id=RELEASE,
            access="owned",
            format="digital",
            note="",
            acquired=ActStatement(None, ""),
        ),
    ),
    "describe_purchase": DescribePurchase(
        purchase_id=PURCHASE, price=StatedPrice(None, ""), entry_id=ENTRY
    ),
    "describe_purchase_refund_taken_back": DescribePurchase(
        purchase_id=PURCHASE, refund=TAKE_REFUND_BACK
    ),
    "remove_purchase": RemovePurchase(purchase_id=PURCHASE),
    "restore_purchase": RestorePurchase(purchase_id=PURCHASE),
    "refund_purchase": RefundPurchase(
        purchase_id=PURCHASE, statement=ActStatement(MAY, "store")
    ),
    "correct_purchase_refund": CorrectPurchaseRefund(
        purchase_id=PURCHASE, statement=ActStatement(None, "")
    ),
    "void_purchase_refund": VoidPurchaseRefund(purchase_id=PURCHASE),
    "undo_purchase_refund": UndoPurchaseRefund(purchase_id=PURCHASE, refunded_at=42),
    "describe_session": DescribeSession(
        session_id=SESSION,
        device=StatedDevice(DEVICE),
        release=StatedRelease(RELEASE),
    ),
    "describe_session_to_none": DescribeSession(
        session_id=SESSION, device=StatedDevice(None), release=StatedRelease(None)
    ),
    "create_timed_session": CreateSession(
        playthrough_id=RUN,
        timing=TimedTiming(started_at=NOON, day_zone="Europe/Prague"),
    ),
    "create_duration_only_session": CreateSession(
        playthrough_id=RUN,
        timing=DurationOnlyTiming(day=date(2021, 5, 1), duration=timedelta(hours=1)),
    ),
    "create_corrected_session": CreateSession(
        playthrough_id=RUN,
        timing=CorrectedTiming(
            started_at=NOON,
            ended_at=NOON + timedelta(hours=2),
            duration=timedelta(hours=1),
            day_zone="Europe/Prague",
        ),
    ),
    "record_historical_playtime": RecordHistoricalPlaytime(
        statement=HistoricalPlaytimeStatement(
            duration=timedelta(hours=100),
            when="2005",
            provenance=HistoricalPlaytimeProvenance.ESTIMATED,
            playthrough_ids=(RUN,),
            device_id=None,
            release_id=RELEASE,
            emulated=False,
            note="",
        )
    ),
}

RECORDED: dict[str, str] = {
    "correct_entry_access_end": (
        "c21467c527ae301865354f28bec92531384614be6657b1b2df4b2087a93a0103"
    ),
    "end_entry_access": (
        "64eb6ed582867c743f0931e85d8d9961d85f5d16cd9742bfe0d1b916c8c521ce"
    ),
    "resume_entry_access": (
        "f42157129bedd51522032d00d28987f151451f97ca33ace14afddcd5cb193f90"
    ),
    "void_entry_access_end": (
        "d2313c5b75931be63e4b2f59028f51dad51ea0e297fb58fb026cad1f7de746d1"
    ),
    "complete": "a383d10184a3fd5c8f7c128ad7c6540cffee5e05b5f329e2cc88f7a6ac398537",
    "correct_completion": (
        "0490e599e25fd92b2019a03e128c8596403b94e8c8911d31121ecdb9bdd30c03"
    ),
    "correct_entry_acquisition": (
        "ba6497d9b1e8fcc785b0ebdb1a00f4419ece408e44b09ac449cb5a4bf2b3b25a"
    ),
    "correct_start": "9650f82546728f0150ebe080bcc5bbc78466123b8418e7029989c62205ff69da",
    "create": "7fe8275a8295fdb9890df94ad28b34430a3dc384dd6c5c3a0cf127659a539d53",
    "create_device": (
        "2bc2ba678e5fa0b358a78326139da09d621bd587ad0994b07a7663ac19ba5274"
    ),
    "describe_entry": "624fbbd5e4c2e5a0d5675d340444058f8af30b92130d935638d7499dc74e4ca4",
    "record_entry": "44a4aac331629282fa27af861f0a83eb84df1a5783fd19a8bb417b046edf541d",
    "remove_entry": "21a157fa46b073a20091ca8e8a86bedd1e6fa8749ccbc35fb4dbe981bb7fd393",
    "restore_entry": "66fa174dd36166b0e374a7bbfe206a58c43e7814233162c82a7a6a1833f164d3",
    "start": "89d10a7bcb9966145fbf794ecd8972584210c18e029986720af18bb06a5ff43a",
    "void_completion": (
        "31b02261fdd35cb1d88a85afb111029cf12964fb940dcfff270776cc1fb02c66"
    ),
    "void_start": "b83184f38a8c6e7cc9ca5d0fa308f3ad48b2176e1815b388f168fe809e9c2a23",
    "describe_purchase": (
        "6686457ec6bad852364858ad902f6f2ceb3f161d3c225160b217905208420dbc"
    ),
    "record_purchase": (
        "ba19ae103bd77c7e136dbf241d00c346b07419df31042308827fd902634a8261"
    ),
    "record_purchase_new_copy": (
        "49fe28a715d8ac3f096f863d009a5556f9be7798f6bdd70af157f650ed99f9ec"
    ),
    "remove_purchase": (
        "6eb59eaeca25392179507029ed9d32bb3acc5ad20d689a06ca08c2af61179a45"
    ),
    "restore_purchase": (
        "2e588e71418455ed1f6e11c04e3e1629638aa20e85049a5e78918a6729021b81"
    ),
    "describe_purchase_refund_taken_back": (
        "5b6fa7cfd60ad05b4226446a285355af7e028c5f6bbafed66ed0744adad3c74c"
    ),
    "refund_purchase": (
        "14703e799db760449f9c8b2ee4fd457566c50c9745022bc90e1930bd3b1f1d75"
    ),
    "correct_purchase_refund": (
        "64ec75f1937109107a1bf26c8d1cbdb0cac89dcdef871df705ddbedaa601e63b"
    ),
    "void_purchase_refund": (
        "bcf8735d0164b1f736dc71770189e5693f6a7731ecac5c9c87d51a2c53c57a14"
    ),
    "undo_purchase_refund": (
        "fab7c21574cb2636fed67dd339cf6a80b1cfe39bc64ccc76e56e776cf25cbbca"
    ),
    "describe_session": (
        "888b5d7e18c2403242f9c9fe79cb530f86041fbe1f2b6647cc38616cf73a1983"
    ),
    "create_timed_session": (
        "07510c52e199fb6bbc12f96791e329d714e15f2cbdfbec4611424de395b15fb1"
    ),
    "create_duration_only_session": (
        "af2b3846e52d6ac1e6bfdc9a48989fd6fba19026388c75345cbc4631bcbc9bab"
    ),
    "create_corrected_session": (
        "538e8bde512e330ea5c74a7972d2064fce13a73f56c541fc67e060c8d84fe5d6"
    ),
    "record_historical_playtime": (
        "8b944a87b58091b5244c42417916c81e76e67f9bcaed5ed51e0b1bb346f67c53"
    ),
    "describe_session_to_none": (
        "0db9ea775239b97d760c9f04c3be5a5b0e2b3449246ece939432a8a854b4e0fa"
    ),
}


@pytest.mark.parametrize("name", sorted(COMMANDS))
def test_fingerprint_is_the_recorded_one(name: str) -> None:
    command = COMMANDS[name]
    assert fingerprint_command_input(canonical_command_input(command)) == RECORDED[name]


def test_a_price_fingerprints_alike_in_every_spelling() -> None:
    def digest(price: StatedPrice) -> str:
        command = DescribePurchase(purchase_id=PURCHASE, price=price)
        return fingerprint_command_input(canonical_command_input(command))

    assert digest(StatedPrice(Decimal("12.5"), " eur ")) == digest(
        StatedPrice(Decimal("12.50"), "EUR")
    )


def test_a_take_back_fingerprints_apart_from_an_undated_refund() -> None:
    def digest(refund) -> str:
        command = DescribePurchase(purchase_id=PURCHASE, refund=refund)
        return fingerprint_command_input(canonical_command_input(command))

    assert digest(TAKE_REFUND_BACK) != digest(ActStatement(None, ""))
