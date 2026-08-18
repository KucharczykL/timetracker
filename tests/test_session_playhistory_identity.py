import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from django.core.management import call_command
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

from games.api import AutoPlayEventIn
from games.forms import GameStatusChangeForm, PlayEventForm, SessionForm
from games.models import Game, GameStatusChange, PlayEvent, Session
from games.views.session import clone_session_by_id

pytestmark = pytest.mark.django_db(transaction=True)

BEFORE_IDENTITY = ("games", "0005_catalog_uuid_identity")
WITH_IDENTITY = ("games", "0006_session_playhistory_uuid_identity")


def floor_ms(moment: datetime) -> int:
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    elapsed = moment - epoch
    return (
        elapsed.days * 86_400_000
        + elapsed.seconds * 1000
        + elapsed.microseconds // 1000
    )


def raw_insert_without_uuid(model, **field_values):
    """INSERT a row through raw SQL that omits the `uuid` column entirely,
    so PostgreSQL's own `uuidv7()` column default fills it in - the only
    way to exercise `db_default`, since the ORM always resolves the field's
    Python `default` first and never leaves the column to the database.
    """
    instance = model(**field_values)
    fields = [
        field
        for field in model._meta.local_concrete_fields
        if field.name != "uuid" and not field.primary_key and not field.generated
    ]
    columns = ", ".join(f'"{field.column}"' for field in fields)
    placeholders = ", ".join(["%s"] * len(fields))
    # pre_save() resolves auto_now/auto_now_add fields the way a real save
    # would; every other field returns its already-set attribute value.
    values = [field.get_prep_value(field.pre_save(instance, True)) for field in fields]
    with connection.cursor() as cursor:
        cursor.execute(
            f'INSERT INTO "{model._meta.db_table}" ({columns}) '
            f'VALUES ({placeholders}) RETURNING "uuid"',
            values,
        )
        return uuid.UUID(str(cursor.fetchone()[0]))


@pytest.fixture
def game(owned_library):
    return Game.objects.create(library=owned_library, name="Identity Subject")


# --- Field contract ---------------------------------------------------------


def test_session_created_through_the_orm_gets_a_distinct_version_7_uuid(game):
    first = Session.objects.create(game=game, timestamp_start=timezone.now())
    second = Session.objects.create(game=game, timestamp_start=timezone.now())
    assert first.uuid.version == 7
    assert second.uuid.version == 7
    assert first.uuid != second.uuid


def test_playevent_created_through_the_orm_gets_a_distinct_version_7_uuid(game):
    first = PlayEvent.objects.create(game=game, started=date(2024, 1, 1))
    second = PlayEvent.objects.create(game=game, started=date(2024, 1, 2))
    assert first.uuid.version == 7
    assert second.uuid.version == 7
    assert first.uuid != second.uuid


def test_gamestatuschange_created_through_the_orm_gets_a_distinct_version_7_uuid(game):
    first = GameStatusChange.objects.create(
        game=game, old_status="u", new_status="p", timestamp=timezone.now()
    )
    second = GameStatusChange.objects.create(
        game=game, old_status="p", new_status="f", timestamp=timezone.now()
    )
    assert first.uuid.version == 7
    assert second.uuid.version == 7
    assert first.uuid != second.uuid


def test_raw_session_insert_omitting_uuid_gets_the_database_default(game):
    session_uuid = raw_insert_without_uuid(
        Session, game=game, timestamp_start=timezone.now(), note="Raw Session"
    )
    assert session_uuid.version == 7
    assert Session.objects.get(uuid=session_uuid).note == "Raw Session"


def test_raw_playevent_insert_omitting_uuid_gets_the_database_default(game):
    playevent_uuid = raw_insert_without_uuid(PlayEvent, game=game, note="Raw PlayEvent")
    assert playevent_uuid.version == 7
    assert PlayEvent.objects.get(uuid=playevent_uuid).note == "Raw PlayEvent"


def test_raw_gamestatuschange_insert_omitting_uuid_gets_the_database_default(game):
    change_uuid = raw_insert_without_uuid(
        GameStatusChange, game=game, old_status="u", new_status="p", timestamp=None
    )
    assert change_uuid.version == 7
    assert GameStatusChange.objects.get(uuid=change_uuid).new_status == "p"


