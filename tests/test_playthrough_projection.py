"""One row per run at a game."""

import uuid
from datetime import date

import pytest
from django.db import connection, transaction
from django.utils import timezone

from games.checks import check_projection_models
from games.commands.playergame import TrackGame
from games.commands.playthrough import CompletePlaythrough, StartPlaythrough
from games.events.append import lock_stream
from games.events.dispatch import dispatch
from games.events.envelope import RecordedEvent
from games.events.playthrough import (
    playthrough_completion_corrected,
    playthrough_created,
    playthrough_name_changed,
    playthrough_note_changed,
    playthrough_start_corrected,
)
from games.events.projection import DEFAULT_REGISTRY, _required_columns
from games.events.rebuild import RebuildMode, rebuild_projections
from games.events.replay import replay
from games.models import (
    Game,
    LibraryEvent,
    PlayerGame,
    Playthrough,
    PlaythroughKind,
)
from timetracker.temporal import TemporalValue

pytestmark = pytest.mark.untracked_games


def test_playthrough_is_a_pure_projection():
    """Nothing in the row predates the event."""
    complaints = [
        str(message.id)
        for message in check_projection_models()
        if message.obj is Playthrough
    ]

    assert complaints == []


def test_the_identity_has_no_default():
    #: The key is the event's aggregate_id.
    assert Playthrough().id is None


def test_the_kind_has_no_default():
    """The event states it, so nothing else may.

    A default would exempt the column from `_required_columns`, and a
    handler that stopped naming it would write the default on the live
    path and on a rebuild alike, agreeing with itself and with nothing
    the event recorded.
    """
    assert not Playthrough._meta.get_field("kind").has_default()
    assert "kind" in {name for name, _ in _required_columns(Playthrough)}


def test_a_playthrough_starts_unnamed():
    """A blank name, for the display number."""
    assert Playthrough().name == ""
    assert Playthrough().note == ""


def test_a_playthrough_starts_with_no_endpoints():
    """The date of a run nobody has stated yet."""
    assert Playthrough().started is None
    assert Playthrough().completed is None


def test_a_playthrough_starts_with_neither_act_recorded():
    """The marker's null is the act that never happened.

    A null date cannot say it: `TemporalValue.unknown()` serializes to
    None, so the date column reads the same for an unknown day.
    """
    row = Playthrough()

    assert row.start_recorded_at is None
    assert row.completion_recorded_at is None


def test_a_playthrough_starts_with_no_endpoint_notes():
    row = Playthrough()

    assert (row.start_note, row.completion_note) == ("", "")


def test_the_endpoint_columns_are_exempt_from_the_required_ones():
    """The creation handler names none of them, and must not.

    Each carries a default, so `_required_columns` exempts it and the
    handler #679 wrote stays as it is.
    """
    required = {name for name, _ in _required_columns(Playthrough)}

    assert required.isdisjoint(
        {
            "started",
            "completed",
            "start_recorded_at",
            "completion_recorded_at",
            "start_note",
            "completion_note",
        }
    )


def test_a_playthrough_starts_live():
    assert Playthrough().removed_at is None


def test_the_bound_columns_are_generated():
    """Never written from application code."""
    generated = {
        field.name for field in Playthrough._meta.concrete_fields if field.generated
    }

    assert generated == {
        "started_lower",
        "started_upper",
        "completed_lower",
        "completed_upper",
    }


def test_the_display_order_index_covers_every_sort_key():
    """The read-time numbering has an index."""
    covering = [
        index
        for index in Playthrough._meta.indexes
        if index.fields
        == [
            "player_game",
            "started_lower",
            "completed_lower",
            "created_at",
            "id",
        ]
    ]

    assert len(covering) == 1


def append_playthrough_created(library, actor, tracked, *, key="create"):
    """Append one creation event, as dispatch would."""
    with transaction.atomic():
        stream = lock_stream(library)
        return stream.append(
            [playthrough_created(tracked.pk)],
            actor=actor,
            correlation_id=uuid.uuid7(),
            idempotency_key=key,
        )


