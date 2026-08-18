import json
import uuid
from zoneinfo import ZoneInfo

import pytest
from django.core.management import call_command
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from common.criteria import FilterQueryContext, Modifier, RelationMatch, StringCriterion
from common.date_time_presentation import (
    DEFAULT_DATE_TIME_FORMAT_PROFILE,
    DateTimePresentation,
)
from games.filters import DeviceFilter, GameFilter, SessionFilter
from games.forms import SessionForm
from games.models import Device, Game, Session, UserLibraryPreferences

PRESENTATION = DateTimePresentation(
    DEFAULT_DATE_TIME_FORMAT_PROFILE, "en-us", ZoneInfo("UTC")
)

UNRESTRICTED_FILTER_CONTEXT = FilterQueryContext(
    lambda model: model._default_manager.all()
)

pytestmark = pytest.mark.django_db(transaction=True)

BEFORE_FK_UUID = ("games", "0010_platform_fk_uuid")
WITH_FK_UUID = ("games", "0011_session_fk_uuid")


# --- Migration harness -------------------------------------------------------


@pytest.fixture
def fk_uuid_harness():
    # Migrating down to BEFORE_FK_UUID unapplies every later migration too, so
    # the restore target is the graph's leaf nodes rather than WITH_FK_UUID,
    # which would strand this worker's shared database behind head for every
    # later test that reuses it.
    leaf_nodes = MigrationExecutor(connection).loader.graph.leaf_nodes()
    executor = MigrationExecutor(connection)
    executor.migrate([BEFORE_FK_UUID])
    call_command("flush", interactive=False, verbosity=0)
    old_apps = executor.loader.project_state([BEFORE_FK_UUID]).apps
    yield old_apps
    MigrationExecutor(connection).migrate(leaf_nodes)


def migrate_to_fk_uuid():
    executor = MigrationExecutor(connection)
    executor.migrate([WITH_FK_UUID])
    return executor.loader.project_state([WITH_FK_UUID]).apps


def seed_historic_world(apps, *, username: str):
    """One library with two games and two devices, on the pre-cutover schema."""
    User = apps.get_model("auth", "User")
    UserLibrary = apps.get_model("games", "UserLibrary")
    Game = apps.get_model("games", "Game")
    Device = apps.get_model("games", "Device")
    user = User.objects.create(username=username)
    library = UserLibrary.objects.create(user_id=user.pk, created_at=timezone.now())
    games = [
        Game.objects.create(library_id=library.pk, name=f"Historic Game {index}")
        for index in range(2)
    ]
    devices = [
        Device.objects.create(library_id=library.pk, name=f"Historic Device {index}")
        for index in range(2)
    ]
    return library, games, devices


def column_type(table_name: str, column_name: str) -> str:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT domain_name FROM information_schema.columns
            WHERE table_name = %s AND column_name = %s
            """,
            [table_name, column_name],
        )
        row = cursor.fetchone()
    assert row is not None, f"{table_name}.{column_name} does not exist"
    return row[0]


def foreign_key_target(table_name: str, column_name: str) -> tuple[str, str] | None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT ccu.table_name, ccu.column_name
            FROM information_schema.table_constraints AS constraint_row
            JOIN information_schema.key_column_usage AS key_usage
                ON key_usage.constraint_name = constraint_row.constraint_name
            JOIN information_schema.constraint_column_usage AS ccu
                ON ccu.constraint_name = constraint_row.constraint_name
            WHERE constraint_row.table_name = %s
                AND constraint_row.constraint_type = 'FOREIGN KEY'
                AND key_usage.column_name = %s
            """,
            [table_name, column_name],
        )
        row = cursor.fetchone()
    return tuple(row) if row is not None else None


# --- Migration: forward -------------------------------------------------------