def test_cloning_a_session_mints_a_new_uuid(game, owned_library):
    source = Session.objects.create(game=game, timestamp_start=timezone.now())
    clone = clone_session_by_id(source.pk, owned_library)
    assert clone.pk != source.pk
    assert clone.uuid != Session.objects.get(pk=source.pk).uuid
    assert clone.uuid.version == 7


def test_database_rejects_a_duplicate_session_uuid(game):
    shared = uuid.uuid7()
    Session.objects.create(game=game, timestamp_start=timezone.now(), uuid=shared)
    with pytest.raises(IntegrityError), transaction.atomic():
        Session.objects.create(game=game, timestamp_start=timezone.now(), uuid=shared)


def test_database_rejects_a_duplicate_playevent_uuid(game):
    shared = uuid.uuid7()
    PlayEvent.objects.create(game=game, uuid=shared)
    with pytest.raises(IntegrityError), transaction.atomic():
        PlayEvent.objects.create(game=game, uuid=shared)


def test_database_rejects_a_duplicate_gamestatuschange_uuid(game):
    shared = uuid.uuid7()
    GameStatusChange.objects.create(game=game, new_status="p", uuid=shared)
    with pytest.raises(IntegrityError), transaction.atomic():
        GameStatusChange.objects.create(game=game, new_status="f", uuid=shared)


def test_database_rejects_a_non_v7_session_uuid(game):
    with pytest.raises(IntegrityError), transaction.atomic():
        Session.objects.create(
            game=game, timestamp_start=timezone.now(), uuid=uuid.uuid4()
        )


def test_database_rejects_a_non_v7_playevent_uuid(game):
    with pytest.raises(IntegrityError), transaction.atomic():
        PlayEvent.objects.create(game=game, uuid=uuid.uuid4())


def test_database_rejects_a_non_v7_gamestatuschange_uuid(game):
    with pytest.raises(IntegrityError), transaction.atomic():
        GameStatusChange.objects.create(game=game, new_status="p", uuid=uuid.uuid4())


# --- Invisibility ------------------------------------------------------------


def test_uuid_is_absent_from_session_form_fields():
    assert "uuid" not in SessionForm.base_fields


def test_uuid_is_absent_from_playevent_form_fields():
    assert "uuid" not in PlayEventForm.base_fields


def test_uuid_is_absent_from_gamestatuschange_form_fields():
    assert "uuid" not in GameStatusChangeForm.base_fields


def test_uuid_is_absent_from_the_playevent_model_schema():
    """`AutoPlayEventIn` is the one `ModelSchema` over a model this cutover
    touches, so its generated fields are asserted directly rather than argued
    from "no ModelSchema covers these models".
    """
    assert "uuid" not in AutoPlayEventIn.model_fields


def test_autoplayeventin_game_field_type_still_follows_games_primary_key():
    """`django_ninja`'s `ModelSchema` infers a relation field's type from
    `field.related_model._meta.pk.get_internal_type()`
    (`ninja/orm/fields.py`), not from the FK's `to_field` - so even though
    `PlayEvent.game` now resolves through `Game.uuid`, the generated `game`
    field silently stays `int`, matching `Game`'s untouched integer primary
    key rather than the UUID the column actually stores. Left as a trap for
    whoever wires this dead schema up; see "Follow-ups" in the design spec.
    """
    assert AutoPlayEventIn.model_fields["game"].annotation is int


# --- Migration: forward backfill --------------------------------------------


def table_columns(table_name: str) -> set[str]:
    with connection.cursor() as cursor:
        description = connection.introspection.get_table_description(cursor, table_name)
    return {column.name for column in description}


def create_row_at(apps, model_name: str, *, created_at: datetime, **field_values):
    """Create a historical-model row and force its `auto_now_add` `created_at`."""
    model = apps.get_model("games", model_name)
    row = model.objects.create(**field_values)
    model.objects.filter(pk=row.pk).update(created_at=created_at)
    row.refresh_from_db()
    return row


