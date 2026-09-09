"""Every event type of both families, replayed.

The dispatches need real transactions, and the conftest tracking
fixture would otherwise write projection rows no event states.
"""

from collections.abc import Mapping
from datetime import date
from typing import Any, NamedTuple

import pytest

from games.backfill.playergame import backfill_library
from games.backfill.playthrough import convert_library
from games.commands.playergame import (
    RemovePlayerGame,
    RestorePlayerGame,
    SetPlayerGameExcludedFromUnfinished,
    SetPlayerGameMastered,
    SetPlayerGameStatus,
    TrackGame,
)
from games.commands.playthrough import (
    CompletePlaythrough,
    CorrectPlaythroughCompletion,
    CorrectPlaythroughStart,
    CreatePlaythrough,
    DescribePlaythrough,
    RemovePlaythrough,
    RestorePlaythrough,
    StartPlaythrough,
)
from games.events.dispatch import Command, CommandOutcome, dispatch
from games.events.rebuild import RebuildMode, rebuild_projections
from games.events.replay import replay
from games.models import (
    Game,
    LibraryEvent,
    LibraryEventStreamHead,
    LibraryIdempotencyRecord,
    PlayerGame,
    PlayerGameStatus,
    PlayEvent,
    Playthrough,
)
from games.projectors.playergame import PlayerGames
from games.projectors.playthrough import Playthroughs
from games.reads.playthrough_numbering import numbered_for
from games.removal import remove
from timetracker.temporal import TemporalValue

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.untracked_games,
]


class DispatchedCommand(NamedTuple):
    """One command, and its idempotency key."""

    command: Command
    key: str


def build_stream(user, library) -> list[DispatchedCommand]:
    """Every type of both families, through commands.

    Nothing appends by hand: the gate is a claim about what the write
    path produces, and an event this module wrote itself would prove
    only that the projector reads it.
    """
    first = Game.objects.create(library=library, name="Outer Wilds")
    second = Game.objects.create(library=library, name="Tunic")
    dispatched: list[DispatchedCommand] = []

    def run(command: Command, key: str) -> None:
        result = dispatch(command, actor=user, library=library, idempotency_key=key)
        assert result.outcome is CommandOutcome.APPENDED, (
            f"{key} recorded nothing, so the stream misses its event types."
        )
        dispatched.append(DispatchedCommand(command, key))

    run(TrackGame(game_id=first.pk), "track-first")
    run(TrackGame(game_id=second.pk), "track-second")

    first_run = Playthrough.objects.get(player_game__game=first)
    run(
        SetPlayerGameStatus(game_id=first.pk, status=PlayerGameStatus.PLAYED),
        "status-first",
    )
    run(SetPlayerGameMastered(game_id=first.pk, mastered=True), "mastered-first")
    run(
        SetPlayerGameExcludedFromUnfinished(
            game_id=first.pk, excluded_from_unfinished=True
        ),
        "excluded-first",
    )
    run(
        StartPlaythrough(
            playthrough_id=first_run.pk,
            when=TemporalValue.from_day(date(2024, 1, 1)),
            note="Began here",
        ),
        "start-first-run",
    )
    run(
        CompletePlaythrough(
            playthrough_id=first_run.pk,
            when=TemporalValue.from_day(date(2024, 2, 1)),
            note="Ended here",
        ),
        "complete-first-run",
    )
    run(
        CorrectPlaythroughStart(
            playthrough_id=first_run.pk,
            when=TemporalValue.from_day(date(2023, 12, 24)),
            note="Played before that",
        ),
        "correct-start-first-run",
    )
    run(
        CorrectPlaythroughCompletion(
            playthrough_id=first_run.pk,
            when=TemporalValue.from_day(date(2024, 2, 14)),
            note="Finished later",
        ),
        "correct-completion-first-run",
    )
    run(
        DescribePlaythrough(
            playthrough_id=first_run.pk, name="Blind run", note="No hints"
        ),
        "describe-first-run",
    )

    run(CreatePlaythrough(game_id=first.pk), "create-second-run")
    second_run = (
        Playthrough.objects.filter(player_game__game=first)
        .exclude(pk=first_run.pk)
        .get()
    )
    run(RemovePlaythrough(playthrough_id=second_run.pk), "remove-second-run")
    run(RestorePlaythrough(playthrough_id=second_run.pk), "restore-second-run")

    run(RemovePlayerGame(game_id=second.pk), "remove-second-game")
    run(RestorePlayerGame(game_id=second.pk), "restore-second-game")
    return dispatched


