"""One version-7 identity per Session, stated nowhere a person can see it."""

import gzip
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml
from django.db import IntegrityError, connection, transaction
from django.utils import timezone

from games.forms import SessionForm
from games.models import Game, Session
from games.views.session import clone_session_by_id
from timetracker.uuidv7 import UUIDv7Field

SAMPLE_FIXTURE = Path(__file__).parents[1] / "games" / "fixtures" / "sample.yaml.gz"

pytestmark = pytest.mark.django_db(transaction=True)


def raw_insert_without_identity(model, **field_values):
    """INSERT a row through raw SQL that omits the primary-key column entirely,
    so PostgreSQL's own `uuidv7()` column default fills it in - the only
    way to exercise `db_default`, since the ORM always resolves the field's
    Python `default` first and never leaves the column to the database.
    """
    instance = model(**field_values)
    fields = [
        field
        for field in model._meta.local_concrete_fields
        if not field.primary_key and not field.generated
    ]
    columns = ", ".join(f'"{field.column}"' for field in fields)
    placeholders = ", ".join(["%s"] * len(fields))
    # pre_save() resolves auto_now/auto_now_add fields the way a real save
    # would; every other field returns its already-set attribute value.
    values = [field.get_prep_value(field.pre_save(instance, True)) for field in fields]
    with connection.cursor() as cursor:
        cursor.execute(
            f'INSERT INTO "{model._meta.db_table}" ({columns}) '
            f'VALUES ({placeholders}) RETURNING "{model._meta.pk.column}"',
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
    assert first.pk.version == 7
    assert second.pk.version == 7
    assert first.pk != second.pk


def test_raw_session_insert_omitting_id_gets_the_database_default(game):
    session_uuid = raw_insert_without_identity(
        Session, game=game, timestamp_start=timezone.now(), note="Raw Session"
    )
    assert session_uuid.version == 7
    assert Session.objects.get(pk=session_uuid).note == "Raw Session"


def test_cloning_a_session_assigns_a_fresh_uuid_to_the_promoted_pk(
    game, owned_library, monkeypatch
):
    source = Session.objects.create(game=game, timestamp_start=timezone.now())
    source_pk = source.pk
    expected_clone_pk = uuid.UUID("018f5e66-e800-7000-8000-000000000002")
    monkeypatch.setattr("games.views.session.uuid7", lambda: expected_clone_pk)

    clone = clone_session_by_id(source.pk, owned_library)

    assert clone.pk == expected_clone_pk
    assert clone.pk != source_pk
    assert clone.pk.version == 7
    assert Session.objects.filter(pk=source_pk).exists()
    assert set(Session.objects.values_list("pk", flat=True)) == {source_pk, clone.pk}


def test_cloning_rejects_a_generated_uuid_owned_by_another_library(
    game, owned_library, django_user_model, monkeypatch
):
    source = Session.objects.create(
        game=game,
        timestamp_start=datetime(2024, 1, 1, tzinfo=UTC),
        timestamp_end=datetime(2024, 1, 2, tzinfo=UTC),
        timestamp_start_timezone="Europe/Prague",
        timestamp_end_timezone="Europe/Prague",
        note="source",
        emulated=True,
    )
    other_owner = django_user_model.objects.create_user(username="clone-collision")
    other_game = Game.objects.create(
        library=other_owner.library, name="Collision Victim"
    )
    victim = Session.objects.create(
        game=other_game,
        timestamp_start=datetime(2023, 2, 1, tzinfo=UTC),
        timestamp_end=datetime(2023, 2, 2, tzinfo=UTC),
        note="victim",
    )
    source_before = Session.objects.filter(pk=source.pk).values().get()
    victim_before = Session.objects.filter(pk=victim.pk).values().get()
    monkeypatch.setattr("games.views.session.uuid7", lambda: victim.pk)

    collision_error: IntegrityError | None = None
    try:
        with transaction.atomic():
            clone_session_by_id(source.pk, owned_library)
    except IntegrityError as error:
        collision_error = error

    assert Session.objects.filter(pk=source.pk).values().get() == source_before
    assert Session.objects.filter(pk=victim.pk).values().get() == victim_before
    assert collision_error is not None


def test_database_rejects_a_duplicate_session_uuid(game):
    shared = uuid.uuid7()
    Session.objects.create(game=game, timestamp_start=timezone.now(), id=shared)
    with pytest.raises(IntegrityError), transaction.atomic():
        Session.objects.create(game=game, timestamp_start=timezone.now(), id=shared)


def test_database_rejects_a_non_v7_session_uuid(game):
    with pytest.raises(IntegrityError), transaction.atomic():
        Session.objects.create(
            game=game, timestamp_start=timezone.now(), id=uuid.uuid4()
        )


# --- Invisibility ------------------------------------------------------------


def test_uuid_is_absent_from_session_form_fields():
    assert "uuid" not in SessionForm.base_fields


def test_the_model_declares_one_uuidv7_primary_key_and_no_second_uuid_field():
    assert isinstance(Session._meta.pk, UUIDv7Field)
    assert Session._meta.pk.name == "id"
    assert Session._meta.pk.primary_key is True
    assert Session._meta.pk.editable is False
    assert "uuid" not in {field.name for field in Session._meta.local_fields}


def test_the_committed_sample_fixture_states_a_version_7_identity_per_row():
    """The fixture keeps the deployment's keys, so its rows read as promoted."""
    with gzip.open(SAMPLE_FIXTURE, "rt") as stream:
        records = yaml.safe_load(stream)

    promoted_models = {"games.game", "games.platform", "games.session"}
    promoted = [record for record in records if record["model"] in promoted_models]

    assert promoted
    assert {record["model"] for record in promoted} == promoted_models
    for record in promoted:
        assert uuid.UUID(str(record["pk"])).version == 7
        assert "uuid" not in record["fields"]


def test_the_committed_sample_fixture_names_no_model_the_app_dropped():
    """A fixture naming one would fail to load rather than be read as stale."""
    with gzip.open(SAMPLE_FIXTURE, "rt") as stream:
        records = yaml.safe_load(stream)

    assert not {"games.playevent", "games.gamestatuschange"} & {
        record["model"] for record in records
    }