def reapply_creation(identity):
    """Hand the recorded creation event to the projectors a second time."""
    event = RecordedEvent.from_row(LibraryEvent.objects.get(aggregate_id=identity))
    with transaction.atomic():
        DEFAULT_REGISTRY.apply(event)


def test_the_creation_event_has_a_current_state_handler():
    handlers = DEFAULT_REGISTRY.handlers_for("library.playthrough.created")

    assert len(handlers) == 1


def test_playergames_still_owns_its_own_events():
    """Two projectors in one family, two acts."""
    assert len(DEFAULT_REGISTRY.handlers_for("library.playergame.created")) == 1


@pytest.fixture
def tracked(owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    return PlayerGame.objects.create(
        id=uuid.uuid7(),
        library=owned_library,
        game=game,
        tracked_at=timezone.now(),
    )


@pytest.mark.django_db(transaction=True)
def test_the_creation_event_writes_the_row(owned_user, owned_library, tracked):
    appended = append_playthrough_created(owned_library, owned_user, tracked)

    row = Playthrough.objects.get()
    assert (row.player_game_id, row.library_id) == (tracked.pk, owned_library.pk)
    assert row.pk == appended.events[0].aggregate_id
    assert row.kind == PlaythroughKind.ORDINARY
    assert row.created_at == appended.events[0].recorded_at
    #: The model defaults, no amendment yet.
    assert (row.name, row.note, row.started, row.completed, row.removed_at) == (
        "",
        "",
        None,
        None,
        None,
    )


@pytest.mark.django_db(transaction=True)
def test_applying_the_creation_event_twice_writes_one_row(
    owned_user, owned_library, tracked
):
    """The write is keyed on aggregate_id."""
    appended = append_playthrough_created(owned_library, owned_user, tracked)

    reapply_creation(appended.events[0].aggregate_id)

    assert Playthrough.objects.count() == 1


@pytest.mark.django_db(transaction=True)
def test_re_applying_the_creation_event_leaves_an_amendment_alone(
    owned_user, owned_library, tracked
):
    """The handler names four columns, and no more.

    `project` passes `update_fields=list(columns)`, so a column the
    handler leaves out survives. The endpoint, name, note and
    correction handlers amend the rest, and the creation event
    carries the lowest sequence,
    so a rebuild replays it first and their events land on top. What
    this holds is the live path, where the same event reaches the
    handler against a row their amendments already changed. Every
    endpoint column needs holding: each carries a default, so
    `_required_columns` exempts it and would let the handler name it
    unnoticed.
    """
    appended = append_playthrough_created(owned_library, owned_user, tracked)
    identity = appended.events[0].aggregate_id
    amended = timezone.now()
    started = TemporalValue.from_year(2024)
    completed = TemporalValue.from_year(2025)
    Playthrough.objects.filter(pk=identity).update(
        name="Blind run",
        note="No hints",
        started=started,
        start_recorded_at=amended,
        start_note="Began here",
        completed=completed,
        completion_recorded_at=amended,
        completion_note="Ended here",
        removed_at=amended,
    )

    reapply_creation(identity)

    row = Playthrough.objects.get()
    assert (
        row.name,
        row.note,
        row.started,
        row.start_recorded_at,
        row.start_note,
        row.completed,
        row.completion_recorded_at,
        row.completion_note,
        row.removed_at,
    ) == (
        "Blind run",
        "No hints",
        started,
        amended,
        "Began here",
        completed,
        amended,
        "Ended here",
        amended,
    )


def track(owned_user, owned_library, game, key="track"):
    return dispatch(
        TrackGame(game_id=game.pk),
        actor=owned_user,
        library=owned_library,
        idempotency_key=key,
    )


@pytest.mark.django_db(transaction=True)
def test_an_empty_database_replay_reproduces_both_tables(owned_user, owned_library):
    """Nothing in either row predates its event."""
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    track(owned_user, owned_library, game)
    before = (
        list(PlayerGame.objects.order_by("pk").values()),
        list(Playthrough.objects.order_by("pk").values()),
    )
    #: The child first: player_game RESTRICTs.
    Playthrough.objects.all().delete()
    PlayerGame.objects.all().delete()

    replay(owned_library)

    assert (
        list(PlayerGame.objects.order_by("pk").values()),
        list(Playthrough.objects.order_by("pk").values()),
    ) == before


@pytest.mark.django_db(transaction=True)
def test_a_rebuild_swaps_both_tables_with_an_empty_diff(owned_user, owned_library):
    """The projection foreign key and generated columns."""
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    track(owned_user, owned_library, game)

    report = rebuild_projections(owned_library, mode=RebuildMode.REBUILD)

    assert report.swapped is True
    #: Both tables, each agreeing with its rebuild.
    assert [
        (table.table, table.only_live, table.only_rebuilt, table.differing)
        for table in report.tables
    ] == [
        ("games_playergame", 0, 0, 0),
        ("games_playthrough", 0, 0, 0),
    ]
    assert (PlayerGame.objects.count(), Playthrough.objects.count()) == (1, 1)


@pytest.mark.django_db
def test_the_foreign_key_to_playergame_is_deferred():
    """Why the swap's table order does not matter."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT condeferrable, condeferred, confdeltype
            FROM pg_constraint
            WHERE conrelid = 'games_playthrough'::regclass
              AND contype = 'f'
              AND confrelid = 'games_playergame'::regclass
            """
        )
        rows = cursor.fetchall()

    assert rows == [(True, True, "a")]