def test_forward_migration_repoints_session_and_preference_relations(
    fk_uuid_harness, capsys
):
    apps = fk_uuid_harness
    library, games, devices = seed_historic_world(apps, username="session-fk-owner")
    Session = apps.get_model("games", "Session")
    Preferences = apps.get_model("games", "UserLibraryPreferences")

    started = timezone.now()
    on_first_device = Session.objects.create(
        game_id=games[0].pk, device_id=devices[0].pk, timestamp_start=started
    )
    on_second_device = Session.objects.create(
        game_id=games[1].pk, device_id=devices[1].pk, timestamp_start=started
    )
    # The nullable half of the invariant: this row must still have no device.
    deviceless = Session.objects.create(
        game_id=games[0].pk, device_id=None, timestamp_start=started
    )
    Preferences.objects.create(
        library_id=library.pk,
        default_device_id=devices[1].pk,
        updated_at=timezone.now(),
    )

    new_apps = migrate_to_fk_uuid()
    NewGame = new_apps.get_model("games", "Game")
    NewDevice = new_apps.get_model("games", "Device")
    NewSession = new_apps.get_model("games", "Session")
    NewPreferences = new_apps.get_model("games", "UserLibraryPreferences")

    migrated_first = NewSession.objects.get(pk=on_first_device.pk)
    migrated_second = NewSession.objects.get(pk=on_second_device.pk)
    migrated_deviceless = NewSession.objects.get(pk=deviceless.pk)

    assert migrated_first.game.name == "Historic Game 0"
    assert migrated_first.device.name == "Historic Device 0"
    assert migrated_second.game.name == "Historic Game 1"
    assert migrated_second.device.name == "Historic Device 1"
    assert migrated_deviceless.game.name == "Historic Game 0"
    assert migrated_deviceless.device_id is None

    assert migrated_first.game_id == NewGame.objects.get(pk=games[0].pk).uuid
    assert migrated_first.device_id == NewDevice.objects.get(pk=devices[0].pk).uuid
    assert (
        NewPreferences.objects.get(library_id=library.pk).default_device.name
        == "Historic Device 1"
    )

    assert column_type("games_session", "game_id") == "uuid_v7"
    assert column_type("games_session", "device_id") == "uuid_v7"
    assert column_type("games_userlibrarypreferences", "default_device_id") == "uuid_v7"
    assert foreign_key_target("games_session", "game_id") == ("games_game", "uuid")
    assert foreign_key_target("games_session", "device_id") == ("games_device", "uuid")
    assert foreign_key_target("games_userlibrarypreferences", "default_device_id") == (
        "games_device",
        "uuid",
    )

    output = capsys.readouterr().out
    assert "FK identity rewritten" in output
    assert "session_rows=3 session_games=2" in output
    assert "session_devices=2 session_device_nulls=1" in output
    assert (
        "preferences_rows=1 preferences_devices=1 preferences_device_nulls=0" in output
    )
    assert "unmatched=0" in output


# --- Migration: reverse -------------------------------------------------------


def test_reverse_migration_restores_the_original_integer_ids(fk_uuid_harness):
    apps = fk_uuid_harness
    library, games, devices = seed_historic_world(
        apps, username="session-fk-reverse-owner"
    )
    Session = apps.get_model("games", "Session")
    Preferences = apps.get_model("games", "UserLibraryPreferences")

    started = timezone.now()
    with_device = Session.objects.create(
        game_id=games[0].pk, device_id=devices[0].pk, timestamp_start=started
    )
    deviceless = Session.objects.create(
        game_id=games[1].pk, device_id=None, timestamp_start=started
    )
    Preferences.objects.create(
        library_id=library.pk,
        default_device_id=devices[0].pk,
        updated_at=timezone.now(),
    )

    migrate_to_fk_uuid()

    executor = MigrationExecutor(connection)
    executor.migrate([BEFORE_FK_UUID])
    reverted_apps = executor.loader.project_state([BEFORE_FK_UUID]).apps

    RevertedSession = reverted_apps.get_model("games", "Session")
    RevertedPreferences = reverted_apps.get_model("games", "UserLibraryPreferences")

    restored = RevertedSession.objects.get(pk=with_device.pk)
    assert restored.game_id == games[0].pk
    assert restored.device_id == devices[0].pk
    restored_deviceless = RevertedSession.objects.get(pk=deviceless.pk)
    assert restored_deviceless.game_id == games[1].pk
    assert restored_deviceless.device_id is None
    assert (
        RevertedPreferences.objects.get(library_id=library.pk).default_device_id
        == devices[0].pk
    )
    assert "game_uuid" not in [
        field.name for field in RevertedSession._meta.get_fields()
    ]
    assert "device_uuid" not in [
        field.name for field in RevertedSession._meta.get_fields()
    ]


# --- ORM behavior (current schema) -------------------------------------------


@pytest.fixture
def game(owned_library):
    return Game.objects.create(library=owned_library, name="FK Identity Subject")


@pytest.fixture
def device(owned_library):
    return Device.objects.create(
        library=owned_library, name="Handheld", type=Device.HANDHELD
    )


@pytest.fixture
def auth_client(owned_user):
    client = Client()
    client.force_login(owned_user)
    return client


def _session(game, **overrides) -> Session:
    return Session.objects.create(
        game=game, timestamp_start=timezone.now(), **overrides
    )


