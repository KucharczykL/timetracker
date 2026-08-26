import uuid
from datetime import UTC, datetime, timedelta, tzinfo
from types import SimpleNamespace

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, NotSupportedError, connection, models, transaction
from django.http import HttpResponse
from django.test import Client, override_settings
from django.test.utils import isolate_apps
from django.urls import NoReverseMatch, path, reverse
from django.urls.converters import get_converters

from timetracker import urls as project_urls  # noqa: F401
from timetracker.uuidv7 import (
    PostgreSQLUUIDv7,
    UUIDv7Converter,
    UUIDv7Field,
    parse_uuidv7,
    uuid7_at,
    validate_uuidv7,
)


def uuidv7_probe(request, value):
    return HttpResponse(str(value), content_type="text/plain")


urlpatterns = [
    path("uuidv7/<uuidv7:value>/", uuidv7_probe, name="uuidv7-probe"),
]


def test_parse_uuidv7_normalizes_text_and_preserves_uuid_objects():
    value = uuid.uuid7()
    assert parse_uuidv7(str(value)) == value
    assert parse_uuidv7(value) is value


def test_python_uuidv7_timestamp_tracks_the_application_clock():
    before = datetime.now(UTC) - timedelta(milliseconds=2)
    value = uuid.uuid7()
    after = datetime.now(UTC) + timedelta(milliseconds=2)
    embedded = datetime.fromtimestamp(value.time / 1_000, UTC)
    assert before <= embedded <= after


@pytest.mark.parametrize(
    ("value", "code"),
    [
        ("not-a-uuid", "invalid_uuid"),
        (uuid.uuid1(), "invalid_uuid_version"),
        (uuid.uuid4(), "invalid_uuid_version"),
        (uuid.UUID(int=0), "invalid_uuid_version"),
        (uuid.UUID(int=(1 << 128) - 1), "invalid_uuid_version"),
        (
            uuid.UUID("00000000-0000-7000-0000-000000000000"),
            "invalid_uuid_version",
        ),
    ],
)
def test_validate_uuidv7_uses_stable_error_codes(value, code):
    with pytest.raises(ValidationError) as caught:
        validate_uuidv7(value)
    assert caught.value.code == code


def test_project_registers_uuidv7_converter():
    assert isinstance(get_converters()["uuidv7"], UUIDv7Converter)


@pytest.mark.django_db
@override_settings(ROOT_URLCONF=__name__)
def test_uuidv7_route_normalizes_valid_input_and_rejects_other_versions():
    value = uuid.uuid7()
    client = Client()
    accepted = client.get(f"/uuidv7/{value}/")
    rejected = client.get(f"/uuidv7/{uuid.uuid4()}/")
    uppercase = client.get(f"/uuidv7/{str(value).upper()}/")

    assert accepted.status_code == 200
    assert accepted.content == str(value).encode()
    assert rejected.status_code == 404
    assert uppercase.status_code == 404


@override_settings(ROOT_URLCONF=__name__)
def test_uuidv7_route_refuses_to_generate_a_non_v7_url():
    with pytest.raises(NoReverseMatch):
        reverse("uuidv7-probe", kwargs={"value": uuid.uuid4()})


def test_uuidv7_field_declares_stable_defaults_and_migration_path():
    field = UUIDv7Field(primary_key=True)
    _, path, args, kwargs = field.deconstruct()

    assert path == "timetracker.uuidv7.UUIDv7Field"
    assert args == []
    assert kwargs["primary_key"] is True
    assert kwargs["default"] is uuid.uuid7
    assert isinstance(kwargs["db_default"], PostgreSQLUUIDv7)


def test_uuidv7_field_allows_explicit_default_overrides():
    field = UUIDv7Field(default=None, db_default=None)
    assert field.default is None
    assert field.db_default is None


def test_uuidv7_field_without_a_database_default_survives_a_clone():
    # clone() rebuilds the field from deconstruct(), where __init__ would
    # otherwise re-apply the generated db_default and leave migration state
    # permanently disagreeing with the model.
    field = UUIDv7Field(default=None, db_default=models.NOT_PROVIDED)

    assert field.deconstruct()[3]["db_default"] is models.NOT_PROVIDED
    assert field.clone().has_db_default() is False


def test_uuidv7_field_without_a_minted_default_survives_a_clone():
    # The same hazard as the db_default guard above, and the one that matters
    # most: a projection key opts out so that a rebuild reproduces the identity
    # the live table had, and the shadow model a rebuild writes to is a clone.
    field = UUIDv7Field(default=models.NOT_PROVIDED)

    assert field.deconstruct()[3]["default"] is models.NOT_PROVIDED
    assert field.clone().has_default() is False