@pytest.mark.django_db(transaction=True)
def test_a_started_event_writes_the_date_the_marker_and_the_note(
    owned_user, owned_library
):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    track(owned_user, owned_library, game)
    run = Playthrough.objects.get()

    dispatch(
        StartPlaythrough(
            playthrough_id=run.pk,
            when=TemporalValue.from_month(2024, 3),
            note="blind run",
        ),
        actor=owned_user,
        library=owned_library,
        idempotency_key="start",
    )

    row = Playthrough.objects.get()
    event = LibraryEvent.objects.get(event_type="library.playthrough.started")
    assert row.started == TemporalValue.from_month(2024, 3)
    assert row.start_recorded_at == event.recorded_at
    assert row.start_note == "blind run"
    #: The other endpoint is untouched: two handlers read alike.
    assert (row.completed, row.completion_recorded_at, row.completion_note) == (
        None,
        None,
        "",
    )


@pytest.mark.django_db(transaction=True)
def test_played_before_reads_back_as_an_act_with_no_day(owned_user, owned_library):
    """The marker carries the act; the date carries nothing."""
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    track(owned_user, owned_library, game)
    run = Playthrough.objects.get()

    dispatch(
        StartPlaythrough(playthrough_id=run.pk, when=None, note=""),
        actor=owned_user,
        library=owned_library,
        idempotency_key="start",
    )

    row = Playthrough.objects.get()
    assert row.started is None
    assert row.start_recorded_at is not None


