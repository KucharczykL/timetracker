"""Endpoint commands keep their recorded fingerprints."""

import uuid
from decimal import Decimal

import pytest

from games.commands.device import CreateDevice
from games.commands.endpoint import WayActStatement
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
    CorrectPurchase,
    DescribePurchase,
    RecordPurchase,
    RemovePurchase,
    RestorePurchase,
    StatedPrice,
)
from games.end_ways import EndWay
from games.events.dispatch import Command, canonical_command_input
from games.events.idempotency import fingerprint_command_input
from timetracker.temporal import TemporalValue

RUN = uuid.UUID("01890000-0000-7000-8000-000000000001")
GAME = uuid.UUID("01890000-0000-7000-8000-000000000002")
RELEASE = uuid.UUID("01890000-0000-7000-8000-000000000003")
ENTRY = uuid.UUID("01890000-0000-7000-8000-000000000004")
PURCHASE = uuid.UUID("01890000-0000-7000-8000-000000000005")
MAY = TemporalValue.parse("2021-05")

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
    "correct_purchase": CorrectPurchase(
        purchase_id=PURCHASE, statement=ActStatement(MAY, "")
    ),
    "remove_purchase": RemovePurchase(purchase_id=PURCHASE),
    "restore_purchase": RestorePurchase(purchase_id=PURCHASE),
}

RECORDED: dict[str, str] = {
    "correct_entry_access_end": (
        "3c52b21416172e04e107a7fbc2f393307a230c83852ec59b3043da02e9405ce1"
    ),
    "end_entry_access": (
        "d58b4017ab28d3d55c22c15e906d908a63b13791f39e35019ec61c593fe0e0a2"
    ),
    "resume_entry_access": (
        "95ab5df157e2618c853ba772c2c4826a81db64bd941bd4bf8a168cccb8dcfa03"
    ),
    "void_entry_access_end": (
        "d2313c5b75931be63e4b2f59028f51dad51ea0e297fb58fb026cad1f7de746d1"
    ),
    "complete": "a383d10184a3fd5c8f7c128ad7c6540cffee5e05b5f329e2cc88f7a6ac398537",
    "correct_completion": (
        "0490e599e25fd92b2019a03e128c8596403b94e8c8911d31121ecdb9bdd30c03"
    ),
    "correct_entry_acquisition": (
        "1c399b9ae1ebc4a20a9d350ecc85a889e65a2650ea0dcdc772ebf8d6c6c40d6b"
    ),
    "correct_start": "9650f82546728f0150ebe080bcc5bbc78466123b8418e7029989c62205ff69da",
    "create": "4820bdd45c212b9a0871172b1ca790d269bcb10f07d21fc0545490bd48ac99ba",
    "create_device": (
        "2bc2ba678e5fa0b358a78326139da09d621bd587ad0994b07a7663ac19ba5274"
    ),
    "describe_entry": "624fbbd5e4c2e5a0d5675d340444058f8af30b92130d935638d7499dc74e4ca4",
    "record_entry": "d6dd7c56e8f3dd69393ed48ca19838c4ce7e64edf1ee385808341d9bc2dc2c68",
    "remove_entry": "21a157fa46b073a20091ca8e8a86bedd1e6fa8749ccbc35fb4dbe981bb7fd393",
    "restore_entry": "66fa174dd36166b0e374a7bbfe206a58c43e7814233162c82a7a6a1833f164d3",
    "start": "89d10a7bcb9966145fbf794ecd8972584210c18e029986720af18bb06a5ff43a",
    "void_completion": (
        "31b02261fdd35cb1d88a85afb111029cf12964fb940dcfff270776cc1fb02c66"
    ),
    "void_start": "b83184f38a8c6e7cc9ca5d0fa308f3ad48b2176e1815b388f168fe809e9c2a23",
    "correct_purchase": (
        "0d5e1310fbaf8b68476247edb8b1d759e2c64756089406a0ad7508a39cd75806"
    ),
    "describe_purchase": (
        "408a6cbd44e31b9de62845fbfe9c99281b65a6779d05a4b2cda7305674b81d20"
    ),
    "record_purchase": (
        "910548f3eadfece06170bf42e6826c97e067ce71effc901b935704862325a2f2"
    ),
    "record_purchase_new_copy": (
        "c8a8ce8fb148d5582384d0c3465d576ee6e4da2a5e534ed360f26b025dee0c93"
    ),
    "remove_purchase": (
        "6eb59eaeca25392179507029ed9d32bb3acc5ad20d689a06ca08c2af61179a45"
    ),
    "restore_purchase": (
        "2e588e71418455ed1f6e11c04e3e1629638aa20e85049a5e78918a6729021b81"
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