def test_uuidv7_field_rejects_an_unsupported_backend():
    with pytest.raises(NotSupportedError, match="PostgreSQL"):
        UUIDv7Field().db_type(SimpleNamespace(vendor="mysql"))


@isolate_apps("games")
def test_uuidv7_field_assigns_distinct_ids_before_save():
    class Probe(models.Model):
        id = UUIDv7Field(primary_key=True)

        class Meta:
            app_label = "games"

    first = Probe()
    second = Probe()

    assert first.pk.version == 7
    assert second.pk.version == 7
    assert first != second
    assert hash(first) != hash(second)


@pytest.mark.django_db(transaction=True)
@isolate_apps("games")
def test_uuidv7_field_round_trips_defaults_constraints_indexes_and_foreign_keys():
    class Probe(models.Model):
        id = UUIDv7Field(primary_key=True)
        label = models.CharField(max_length=32)
        optional = UUIDv7Field(null=True, default=None, db_default=None)

        class Meta:
            app_label = "games"
            db_table = "test_uuidv7_probe"

    class Child(models.Model):
        probe = models.ForeignKey(Probe, on_delete=models.CASCADE)

        class Meta:
            app_label = "games"
            db_table = "test_uuidv7_child"

    with connection.schema_editor() as schema_editor:
        schema_editor.create_model(Probe)
        schema_editor.create_model(Child)

    try:
        python_created = Probe.objects.create(label="python")
        assert isinstance(python_created.pk, uuid.UUID)
        assert python_created.pk.version == 7
        assert python_created.optional is None

        with connection.cursor() as cursor:
            cursor.execute(
                'INSERT INTO "test_uuidv7_probe" ("label") VALUES (%s) RETURNING "id"',
                ["database"],
            )
            raw_id = uuid.UUID(str(cursor.fetchone()[0]))

        database_created = Probe.objects.get(pk=raw_id)
        assert isinstance(database_created.pk, uuid.UUID)
        assert database_created.pk.version == 7
        assert Child._meta.get_field("probe").db_type(connection) == "uuid_v7"
        assert Child.objects.create(probe=database_created).probe_id == raw_id

        ordered = list(Probe.objects.order_by("id").values_list("id", flat=True))
        assert ordered == sorted(ordered)

        with connection.cursor() as cursor:
            constraints = connection.introspection.get_constraints(
                cursor, Probe._meta.db_table
            )
        assert any(item["primary_key"] for item in constraints.values())

        with (
            pytest.raises(IntegrityError),
            transaction.atomic(),
            connection.cursor() as cursor,
        ):
            cursor.execute(
                'INSERT INTO "test_uuidv7_probe" ("id", "label") VALUES (%s, %s)',
                [uuid.uuid4(), "invalid"],
            )
    finally:
        with connection.schema_editor() as schema_editor:
            schema_editor.delete_model(Child)
            schema_editor.delete_model(Probe)


@pytest.mark.parametrize(
    ("value", "code"),
    [
        ("not-a-uuid", "invalid_uuid"),
        (uuid.uuid4(), "invalid_uuid_version"),
    ],
)
@isolate_apps("games")
def test_uuidv7_field_full_clean_uses_shared_validation_codes(value, code):
    class Probe(models.Model):
        id = UUIDv7Field(primary_key=True)

        class Meta:
            app_label = "games"

    with pytest.raises(ValidationError) as caught:
        Probe(id=value).full_clean()

    assert caught.value.error_dict["id"][0].code == code


@pytest.mark.django_db
def test_uuidv7_field_normalizes_a_driver_string():
    value = uuid.uuid7()
    normalized = UUIDv7Field().from_db_value(str(value), None, connection)
    assert normalized == value
    assert isinstance(normalized, uuid.UUID)


def test_uuid7_at_encodes_the_requested_millisecond():
    moment = datetime(2024, 1, 1, tzinfo=UTC)
    value = uuid7_at(moment)
    assert value.time == round(moment.timestamp() * 1000)


def test_uuid7_at_floors_fractional_milliseconds_instead_of_rounding():
    # microsecond=999_999 sits at the top of its millisecond: round() would
    # carry into the next millisecond (and here, the next second), but the
    # migration's reconciliation compares against PostgreSQL's
    # date_trunc('milliseconds', ...), which floors — as does CPython's own
    # uuid.uuid7() (nanoseconds // 1_000_000).
    moment = datetime(2024, 1, 1, 0, 0, 0, 999_999, tzinfo=UTC)
    value = uuid7_at(moment)
    elapsed = moment - datetime(1970, 1, 1, tzinfo=UTC)
    floored_ms = (
        elapsed.days * 86_400_000
        + elapsed.seconds * 1000
        + elapsed.microseconds // 1000
    )
    assert value.time == floored_ms
    assert value.time != round(moment.timestamp() * 1000)


