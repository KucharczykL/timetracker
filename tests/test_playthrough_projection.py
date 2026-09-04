"""One row per run at a game a library tracks."""

import uuid

import pytest
from django.db import connection, transaction
from django.utils import timezone

from games.checks import check_projection_models
from games.commands.playergame import TrackGame
from games.events.append import lock_stream
from games.events.dispatch import dispatch
from games.events.envelope import RecordedEvent
from games.events.playthrough import playthrough_created
from games.events.projection import DEFAULT_REGISTRY
from games.events.rebuild import RebuildMode, rebuild_projections
from games.events.replay import replay
from games.models import (
    Game,
    LibraryEvent,
    PlayerGame,
    Playthrough,
    PlaythroughKind,
)

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


def test_a_playthrough_starts_ordinary():
    assert Playthrough().kind == PlaythroughKind.ORDINARY


def test_a_playthrough_starts_unnamed():
    """A blank name is what the display number is for."""
    assert Playthrough().name == ""
    assert Playthrough().note == ""


def test_a_playthrough_starts_with_no_endpoints():
    """#681 states them."""
    assert Playthrough().started is None
    assert Playthrough().completed is None


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
    """The read-time numbering has an index behind it."""
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


def test_the_creation_event_has_a_current_state_handler():
    handlers = DEFAULT_REGISTRY.handlers_for("library.playthrough.created")

    assert len(handlers) == 1


def test_playergames_still_owns_its_own_events():
    """Two projectors in one family, each with its own act."""
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
    #: The model defaults, which no amendment has replaced yet.
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
    event = RecordedEvent.from_row(
        LibraryEvent.objects.get(aggregate_id=appended.events[0].aggregate_id)
    )

    with transaction.atomic():
        DEFAULT_REGISTRY.apply(event)

    assert Playthrough.objects.count() == 1


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
    """The foreign key between two projection tables and the generated
    columns, proven rather than argued."""
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
    """Why the swap's table order is not load-bearing.

    Django emits no ON DELETE clause, so the constraint is Postgres's
    default NO ACTION -- and deferred, so it is checked at COMMIT, after
    the swap has reinserted both tables.
    """
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
