import uuid
from datetime import UTC, datetime, timedelta

import pytest
from django.core.exceptions import ValidationError
from django.http import HttpResponse
from django.test import Client, override_settings
from django.urls import NoReverseMatch, path, reverse
from django.urls.converters import get_converters

from timetracker import urls as project_urls  # noqa: F401
from timetracker.uuidv7 import UUIDv7Converter, parse_uuidv7, validate_uuidv7


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