@pytest.fixture
def identity_harness():
    # Migrating down to BEFORE_IDENTITY unapplies every later migration too, so
    # the restore target is the graph's leaf nodes rather than WITH_IDENTITY,
    # which would strand this worker's shared database behind head for every
    # later test that reuses it.
    leaf_nodes = MigrationExecutor(connection).loader.graph.leaf_nodes()
    executor = MigrationExecutor(connection)
    executor.migrate([BEFORE_IDENTITY])
    call_command("flush", interactive=False, verbosity=0)
    old_apps = executor.loader.project_state([BEFORE_IDENTITY]).apps
    yield old_apps
    MigrationExecutor(connection).migrate(leaf_nodes)


def migrate_to_identity():
    executor = MigrationExecutor(connection)
    executor.migrate([WITH_IDENTITY])
    return executor.loader.project_state([WITH_IDENTITY]).apps


def seed_owned_game(apps, *, username: str):
    User = apps.get_model("auth", "User")
    UserLibrary = apps.get_model("games", "UserLibrary")
    Game = apps.get_model("games", "Game")
    user = User.objects.create(username=username)
    library = UserLibrary.objects.create(user_id=user.pk, created_at=timezone.now())
    return Game.objects.create(library_id=library.pk, name="Historic Game")


def test_forward_migration_backfills_every_row_with_a_distinct_ordered_uuid(
    identity_harness, capsys
):
    apps = identity_harness
    game = seed_owned_game(apps, username="identity-owner")

    tied_ms = datetime(2024, 6, 1, 12, 0, 0, 500_000, tzinfo=UTC)
    later = datetime(2024, 6, 1, 12, 0, 1, 0, tzinfo=UTC)

    # session_late is created first (lowest pk) but stamped with the latest
    # created_at, so order_by("created_at", "pk") must disagree with
    # creation/pk order - the "one row out of primary-key order" case.
    session_late = create_row_at(
        apps,
        "Session",
        game_id=game.pk,
        timestamp_start=later,
        created_at=later,
    )
    session_tied_a = create_row_at(
        apps, "Session", game_id=game.pk, timestamp_start=tied_ms, created_at=tied_ms
    )
    session_tied_b = create_row_at(
        apps, "Session", game_id=game.pk, timestamp_start=tied_ms, created_at=tied_ms
    )

    playevent_tied_a = create_row_at(
        apps, "PlayEvent", game_id=game.pk, created_at=tied_ms
    )
    playevent_tied_b = create_row_at(
        apps, "PlayEvent", game_id=game.pk, created_at=tied_ms
    )
    playevent_late = create_row_at(apps, "PlayEvent", game_id=game.pk, created_at=later)

    new_apps = migrate_to_identity()
    Session = new_apps.get_model("games", "Session")
    PlayEvent = new_apps.get_model("games", "PlayEvent")

    sessions = list(Session.objects.order_by("pk"))
    playevents = list(PlayEvent.objects.order_by("pk"))

    for rows in (sessions, playevents):
        assert all(row.uuid is not None for row in rows)
        assert len({row.uuid for row in rows}) == len(rows)
        assert all(row.uuid.version == 7 for row in rows)
        for row in rows:
            assert row.uuid.time == floor_ms(row.created_at)

    for model in (Session, PlayEvent):
        assert list(
            model.objects.order_by("uuid").values_list("pk", flat=True)
        ) == list(
            model.objects.order_by("created_at", "pk").values_list("pk", flat=True)
        )

    assert list(Session.objects.order_by("uuid").values_list("pk", flat=True)) == [
        session_tied_a.pk,
        session_tied_b.pk,
        session_late.pk,
    ]
    assert list(PlayEvent.objects.order_by("uuid").values_list("pk", flat=True)) == [
        playevent_tied_a.pk,
        playevent_tied_b.pk,
        playevent_late.pk,
    ]

    output = capsys.readouterr().out
    assert "SES identity backfilled" in output
    assert "session_rows=3" in output
    assert "playevent_rows=3" in output
    assert "max_timestamp_delta_ms=0 order_preserved=true" in output