@pytest.mark.django_db(transaction=True)
def test_a_completed_event_leaves_the_start_alone(owned_user, owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    track(owned_user, owned_library, game)
    run = Playthrough.objects.get()
    dispatch(
        StartPlaythrough(
            playthrough_id=run.pk, when=TemporalValue.from_month(2024, 3), note="blind"
        ),
        actor=owned_user,
        library=owned_library,
        idempotency_key="start",
    )

    dispatch(
        CompletePlaythrough(
            playthrough_id=run.pk,
            when=TemporalValue.from_day(date(2024, 4, 2)),
            note="hard mode",
        ),
        actor=owned_user,
        library=owned_library,
        idempotency_key="done",
    )

    row = Playthrough.objects.get()
    assert (row.started, row.start_note) == (TemporalValue.from_month(2024, 3), "blind")
    assert row.completed == TemporalValue.from_day(date(2024, 4, 2))
    assert row.completion_note == "hard mode"
    assert row.completion_recorded_at is not None


@pytest.mark.django_db(transaction=True)
def test_an_empty_database_replay_reproduces_both_endpoints(owned_user, owned_library):
    """Every written value comes off the event, so a replay agrees."""
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    track(owned_user, owned_library, game)
    run = Playthrough.objects.get()
    for command, key in (
        (
            StartPlaythrough(
                playthrough_id=run.pk, when=TemporalValue.from_month(2024, 3), note="a"
            ),
            "start",
        ),
        (CompletePlaythrough(playthrough_id=run.pk, when=None, note="b"), "done"),
    ):
        dispatch(command, actor=owned_user, library=owned_library, idempotency_key=key)
    before = list(Playthrough.objects.order_by("pk").values())
    #: The child first: player_game RESTRICTs.
    Playthrough.objects.all().delete()
    PlayerGame.objects.all().delete()

    replay(owned_library)

    assert list(Playthrough.objects.order_by("pk").values()) == before


def append_about_run(library, actor, event, *, key):
    """Append one event about a run that exists, as dispatch would."""
    with transaction.atomic():
        stream = lock_stream(library)
        return stream.append(
            [event],
            actor=actor,
            correlation_id=uuid.uuid7(),
            idempotency_key=key,
        )


def started_run(owned_user, owned_library, *, when, note="first"):
    """A tracked game with one run, whose start is stated."""
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    track(owned_user, owned_library, game)
    run = Playthrough.objects.get()
    dispatch(
        StartPlaythrough(playthrough_id=run.pk, when=when, note=note),
        actor=owned_user,
        library=owned_library,
        idempotency_key="start",
    )
    return run


def _describe_and_correct(owned_user, owned_library, run):
    """One event of every descriptive and corrective kind."""
    dispatch(
        CompletePlaythrough(
            playthrough_id=run.pk, when=TemporalValue.from_year(2024), note="done"
        ),
        actor=owned_user,
        library=owned_library,
        idempotency_key="done",
    )
    for event, key in (
        (playthrough_name_changed(run.pk, name="Ironman"), "rename"),
        (playthrough_note_changed(run.pk, note="no saves"), "note"),
        (
            playthrough_start_corrected(run.pk, when=None, note="a guess"),
            "correct-start",
        ),
        (
            playthrough_completion_corrected(
                run.pk, when=TemporalValue.from_day(date(2024, 4, 2)), note="hard mode"
            ),
            "correct-completion",
        ),
    ):
        append_about_run(owned_library, owned_user, event, key=key)


@pytest.mark.django_db(transaction=True)
def test_a_rename_writes_the_name_and_nothing_else(owned_user, owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    track(owned_user, owned_library, game)
    run = Playthrough.objects.get()

    append_about_run(
        owned_library,
        owned_user,
        playthrough_name_changed(run.pk, name="Ironman"),
        key="rename",
    )

    row = Playthrough.objects.get()
    assert row.name == "Ironman"
    #: Two facts, two handlers, and neither writes the other.
    assert row.note == ""


@pytest.mark.django_db(transaction=True)
def test_a_note_change_writes_the_note_and_nothing_else(owned_user, owned_library):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    track(owned_user, owned_library, game)
    run = Playthrough.objects.get()

    append_about_run(
        owned_library,
        owned_user,
        playthrough_note_changed(run.pk, note="no saves"),
        key="note",
    )

    row = Playthrough.objects.get()
    assert row.note == "no saves"
    assert row.name == ""


@pytest.mark.django_db(transaction=True)
def test_a_corrected_start_replaces_the_date_and_keeps_the_marker(
    owned_user, owned_library
):
    """The act happened once; only the day it names was wrong."""
    run = started_run(owned_user, owned_library, when=TemporalValue.from_year(2023))
    stated_at = LibraryEvent.objects.get(
        event_type="library.playthrough.started"
    ).recorded_at

    append_about_run(
        owned_library,
        owned_user,
        playthrough_start_corrected(
            run.pk, when=TemporalValue.from_year(2024), note="second look"
        ),
        key="correct-start",
    )

    row = Playthrough.objects.get()
    assert row.started == TemporalValue.from_year(2024)
    assert row.start_note == "second look"
    assert row.start_recorded_at == stated_at
    #: The other endpoint stays the one nobody stated.
    assert (row.completed, row.completion_recorded_at, row.completion_note) == (
        None,
        None,
        "",
    )


@pytest.mark.django_db(transaction=True)
def test_a_corrected_completion_replaces_the_date_and_keeps_the_marker(
    owned_user, owned_library
):
    game = Game.objects.create(library=owned_library, name="Outer Wilds")
    track(owned_user, owned_library, game)
    run = Playthrough.objects.get()
    dispatch(
        CompletePlaythrough(
            playthrough_id=run.pk, when=TemporalValue.from_year(2023), note="done"
        ),
        actor=owned_user,
        library=owned_library,
        idempotency_key="done",
    )
    stated_at = LibraryEvent.objects.get(
        event_type="library.playthrough.completed"
    ).recorded_at

    append_about_run(
        owned_library,
        owned_user,
        playthrough_completion_corrected(
            run.pk, when=TemporalValue.from_day(date(2024, 4, 2)), note="hard mode"
        ),
        key="correct-completion",
    )

    row = Playthrough.objects.get()
    assert row.completed == TemporalValue.from_day(date(2024, 4, 2))
    assert row.completion_note == "hard mode"
    assert row.completion_recorded_at == stated_at
    assert (row.started, row.start_recorded_at, row.start_note) == (None, None, "")


@pytest.mark.django_db(transaction=True)
def test_a_correction_reads_back_an_unknown_day_as_the_act_alone(
    owned_user, owned_library
):
    """A stated day, corrected to a day nobody knows."""
    run = started_run(owned_user, owned_library, when=TemporalValue.from_year(2023))

    append_about_run(
        owned_library,
        owned_user,
        playthrough_start_corrected(run.pk, when=None, note=""),
        key="correct-start",
    )

    row = Playthrough.objects.get()
    assert row.started is None
    assert row.start_recorded_at is not None


@pytest.mark.django_db(transaction=True)
def test_a_replay_keeps_the_instant_the_start_was_recorded(owned_user, owned_library):
    """A correction states a better date, not a second act."""
    run = started_run(owned_user, owned_library, when=TemporalValue.from_year(2023))
    append_about_run(
        owned_library,
        owned_user,
        playthrough_start_corrected(
            run.pk, when=TemporalValue.from_year(2024), note="second look"
        ),
        key="correct-start",
    )
    #: Off the event, so a marker the handler moved is caught.
    stated_at = LibraryEvent.objects.get(
        event_type="library.playthrough.started"
    ).recorded_at
    #: The child first: player_game RESTRICTs.
    Playthrough.objects.all().delete()
    PlayerGame.objects.all().delete()

    replay(owned_library)

    rebuilt = Playthrough.objects.get(pk=run.pk)
    assert rebuilt.start_recorded_at == stated_at
    assert rebuilt.started == TemporalValue.from_year(2024)


@pytest.mark.django_db(transaction=True)
def test_an_empty_database_replay_reproduces_a_described_run(owned_user, owned_library):
    """Every written value comes off the event, so a replay agrees."""
    run = started_run(owned_user, owned_library, when=TemporalValue.from_year(2023))
    _describe_and_correct(owned_user, owned_library, run)
    before = list(Playthrough.objects.order_by("pk").values())
    #: The child first: player_game RESTRICTs.
    Playthrough.objects.all().delete()
    PlayerGame.objects.all().delete()

    replay(owned_library)

    assert list(Playthrough.objects.order_by("pk").values()) == before


@pytest.mark.django_db(transaction=True)
def test_a_rebuild_of_a_described_run_swaps_with_an_empty_diff(
    owned_user, owned_library
):
    """The shadow table, over a row every handler has written."""
    run = started_run(owned_user, owned_library, when=TemporalValue.from_year(2023))
    _describe_and_correct(owned_user, owned_library, run)

    report = rebuild_projections(owned_library, mode=RebuildMode.REBUILD)

    assert report.swapped is True
    assert [
        (table.table, table.only_live, table.only_rebuilt, table.differing)
        for table in report.tables
    ] == [
        ("games_playergame", 0, 0, 0),
        ("games_playthrough", 0, 0, 0),
    ]
