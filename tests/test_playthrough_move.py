"""Moving a run to another game."""

import uuid
from datetime import date, timedelta

import pytest
from django.db import transaction

from games.commands.historical_playtime import (
    HistoricalPlaytimeStatement,
    RecordHistoricalPlaytime,
    RemoveHistoricalPlaytime,
)
from games.commands.playergame import RemovePlayerGame, TrackGame
from games.commands.playersession import CreateSession, DurationOnlyTiming
from games.commands.playthrough import (
    CreatePlaythrough,
    DescribePlaythrough,
    MovePlaythroughToGame,
    PlaythroughNotHeld,
    RemovePlaythrough,
)
from games.events.append import lock_stream
from games.events.dispatch import (
    CommandOutcome,
    CommandRejected,
    RowNotHeld,
    dispatch,
)
from games.events.playthrough import playthrough_created
from games.events.rebuild import RebuildMode, rebuild_projections
from games.models import (
    Game,
    HistoricalPlaytime,
    HistoricalPlaytimeProvenance,
    HistoricalPlaytimeRun,
    PlayerGame,
    PlayerSession,
    Playthrough,
    PlaythroughKind,
)
from games.reads.events import dispatched_events
from games.removal import remove

pytestmark = [
    pytest.mark.untracked_games,
    pytest.mark.django_db(transaction=True),
]


class Run:
    """Dispatches under fresh keys."""

    def __init__(self, user, library):
        self.user = user
        self.library = library

    def __call__(self, command):
        return dispatch(
            command,
            actor=self.user,
            library=self.library,
            idempotency_key=str(uuid.uuid7()),
        )


@pytest.fixture
def run(owned_user, owned_library):
    return Run(owned_user, owned_library)


@pytest.fixture
def base(owned_library, run):
    game = Game.objects.create(library=owned_library, name="Resident Evil 4")
    run(TrackGame(game_id=game.pk))
    return game


@pytest.fixture
def dlc(owned_library, run):
    game = Game.objects.create(library=owned_library, name="Separate Ways")
    run(TrackGame(game_id=game.pk))
    return game


def tracked(library, game):
    return PlayerGame.objects.get(library=library, game=game)


def live_runs(library, game):
    return list(
        Playthrough.objects.filter(
            library=library,
            player_game__game=game,
            removed_at__isnull=True,
            kind=PlaythroughKind.ORDINARY,
        ).order_by("created_at", "id")
    )


def sole_run(library, game):
    (only,) = live_runs(library, game)
    return only


def named_run(run, library, game, name):
    """A second run, named, so the first is not alone."""
    run(
        CreatePlaythrough(
            game_id=game.pk, implies_played=False, implies_completed=False
        )
    )
    newest = live_runs(library, game)[-1]
    run(DescribePlaythrough(playthrough_id=newest.pk, name=name, note=None))
    newest.refresh_from_db()
    return newest


def session_on(run, playthrough):
    run(
        CreateSession(
            playthrough_id=playthrough.pk,
            timing=DurationOnlyTiming(
                day=date(2024, 3, 1), duration=timedelta(hours=1)
            ),
            implies_played=False,
        )
    )


def record_on(run, library, *playthroughs):
    run(
        RecordHistoricalPlaytime(
            statement=HistoricalPlaytimeStatement(
                duration=timedelta(hours=10),
                when="2019",
                provenance=HistoricalPlaytimeProvenance.ESTIMATED,
                playthrough_ids=tuple(item.pk for item in playthroughs),
                device_id=None,
                release_id=None,
                emulated=False,
                note="",
            )
        )
    )
    return HistoricalPlaytime.objects.filter(library=library).latest("created_at")


def move(run, playthrough, game):
    return run(MovePlaythroughToGame(playthrough_id=playthrough.pk, game_id=game.pk))


def appended_types(result):
    return list(dispatched_events(result).values_list("event_type", flat=True))


def test_the_run_moves_with_its_sessions(owned_library, run, base, dlc):
    moving = named_run(run, owned_library, base, "Separate Ways run")
    session_on(run, moving)

    move(run, moving, dlc)

    moving.refresh_from_db()
    assert moving.player_game == tracked(owned_library, dlc)
    session = PlayerSession.objects.get(playthrough=moving)
    assert session.playthrough.player_game.game == dlc