def test_session_attnames_read_back_as_the_targets_uuids(game, device):
    session = _session(game, device=device)
    assert session.game_id == game.uuid
    assert session.device_id == device.uuid


def test_default_device_attname_reads_back_as_the_devices_uuid(owned_library, device):
    preferences = UserLibraryPreferences.objects.get(library=owned_library)
    preferences.set_default_device(device)
    preferences.refresh_from_db()
    assert preferences.default_device_id == device.uuid


def test_set_default_device_still_short_circuits_an_unchanged_value(
    owned_library, device
):
    preferences = UserLibraryPreferences.objects.get(library=owned_library)
    assert preferences.set_default_device(device) is True
    assert preferences.set_default_device(device) is False


def test_session_filters_by_related_instance_and_by_integer_id(
    game, device, owned_library
):
    other_game = Game.objects.create(library=owned_library, name="Other")
    other_device = Device.objects.create(library=owned_library, name="Desk")
    matching = _session(game, device=device)
    _session(other_game, device=other_device)

    assert list(Session.objects.filter(game=game)) == [matching]
    assert list(Session.objects.filter(game__id=game.id)) == [matching]
    assert list(Session.objects.filter(device=device)) == [matching]
    assert list(Session.objects.filter(device__id=device.id)) == [matching]


def test_reverse_accessors_reach_sessions_from_game_and_device(game, device):
    session = _session(game, device=device)
    assert list(game.sessions.all()) == [session]
    # /api/devices/search sorts on this reverse name; it must survive the swap.
    assert list(device.session_set.all()) == [session]


def test_deleting_a_game_cascades_and_deleting_a_device_clears_the_session(
    game, device
):
    kept = _session(game, device=device)
    device.delete()
    kept.refresh_from_db()
    assert kept.device_id is None

    game.delete()
    assert not Session.objects.filter(pk=kept.pk).exists()


def test_database_rejects_a_session_naming_a_device_uuid_no_device_owns(game):
    # bulk_create bypasses Session.save(), which dereferences self.device and
    # would raise DoesNotExist before any insert is attempted.
    with pytest.raises(IntegrityError), transaction.atomic():
        Session.objects.bulk_create(
            [
                Session(
                    game=game,
                    timestamp_start=timezone.now(),
                    device_id=uuid.uuid7(),
                )
            ]
        )


def test_database_rejects_preferences_naming_a_device_uuid_no_device_owns(
    owned_library,
):
    preferences = UserLibraryPreferences.objects.get(library=owned_library)
    # Same reason as above: save() calls clean(), which dereferences
    # self.default_device.
    with pytest.raises(IntegrityError), transaction.atomic():
        UserLibraryPreferences.objects.filter(pk=preferences.pk).update(
            default_device_id=uuid.uuid7()
        )


# --- Filters (integer criterion values, one join deeper) --------------------


def test_sessionfilter_game_and_device_criteria_select_the_right_rows(
    game, device, owned_library
):
    other_game = Game.objects.create(library=owned_library, name="Other")
    other_device = Device.objects.create(library=owned_library, name="Desk")
    matching = _session(game, device=device)
    _session(other_game, device=other_device)

    by_game = SessionFilter.where(game=[game.id])
    by_device = SessionFilter.where(device=[device.id])
    assert list(Session.objects.filter(by_game.to_q(UNRESTRICTED_FILTER_CONTEXT))) == [
        matching
    ]
    assert list(
        Session.objects.filter(by_device.to_q(UNRESTRICTED_FILTER_CONTEXT))
    ) == [matching]


def test_gamefilter_session_filter_selects_games_by_relation_match(
    game, device, owned_library
):
    other_game = Game.objects.create(library=owned_library, name="Other")
    _session(game, device=device, note="Marathon session")
    _session(other_game, device=device, note="Something else")

    note_filter = SessionFilter(
        note=StringCriterion(value="Marathon", modifier=Modifier.INCLUDES)
    )
    owned = Game.objects.filter(library=owned_library)

    any_match = GameFilter(session_filter=note_filter)
    assert list(owned.filter(any_match.to_q(UNRESTRICTED_FILTER_CONTEXT))) == [game]

    none_match = GameFilter(
        session_filter=SessionFilter(
            note=StringCriterion(value="Marathon", modifier=Modifier.INCLUDES),
            match=RelationMatch.NONE,
        )
    )
    assert list(owned.filter(none_match.to_q(UNRESTRICTED_FILTER_CONTEXT))) == [
        other_game
    ]


