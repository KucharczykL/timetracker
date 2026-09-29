"""Endpoint commands keep their recorded fingerprints."""

import uuid

import pytest

from games.commands.device import CreateDevice
from games.commands.libraryentry import (
    CorrectEntryAcquisition,
    DescribeEntry,
    RecordEntry,
    RemoveEntry,
    RestoreEntry,
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
from games.events.dispatch import Command, canonical_command_input
from games.events.idempotency import fingerprint_command_input
from timetracker.temporal import TemporalValue

RUN = uuid.UUID("01890000-0000-7000-8000-000000000001")
GAME = uuid.UUID("01890000-0000-7000-8000-000000000002")
RELEASE = uuid.UUID("01890000-0000-7000-8000-000000000003")
ENTRY = uuid.UUID("01890000-0000-7000-8000-000000000004")
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
}

RECORDED: dict[str, str] = {
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
}


@pytest.mark.parametrize("name", sorted(COMMANDS))
def test_fingerprint_is_the_recorded_one(name: str) -> None:
    command = COMMANDS[name]
    assert fingerprint_command_input(canonical_command_input(command)) == RECORDED[name]