def test_forward_migration_sorts_null_timestamp_status_changes_last(
    identity_harness, capsys
):
    apps = identity_harness
    game = seed_owned_game(apps, username="statuschange-owner")
    GameStatusChange = apps.get_model("games", "GameStatusChange")

    tied_ms = datetime(2024, 6, 1, 12, 0, 0, 500_000, tzinfo=UTC)
    later = datetime(2024, 6, 1, 12, 0, 1, 0, tzinfo=UTC)
    migration_floor = timezone.now()

    # A fixture-loaded row can carry a NULL timestamp even though the only
    # code path that writes one always sets it.
    null_first = GameStatusChange.objects.create(
        game_id=game.pk, old_status="u", new_status="p", timestamp=None
    )
    change_later = GameStatusChange.objects.create(
        game_id=game.pk, old_status="p", new_status="f", timestamp=later
    )
    change_tied_a = GameStatusChange.objects.create(
        game_id=game.pk, old_status="u", new_status="p", timestamp=tied_ms
    )
    change_tied_b = GameStatusChange.objects.create(
        game_id=game.pk, old_status="p", new_status="r", timestamp=tied_ms
    )
    null_second = GameStatusChange.objects.create(
        game_id=game.pk, old_status="f", new_status="a", timestamp=None
    )

    new_apps = migrate_to_identity()
    MigratedChange = new_apps.get_model("games", "GameStatusChange")

    changes = list(MigratedChange.objects.order_by("pk"))
    assert all(change.uuid is not None for change in changes)
    assert len({change.uuid for change in changes}) == len(changes)
    assert all(change.uuid.version == 7 for change in changes)

    populated = MigratedChange.objects.filter(timestamp__isnull=False)
    for change in populated:
        assert change.uuid.time == floor_ms(change.timestamp)
    assert list(populated.order_by("uuid").values_list("pk", flat=True)) == [
        change_tied_a.pk,
        change_tied_b.pk,
        change_later.pk,
    ]

    by_uuid = list(MigratedChange.objects.order_by("uuid").values_list("pk", flat=True))
    assert set(by_uuid[-2:]) == {null_first.pk, null_second.pk}

    for change in MigratedChange.objects.filter(timestamp__isnull=True):
        assert change.uuid.time >= floor_ms(migration_floor)

    output = capsys.readouterr().out
    assert "gamestatuschange_rows=5" in output
    assert "gamestatuschange_null_timestamp_rows=2" in output


# --- Migration: reverse -------------------------------------------------------


def test_reverse_migration_drops_the_columns_and_keeps_other_data(identity_harness):
    apps = identity_harness
    game = seed_owned_game(apps, username="reverse-owner")
    GameStatusChange = apps.get_model("games", "GameStatusChange")

    started = timezone.now() - timedelta(hours=1)
    session = create_row_at(
        apps,
        "Session",
        game_id=game.pk,
        timestamp_start=started,
        note="Persistent Session",
        created_at=started,
    )
    playevent = create_row_at(
        apps, "PlayEvent", game_id=game.pk, note="Persistent Event", created_at=started
    )
    change = GameStatusChange.objects.create(
        game_id=game.pk, old_status="u", new_status="p", timestamp=started
    )

    new_apps = migrate_to_identity()
    assert new_apps.get_model("games", "Session").objects.get(pk=session.pk).uuid
    assert new_apps.get_model("games", "PlayEvent").objects.get(pk=playevent.pk).uuid
    assert (
        new_apps.get_model("games", "GameStatusChange").objects.get(pk=change.pk).uuid
    )

    executor = MigrationExecutor(connection)
    executor.migrate([BEFORE_IDENTITY])
    reverted_apps = executor.loader.project_state([BEFORE_IDENTITY]).apps

    assert "uuid" not in table_columns("games_session")
    assert "uuid" not in table_columns("games_playevent")
    assert "uuid" not in table_columns("games_gamestatuschange")

    RevertedSession = reverted_apps.get_model("games", "Session")
    RevertedPlayEvent = reverted_apps.get_model("games", "PlayEvent")
    RevertedChange = reverted_apps.get_model("games", "GameStatusChange")
    assert RevertedSession.objects.get(pk=session.pk).note == "Persistent Session"
    assert RevertedPlayEvent.objects.get(pk=playevent.pk).note == "Persistent Event"
    assert RevertedChange.objects.get(pk=change.pk).new_status == "p"