def test_sessionfilter_game_and_device_sub_filters_select_sessions(
    game, device, owned_library
):
    other_game = Game.objects.create(library=owned_library, name="Other")
    other_device = Device.objects.create(library=owned_library, name="Desk")
    matching = _session(game, device=device)
    _session(other_game, device=other_device)

    by_game = SessionFilter(
        game_filter=GameFilter(name=StringCriterion(value=game.name))
    )
    by_device = SessionFilter(
        device_filter=DeviceFilter(name=StringCriterion(value=device.name))
    )
    assert list(Session.objects.filter(by_game.to_q(UNRESTRICTED_FILTER_CONTEXT))) == [
        matching
    ]
    assert list(
        Session.objects.filter(by_device.to_q(UNRESTRICTED_FILTER_CONTEXT))
    ) == [matching]


def test_devicefilter_session_filter_selects_devices(game, device, owned_library):
    other_device = Device.objects.create(library=owned_library, name="Desk")
    _session(game, device=device, note="Marathon session")
    _session(game, device=other_device, note="Something else")

    filter_ = DeviceFilter(
        session_filter=SessionFilter(
            note=StringCriterion(value="Marathon", modifier=Modifier.INCLUDES)
        )
    )
    results = Device.objects.filter(library=owned_library).filter(
        filter_.to_q(UNRESTRICTED_FILTER_CONTEXT)
    )
    assert list(results) == [device]


def test_filtered_playtime_annotation_survives_the_uuid_relation(
    auth_client, game, device, owned_library
):
    """The games list correlates Session.game against Game in a subquery.

    It is annotated unconditionally, so a stale OuterRef target would take down
    every render of the page rather than just the filtered case.
    """
    _session(game, device=device, note="Marathon session")
    filter_json = json.dumps(
        {"AND": [{"session_filter": {"note": {"value": "Marathon"}}}]}
    )

    response = auth_client.get(reverse("games:list_games"), {"filter": filter_json})

    assert response.status_code == 200
    assert game.name in response.content.decode()


# --- Form initial-value shim -------------------------------------------------


def test_sessionform_preselects_both_relations_by_integer_id(
    game, device, owned_library
):
    session = _session(game, device=device)

    form = SessionForm(
        instance=session, library=owned_library, presentation=PRESENTATION
    )

    assert form.initial["game"] == game
    assert form.initial["device"] == device
    assert form.fields["game"].prepare_value(form.initial["game"]) == game.pk
    assert form.fields["device"].prepare_value(form.initial["device"]) == device.pk


def test_sessionform_keeps_a_caller_supplied_device_initial(
    game, device, owned_library
):
    """edit_session offers the library's default device to a deviceless session."""
    session = _session(game)

    form = SessionForm(
        instance=session,
        initial={"device": device},
        library=owned_library,
        presentation=PRESENTATION,
    )

    assert form.initial["device"] == device


def test_sessionform_posting_integer_ids_saves_the_right_relations(
    game, device, owned_library
):
    session = _session(game)
    other_game = Game.objects.create(library=owned_library, name="Retarget")

    form = SessionForm(
        data={
            "game": str(other_game.pk),
            "timestamp_start": "2026-08-14T12:00:00+00:00",
            "timestamp_start_timezone": "UTC",
            "timestamp_end": "",
            "timestamp_end_timezone": "",
            "duration_manual": "",
            "device": str(device.pk),
            "note": "",
        },
        instance=session,
        library=owned_library,
        presentation=PRESENTATION,
    )

    assert form.is_valid(), form.errors
    saved = form.save()
    assert saved.game_id == other_game.uuid
    assert saved.device_id == device.uuid


# --- Device PATCH endpoint ----------------------------------------------------


def _patch_device(client, session_id: int, payload: dict):
    return client.patch(
        f"/api/session/{session_id}/device",
        data=json.dumps(payload),
        content_type="application/json",
    )


def test_patch_session_device_binds_and_clears_by_integer_id(
    auth_client, owned_user, device
):
    game = Game.objects.create(library=owned_user.library, name="Patched")
    session = _session(game)

    assert (
        _patch_device(auth_client, session.pk, {"device_id": device.pk}).status_code
        == 204
    )
    session.refresh_from_db()
    assert session.device_id == device.uuid

    assert (
        _patch_device(auth_client, session.pk, {"device_id": None}).status_code == 204
    )
    session.refresh_from_db()
    assert session.device_id is None


def test_patch_session_device_rejects_a_stale_device_id(auth_client, owned_user):
    game = Game.objects.create(library=owned_user.library, name="Patched")
    session = _session(game)

    response = _patch_device(auth_client, session.pk, {"device_id": 999999})

    assert response.status_code == 404