def registered_event_types() -> set[str]:
    """Every type the two CURRENT_STATE projectors read."""
    return {
        spec.event_type
        for handles in (PlayerGames.handles, Playthroughs.handles)
        for spec in handles
    }


def test_the_stream_carries_every_registered_event_type(owned_user, owned_library):
    """A type the stream misses goes untested."""
    build_stream(owned_user, owned_library)
    appended = set(
        LibraryEvent.objects.filter(library=owned_library).values_list(
            "event_type", flat=True
        )
    )

    assert registered_event_types() - appended == set()


def test_the_guard_names_a_type_the_stream_missed():
    """The guard names the type it missed."""
    complete = registered_event_types()
    missing = "library.playthrough.restored"
    assert missing in complete

    assert complete - (complete - {missing}) == {missing}


def build_neighbour(user, library) -> None:
    """A shorter stream every leg leaves alone."""
    game = Game.objects.create(library=library, name="Hollow Knight")
    dispatch(
        TrackGame(game_id=game.pk),
        actor=user,
        library=library,
        idempotency_key="neighbour-track",
    )
    dispatch(
        SetPlayerGameStatus(game_id=game.pk, status=PlayerGameStatus.COMPLETED),
        actor=user,
        library=library,
        idempotency_key="neighbour-status",
    )


@pytest.fixture
def neighbour(django_user_model):
    """A second owner with their own library."""
    user = django_user_model.objects.create_user(
        username="gate-neighbour", password="p"
    )
    build_neighbour(user, user.library)
    return user.library


#: Both tables' rows, as `.values()` answers them.
type ProjectionRows = list[Mapping[str, Any]]


def rows_of(library) -> tuple[ProjectionRows, ProjectionRows]:
    """Both tables' whole rows, in key order.

    `.values()` rather than a column list, so a column added later is
    in the comparison the day it lands.
    """
    return (
        list(PlayerGame.objects.filter(library=library).order_by("pk").values()),
        list(Playthrough.objects.filter(library=library).order_by("pk").values()),
    )


def empty_projections(library) -> None:
    """Scoped by library, child first for RESTRICT."""
    Playthrough.objects.filter(library=library).delete()
    PlayerGame.objects.filter(library=library).delete()


def test_replaying_an_emptied_library_reproduces_both_tables(
    owned_user, owned_library, neighbour
):
    """Every column, including the clock-derived ones."""
    build_stream(owned_user, owned_library)
    before = rows_of(owned_library)
    untouched = rows_of(neighbour)
    empty_projections(owned_library)

    result = replay(owned_library)

    assert result.replayed_through == (
        LibraryEventStreamHead.objects.get(library=owned_library).current_sequence
    )
    assert rows_of(owned_library) == before
    assert rows_of(neighbour) == untouched


def test_a_rebuild_swaps_both_tables_with_an_empty_diff(
    owned_user, owned_library, neighbour
):
    """The rebuild's own diff, not this module's."""
    build_stream(owned_user, owned_library)
    untouched = rows_of(neighbour)

    report = rebuild_projections(owned_library, mode=RebuildMode.REBUILD)

    assert report.swapped is True
    assert [
        (table.table, table.only_live, table.only_rebuilt, table.differing)
        for table in report.tables
    ] == [
        ("games_playergame", 0, 0, 0),
        ("games_playthrough", 0, 0, 0),
    ]
    assert rows_of(neighbour) == untouched