def test_uuid7_at_sets_version_and_variant():
    value = uuid7_at(datetime(2024, 1, 1, tzinfo=UTC))
    assert value.version == 7
    assert value.variant == uuid.RFC_4122


def test_uuid7_at_is_distinct_for_repeated_calls_at_the_same_instant():
    moment = datetime(2024, 1, 1, tzinfo=UTC)
    first = uuid7_at(moment)
    second = uuid7_at(moment)
    assert first != second


def test_uuid7_at_sequence_orders_values_within_one_millisecond():
    moment = datetime(2024, 1, 1, tzinfo=UTC)
    values = [uuid7_at(moment, sequence=sequence) for sequence in range(5)]
    assert values == sorted(values)
    assert len({value for value in values}) == len(values)


def test_uuid7_at_rejects_a_naive_datetime():
    with pytest.raises(ValueError, match="timezone-aware"):
        uuid7_at(datetime(2024, 1, 1))  # noqa: DTZ001


class _TzinfoWithoutOffset(tzinfo):
    """A tzinfo present but returning no offset - technically not aware.

    Python's own definition of "aware" is `tzinfo is not None and
    utcoffset() is not None`; a bare `tzinfo is None` check misses this.
    """

    def utcoffset(self, moment):
        return None

    def dst(self, moment):
        return None

    def tzname(self, moment):
        return "broken"


def test_uuid7_at_rejects_a_datetime_whose_tzinfo_has_no_utcoffset():
    moment = datetime(2024, 1, 1, tzinfo=_TzinfoWithoutOffset())
    with pytest.raises(ValueError, match="timezone-aware"):
        uuid7_at(moment)


@pytest.mark.parametrize("sequence", [-1, 4096])
def test_uuid7_at_rejects_a_sequence_outside_the_12_bit_range(sequence):
    with pytest.raises(ValueError, match="sequence must be between 0 and 4095"):
        uuid7_at(datetime(2024, 1, 1, tzinfo=UTC), sequence=sequence)


@pytest.mark.parametrize("sequence", [0, 4095])
def test_uuid7_at_accepts_sequence_at_the_12_bit_boundaries(sequence):
    value = uuid7_at(datetime(2024, 1, 1, tzinfo=UTC), sequence=sequence)
    assert value.version == 7


def test_uuid7_at_rejects_a_pre_epoch_moment():
    with pytest.raises(ValueError, match="before the Unix epoch"):
        uuid7_at(datetime(1969, 12, 31, 23, 59, 59, 999_000, tzinfo=UTC))


def test_uuid7_at_accepts_the_epoch_instant_itself():
    value = uuid7_at(datetime(1970, 1, 1, tzinfo=UTC))
    assert value.time == 0


def test_uuid7_at_pins_the_byte_layout():
    moment = datetime(2024, 1, 1, tzinfo=UTC)
    value = uuid7_at(moment, sequence=5)
    # Everything except the 62 random rand_b bits: unix_ts_ms | version | rand_a | variant.
    assert value.int >> 62 == 0x6330947D001C016


def test_uuid7_at_repeats_exactly_for_the_same_entropy():
    moment = datetime(2024, 1, 1, tzinfo=UTC)
    first = uuid7_at(moment, sequence=3, entropy=12345)
    second = uuid7_at(moment, sequence=3, entropy=12345)
    assert first == second


def test_uuid7_at_writes_entropy_into_rand_b():
    entropy = 0x2BADC0FFEE1234
    value = uuid7_at(datetime(2024, 1, 1, tzinfo=UTC), entropy=entropy)
    assert value.int & ((1 << 62) - 1) == entropy
    assert value.version == 7
    assert value.variant == uuid.RFC_4122


@pytest.mark.parametrize("entropy", [-1, 1 << 62])
def test_uuid7_at_rejects_entropy_outside_the_62_bit_range(entropy):
    with pytest.raises(ValueError, match="entropy must be between 0 and"):
        uuid7_at(datetime(2024, 1, 1, tzinfo=UTC), entropy=entropy)


@pytest.mark.parametrize("entropy", [0, (1 << 62) - 1])
def test_uuid7_at_accepts_entropy_at_the_62_bit_boundaries(entropy):
    value = uuid7_at(datetime(2024, 1, 1, tzinfo=UTC), entropy=entropy)
    assert value.int & ((1 << 62) - 1) == entropy


def test_uuid7_at_without_entropy_still_varies_between_calls():
    moment = datetime(2024, 1, 1, tzinfo=UTC)
    values = {uuid7_at(moment, sequence=0) for _ in range(8)}
    assert len(values) == 8
