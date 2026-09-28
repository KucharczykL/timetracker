"""Endpoint commands keep their recorded fingerprints."""

import uuid

import pytest

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
    "create": CreatePlaythrough(
        game_id=GAME,
        started=ActStatement(MAY, "began"),
        completed=ActStatement(None, ""),
        note="run",
    ),
}

RECORDED: dict[str, str] = {
    "complete": "a383d10184a3fd5c8f7c128ad7c6540cffee5e05b5f329e2cc88f7a6ac398537",
    "correct_completion": (
        "0490e599e25fd92b2019a03e128c8596403b94e8c8911d31121ecdb9bdd30c03"
    ),
    "correct_start": "9650f82546728f0150ebe080bcc5bbc78466123b8418e7029989c62205ff69da",
    "create": "4820bdd45c212b9a0871172b1ca790d269bcb10f07d21fc0545490bd48ac99ba",
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