def test_every_command_repeated_under_its_key_records_nothing(
    owned_user, owned_library, neighbour
):
    """A repeat answers from the record."""
    dispatched = build_stream(owned_user, owned_library)
    before = rows_of(owned_library)
    untouched = rows_of(neighbour)
    head_before = LibraryEventStreamHead.objects.get(
        library=owned_library
    ).current_sequence
    events_before = LibraryEvent.objects.filter(library=owned_library).count()

    for command, key in dispatched:
        result = dispatch(
            command, actor=owned_user, library=owned_library, idempotency_key=key
        )
        assert result.outcome is CommandOutcome.REPLAYED, key

    assert (
        LibraryEventStreamHead.objects.get(library=owned_library).current_sequence
        == head_before
    )
    assert LibraryEvent.objects.filter(library=owned_library).count() == events_before
    assert rows_of(owned_library) == before
    assert rows_of(neighbour) == untouched
    assert LibraryIdempotencyRecord.objects.filter(
        library=owned_library
    ).count() == len({key for _command, key in dispatched})


def build_converted(library) -> Game:
    """Runs converted out of the legacy rows."""
    game = Game.objects.create(library=library, name="Chrono Trigger")
    PlayEvent.objects.create(
        game=game, started=date(2024, 1, 1), ended=date(2024, 1, 9), note="One"
    )
    PlayEvent.objects.create(game=game)
    remove(PlayEvent.objects.create(game=game, started=date(2023, 1, 1)))
    backfill_library(library)
    convert_library(library)
    return game


def test_a_converted_library_replays_into_its_live_rows(owned_library, neighbour):
    """The live tables, not a shadow."""
    build_converted(owned_library)
    before = rows_of(owned_library)
    untouched = rows_of(neighbour)
    empty_projections(owned_library)

    replay(owned_library)

    assert rows_of(owned_library) == before
    assert rows_of(neighbour) == untouched


def test_a_converted_library_rebuilds_with_an_empty_diff(owned_library, neighbour):
    """A real REBUILD, which swaps."""
    build_converted(owned_library)
    untouched = rows_of(neighbour)

    report = rebuild_projections(owned_library, mode=RebuildMode.REBUILD)

    assert report.swapped is True
    assert [
        (table.table, table.only_live, table.only_rebuilt, table.differing)
        for table in report.tables
    ] == [
        ("games_playergame", 0, 0, 0),
        ("games_playthrough", 0, 0, 0),
    ]
    assert rows_of(neighbour) == untouched


def test_the_display_number_survives_a_rebuild_of_tied_runs(owned_library):
    """Only the key separates these two runs.

    RowNumber over peers follows the plan's input order, which a swap
    changes -- so a tie is the case a rebuild can renumber.
    """
    game = Game.objects.create(library=owned_library, name="Chrono Trigger")
    first = PlayEvent.objects.create(game=game)
    second = PlayEvent.objects.create(game=game)
    #: auto_now_add: the tie is stated by hand.
    instant = PlayEvent.objects.get(pk=first.pk).created_at
    PlayEvent.objects.filter(pk__in=(first.pk, second.pk)).update(created_at=instant)
    backfill_library(owned_library)
    convert_library(owned_library)
    tracked = PlayerGame.objects.get(library=owned_library, game=game)

    #: Unannotated: display_number is a queryset alias.
    def numbers():
        return {
            run.pk: run.display_number
            for run in numbered_for(owned_library, [tracked.pk])
        }

    before = numbers()
    #: Two runs, endpoints unstated, created_at tied.
    assert len(before) == 2
    assert sorted(before.values()) == [1, 2]

    report = rebuild_projections(owned_library, mode=RebuildMode.REBUILD)

    assert report.swapped is True
    assert numbers() == before