def test_the_game_the_run_names_is_unchanged(owned_library, run, base):
    result = move(run, sole_run(owned_library, base), base)

    assert result.outcome is CommandOutcome.UNCHANGED


def test_unchanged_comes_before_a_removed_run(owned_library, run, base):
    removed = named_run(run, owned_library, base, "Gone")
    run(RemovePlaythrough(playthrough_id=removed.pk))

    result = move(run, removed, base)

    assert result.outcome is CommandOutcome.UNCHANGED


def test_a_removed_run_is_refused(owned_library, run, base, dlc):
    removed = named_run(run, owned_library, base, "Gone")
    run(RemovePlaythrough(playthrough_id=removed.pk))

    with pytest.raises(CommandRejected) as refusal:
        move(run, removed, dlc)

    assert "playthrough was removed" in refusal.value.sentence


def test_a_run_of_a_removed_game_is_refused(owned_library, run, base, dlc):
    moving = sole_run(owned_library, base)
    run(RemovePlayerGame(game_id=base.pk))

    with pytest.raises(CommandRejected) as refusal:
        move(run, moving, dlc)

    assert "game was removed" in refusal.value.sentence


def test_the_bucket_is_refused(owned_user, owned_library, run, base, dlc):
    with transaction.atomic():
        lock_stream(owned_library).append(
            [
                playthrough_created(
                    tracked(owned_library, base).pk, kind="imported_history"
                )
            ],
            actor=owned_user,
            correlation_id=uuid.uuid7(),
            idempotency_key="bucket",
        )
    bucket = Playthrough.objects.get(kind=PlaythroughKind.IMPORTED_HISTORY)

    with pytest.raises(CommandRejected) as refusal:
        move(run, bucket, dlc)

    assert "imported-history" in refusal.value.sentence


def test_a_removed_target_is_refused_with_the_restore(owned_library, run, base, dlc):
    run(RemovePlayerGame(game_id=dlc.pk))

    with pytest.raises(CommandRejected) as refusal:
        move(run, named_run(run, owned_library, base, "DLC"), dlc)

    assert "Restore" in refusal.value.sentence


def test_a_removed_shared_target_is_refused_with_the_restore(owned_library, run, base):
    shared = Game.objects.create(library=None, name="Assignment Ada")
    run(TrackGame(game_id=shared.pk))
    run(RemovePlayerGame(game_id=shared.pk))

    with pytest.raises(CommandRejected) as refusal:
        move(run, named_run(run, owned_library, base, "Ada"), shared)

    assert "Restore" in refusal.value.sentence


def test_a_target_the_library_cannot_see_is_absent(
    owned_library, django_user_model, run, base
):
    stranger = django_user_model.objects.create_user(username="stranger")
    foreign = Game.objects.create(library=stranger.library, name="Not yours")

    with pytest.raises(RowNotHeld):
        move(run, named_run(run, owned_library, base, "Lost"), foreign)


def test_an_unknown_run_is_absent(run, base):
    with pytest.raises(PlaythroughNotHeld):
        run(MovePlaythroughToGame(playthrough_id=uuid.uuid7(), game_id=base.pk))


def test_an_untracked_target_is_tracked_without_a_placeholder(owned_library, run, base):
    untracked = Game.objects.create(library=owned_library, name="Separate Ways")
    moving = named_run(run, owned_library, base, "DLC")

    result = move(run, moving, untracked)

    assert appended_types(result) == [
        "library.playergame.created",
        "library.playthrough.moved",
    ]
    assert live_runs(owned_library, untracked) == [moving]


def test_the_target_placeholder_is_removed(owned_library, run, base, dlc):
    placeholder = sole_run(owned_library, dlc)
    moving = named_run(run, owned_library, base, "DLC")

    move(run, moving, dlc)

    placeholder.refresh_from_db()
    assert placeholder.removed_at is not None
    assert live_runs(owned_library, dlc) == [moving]


def test_a_named_target_run_stays(owned_library, run, base, dlc):
    kept = sole_run(owned_library, dlc)
    run(DescribePlaythrough(playthrough_id=kept.pk, name="Mine", note=None))
    moving = named_run(run, owned_library, base, "DLC")

    move(run, moving, dlc)

    assert live_runs(owned_library, dlc) == [kept, moving]


