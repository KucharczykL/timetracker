"""Every event type of both families, replayed.

The dispatches need real transactions, and the conftest tracking
fixture would otherwise write projection rows no event states.
"""

from collections.abc import Mapping
from datetime import date
from typing import Any, NamedTuple

import pytest
from django.db import connection

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
    PlaythroughKind,
)
from games.projectors.playergame import PlayerGames
from games.projectors.playthrough import Playthroughs
from games.reads.playthrough_numbering import DISPLAY_ORDER
from games.removal import remove
from timetracker.temporal import TemporalValue

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.untracked_games,
]

#: No command states one; an importer takes it.
UNREACHABLE_KINDS = frozenset({PlaythroughKind.IMPORTED_HISTORY})


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
    third = Game.objects.create(library=library, name="Hades")
    dispatched: list[DispatchedCommand] = []

    def run(command: Command, key: str) -> None:
        result = dispatch(command, actor=user, library=library, idempotency_key=key)
        assert result.outcome is CommandOutcome.APPENDED, (
            f"{key} recorded nothing, so the stream misses its event types."
        )
        dispatched.append(DispatchedCommand(command, key))

    run(TrackGame(game_id=first.pk), "track-first")
    run(TrackGame(game_id=second.pk), "track-second")
    run(TrackGame(game_id=third.pk), "track-third")

    first_run = Playthrough.objects.get(player_game__game=first)
    run(
        SetPlayerGameStatus(game_id=first.pk, status=PlayerGameStatus.PLAYED),
        "status-first",
    )
    #: A second word, so the column is no constant.
    run(
        SetPlayerGameStatus(game_id=second.pk, status=PlayerGameStatus.ABANDONED),
        "status-second",
    )
    run(SetPlayerGameMastered(game_id=first.pk, mastered=True), "mastered-first")
    #: On, then off: the false is stated, not defaulted.
    run(SetPlayerGameMastered(game_id=second.pk, mastered=True), "mastered-second-on")
    run(SetPlayerGameMastered(game_id=second.pk, mastered=False), "mastered-second-off")
    run(
        SetPlayerGameExcludedFromUnfinished(
            game_id=first.pk, excluded_from_unfinished=True
        ),
        "excluded-first",
    )
    run(
        SetPlayerGameExcludedFromUnfinished(
            game_id=second.pk, excluded_from_unfinished=True
        ),
        "excluded-second-on",
    )
    run(
        SetPlayerGameExcludedFromUnfinished(
            game_id=second.pk, excluded_from_unfinished=False
        ),
        "excluded-second-off",
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
    #: A stated act on no day: the marker stands, the date is null.
    run(
        StartPlaythrough(
            playthrough_id=second_run.pk, when=None, note="Before I kept dates"
        ),
        "start-second-run-undated",
    )
    run(
        CompletePlaythrough(
            playthrough_id=second_run.pk, when=None, note="Some time later"
        ),
        "complete-second-run-undated",
    )
    #: A name alone, then a note alone: one fact each.
    run(
        DescribePlaythrough(playthrough_id=second_run.pk, name="Undated", note=None),
        "name-second-run",
    )
    run(
        DescribePlaythrough(playthrough_id=second_run.pk, name=None, note="No days"),
        "note-second-run",
    )
    run(RemovePlaythrough(playthrough_id=second_run.pk), "remove-second-run")
    run(RestorePlaythrough(playthrough_id=second_run.pk), "restore-second-run")

    #: Left removed, so a stamped removed_at reaches the snapshot.
    run(CreatePlaythrough(game_id=first.pk), "create-third-run")
    third_run = (
        Playthrough.objects.filter(player_game__game=first)
        .exclude(pk__in=(first_run.pk, second_run.pk))
        .get()
    )
    run(RemovePlaythrough(playthrough_id=third_run.pk), "remove-third-run")

    run(RemovePlayerGame(game_id=second.pk), "remove-second-game")
    run(RestorePlayerGame(game_id=second.pk), "restore-second-game")
    #: Left removed, for the same reason as the third run.
    run(RemovePlayerGame(game_id=third.pk), "remove-third-game")
    return dispatched


def registered_event_types() -> set[str]:
    """Every type the two CURRENT_STATE projectors read."""
    return {
        spec.event_type
        for handles in (PlayerGames.handles, Playthroughs.handles)
        for spec in handles
    }


def missing_event_types(library) -> set[str]:
    """Every registered type this stream never appended."""
    appended = set(
        LibraryEvent.objects.filter(library=library).values_list(
            "event_type", flat=True
        )
    )
    return registered_event_types() - appended


def test_the_stream_carries_every_registered_event_type(owned_user, owned_library):
    """A type the stream misses goes untested."""
    build_stream(owned_user, owned_library)

    assert missing_event_types(owned_library) == set()


def test_the_guard_names_a_type_a_partial_stream_missed(owned_user, owned_library):
    """A real stream, short of thirteen of its types."""
    game = Game.objects.create(library=owned_library, name="Celeste")
    dispatch(
        TrackGame(game_id=game.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key="partial-track",
    )

    missing = missing_event_types(owned_library)

    #: What TrackGame appends, so neither is named.
    assert missing == registered_event_types() - {
        "library.playergame.created",
        "library.playthrough.created",
    }
    assert len(missing) == 13


def build_neighbour(user, library) -> None:
    """A shorter stream every leg leaves alone.

    Each dispatch is asserted, because a build that quietly wrote
    nothing would turn every neighbour comparison into two empty lists
    agreeing with each other.
    """
    game = Game.objects.create(library=library, name="Hollow Knight")
    for command, key in (
        (TrackGame(game_id=game.pk), "neighbour-track"),
        (
            SetPlayerGameStatus(game_id=game.pk, status=PlayerGameStatus.COMPLETED),
            "neighbour-status",
        ),
    ):
        result = dispatch(command, actor=user, library=library, idempotency_key=key)
        assert result.outcome is CommandOutcome.APPENDED, key


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
    in the comparison the day it lands. Refuses an empty table, because
    every caller compares two snapshots and two empty ones agree
    whatever the leg between them did.
    """
    tracked: ProjectionRows = list(
        PlayerGame.objects.filter(library=library).order_by("pk").values()
    )
    runs: ProjectionRows = list(
        Playthrough.objects.filter(library=library).order_by("pk").values()
    )
    assert tracked and runs, f"Library {library.pk} holds no rows to compare."
    return (tracked, runs)


def row_versions(library) -> list[tuple[str, str]]:
    """Each row's key and its `xmin`, in key order.

    A rewrite moves `xmin` even where it writes the values the row
    already held, which is what parts an untouched neighbour from one
    an unscoped replay upserted over.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT id::text, xmin::text FROM games_playergame WHERE library_id = %s
            UNION ALL
            SELECT id::text, xmin::text FROM games_playthrough WHERE library_id = %s
            ORDER BY 1
            """,
            [library.pk, library.pk],
        )
        return cursor.fetchall()


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
    unwritten = row_versions(neighbour)
    empty_projections(owned_library)

    result = replay(owned_library)

    assert result.replayed_through == (
        LibraryEventStreamHead.objects.get(library=owned_library).current_sequence
    )
    assert rows_of(owned_library) == before
    assert rows_of(neighbour) == untouched
    #: Values alone cannot part untouched from upserted alike.
    assert row_versions(neighbour) == unwritten


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
    unwritten = row_versions(neighbour)
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
    #: Values alone cannot part untouched from upserted alike.
    assert row_versions(neighbour) == unwritten
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
    unwritten = row_versions(neighbour)
    empty_projections(owned_library)

    replay(owned_library)

    assert rows_of(owned_library) == before
    assert rows_of(neighbour) == untouched
    #: Values alone cannot part untouched from upserted alike.
    assert row_versions(neighbour) == unwritten


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


def test_the_display_number_is_ordered_by_a_total_key():
    """The key last is what a swap cannot renumber.

    A conversion stamps `recorded_at` from each legacy row's
    `created_at`, so two undated rows made in one instant tie on the
    first three sort fields. RowNumber over peers follows the plan's
    input order, and a swap changes that -- so the fourth field, which
    is unique, is the whole reason a rebuild leaves the numbers alone.
    """
    assert DISPLAY_ORDER[-1] == "id"


def test_the_stream_leaves_a_removed_row_in_each_table(owned_user, owned_library):
    """A restored row states no removed_at to compare."""
    build_stream(owned_user, owned_library)

    assert PlayerGame.objects.filter(
        library=owned_library, removed_at__isnull=False
    ).exists()
    assert Playthrough.objects.filter(
        library=owned_library, removed_at__isnull=False
    ).exists()


def test_the_gate_replays_every_reachable_playthrough_kind(
    owned_user, owned_library, django_user_model
):
    """A new kind fails here until a leg states it."""
    build_stream(owned_user, owned_library)
    #: Its own library: the backfill reads every game in one.
    converted = django_user_model.objects.create_user(
        username="gate-converted", password="p"
    )
    build_converted(converted.library)

    stated = set(
        Playthrough.objects.filter(
            library__in=(owned_library, converted.library)
        ).values_list("kind", flat=True)
    )

    assert stated == {kind for kind in PlaythroughKind} - UNREACHABLE_KINDS