def test_a_target_run_with_a_session_stays(owned_library, run, base, dlc):
    kept = sole_run(owned_library, dlc)
    session_on(run, kept)
    moving = named_run(run, owned_library, base, "DLC")

    move(run, moving, dlc)

    assert live_runs(owned_library, dlc) == [kept, moving]


def test_a_bare_source_gets_a_placeholder(owned_library, run, base, dlc):
    moving = sole_run(owned_library, base)

    result = move(run, moving, dlc)

    assert appended_types(result)[-1] == "library.playthrough.created"
    left = sole_run(owned_library, base)
    assert left != moving
    assert (left.name, left.started, left.completed) == ("", None, None)


def test_a_source_with_another_run_gets_none(owned_library, run, base, dlc):
    stays = sole_run(owned_library, base)
    moving = named_run(run, owned_library, base, "DLC")

    move(run, moving, dlc)

    assert live_runs(owned_library, base) == [stays]


def test_a_record_naming_the_run_alone_follows_it(owned_library, run, base, dlc):
    moving = named_run(run, owned_library, base, "DLC")
    record = record_on(run, owned_library, moving)
    join = HistoricalPlaytimeRun.objects.get(record=record)

    move(run, moving, dlc)

    record.refresh_from_db()
    assert record.player_game == tracked(owned_library, dlc)
    assert record.restated_at is None
    assert HistoricalPlaytimeRun.objects.get(record=record).pk == join.pk


def test_a_removed_record_follows_too(owned_library, run, base, dlc):
    moving = named_run(run, owned_library, base, "DLC")
    record = record_on(run, owned_library, moving)
    run(RemoveHistoricalPlaytime(record_id=record.pk))

    move(run, moving, dlc)

    record.refresh_from_db()
    assert record.player_game == tracked(owned_library, dlc)


def test_a_record_shared_with_another_run_refuses_the_move(
    owned_library, run, base, dlc
):
    stays = sole_run(owned_library, base)
    moving = named_run(run, owned_library, base, "DLC")
    record_on(run, owned_library, stays, moving)

    with pytest.raises(CommandRejected) as refusal:
        move(run, moving, dlc)

    assert "historical playtime" in refusal.value.sentence


def test_a_removed_shared_record_names_the_restore(owned_library, run, base, dlc):
    stays = sole_run(owned_library, base)
    moving = named_run(run, owned_library, base, "DLC")
    record = record_on(run, owned_library, stays, moving)
    run(RemoveHistoricalPlaytime(record_id=record.pk))

    with pytest.raises(CommandRejected) as refusal:
        move(run, moving, dlc)

    assert "Restore" in refusal.value.sentence


def test_an_untracked_shared_target_is_tracked(owned_library, run, base):
    shared = Game.objects.create(library=None, name="Assignment Ada")
    moving = named_run(run, owned_library, base, "Ada")

    move(run, moving, shared)

    assert live_runs(owned_library, shared) == [moving]


def test_an_untracked_removed_catalog_game_is_absent(owned_library, run, base):
    gone = Game.objects.create(library=owned_library, name="Gone")
    remove(gone)

    with pytest.raises(RowNotHeld):
        move(run, named_run(run, owned_library, base, "Gone"), gone)


def test_both_placeholders_swap_in_one_dispatch(owned_library, run, base, dlc):
    result = move(run, sole_run(owned_library, base), dlc)

    assert appended_types(result) == [
        "library.playthrough.moved",
        "library.playthrough.removed",
        "library.playthrough.created",
    ]


def test_a_rebuild_keeps_the_moved_game(owned_library, run, base, dlc):
    """The creation names the old game; the move wins."""
    moving = named_run(run, owned_library, base, "DLC")
    record = record_on(run, owned_library, moving)
    move(run, moving, dlc)

    report = rebuild_projections(owned_library, mode=RebuildMode.REBUILD)

    assert all(table.differing == 0 for table in report.tables)
    moving.refresh_from_db()
    record.refresh_from_db()
    assert moving.player_game == tracked(owned_library, dlc)
    assert record.player_game == tracked(owned_library, dlc)
