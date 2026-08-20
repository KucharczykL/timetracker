import json
import uuid
from datetime import UTC, datetime

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import NoReverseMatch, Resolver404, resolve, reverse

from common.criteria import FilterError, Modifier, UUIDMultiCriterion
from games.api import api
from games.filters import SessionFilter, parse_session_filter
from games.models import Device, FilterPreset, Game, Session

pytestmark = pytest.mark.django_db

UUID4 = uuid.UUID("018f5e66-e800-4000-8000-000000000001")


@pytest.fixture
def runtime_world():
    owner = get_user_model().objects.create_user(username="config-runtime-owner")
    foreign_user = get_user_model().objects.create_user(username="config-runtime-other")
    client = Client()
    client.force_login(owner)
    own_device = Device.objects.create(library=owner.library, name="Own deck")
    foreign_device = Device.objects.create(
        library=foreign_user.library, name="Foreign deck"
    )
    game = Game.objects.create(library=owner.library, name="Runtime game")
    session = Session.objects.create(
        game=game,
        device=own_device,
        timestamp_start=datetime(2026, 8, 20, 8, tzinfo=UTC),
    )
    own_preset = FilterPreset.objects.create(
        library=owner.library, name="Own preset", mode="sessions"
    )
    foreign_preset = FilterPreset.objects.create(
        library=foreign_user.library, name="Foreign preset", mode="sessions"
    )
    return locals()


@pytest.mark.parametrize("route_name", ["games:edit_device", "games:delete_device"])
def test_device_html_routes_use_uuidv7(route_name):
    identity = uuid.uuid7()
    url = reverse(route_name, args=[identity])
    assert resolve(url).kwargs == {"device_id": identity}

    for invalid in (1, "malformed", UUID4):
        with pytest.raises(NoReverseMatch):
            reverse(route_name, args=[invalid])
        with pytest.raises(Resolver404):
            resolve(url.replace(str(identity), str(invalid)))


def _patch(client, path, payload):
    return client.patch(path, json.dumps(payload), content_type="application/json")


def test_device_api_values_are_uuid_strings(runtime_world):
    world = runtime_world
    search = world["client"].get("/api/devices/search").json()
    detail = world["client"].get(f"/api/session/{world['session'].pk}").json()

    assert [option["value"] for option in search] == [str(world["own_device"].pk)]
    assert detail["device"]["id"] == str(world["own_device"].pk)


def test_session_device_patch_is_strict_nullable_and_library_scoped(runtime_world):
    world = runtime_world
    replacement = Device.objects.create(
        library=world["owner"].library, name="Replacement"
    )
    url = f"/api/session/{world['session'].pk}/device"

    assert (
        _patch(world["client"], url, {"device_id": str(replacement.pk)}).status_code
        == 204
    )
    world["session"].refresh_from_db()
    assert world["session"].device == replacement

    for invalid in (1, "malformed", str(UUID4)):
        assert _patch(world["client"], url, {"device_id": invalid}).status_code == 422
    assert (
        _patch(world["client"], url, {"device_id": str(uuid.uuid7())}).status_code
        == 404
    )
    assert (
        _patch(
            world["client"], url, {"device_id": str(world["foreign_device"].pk)}
        ).status_code
        == 404
    )
    assert _patch(world["client"], url, {"device_id": None}).status_code == 204
    world["session"].refresh_from_db()
    assert world["session"].device is None


def test_default_device_setting_is_strict_nullable_and_library_scoped(runtime_world):
    world = runtime_world
    url = "/api/library/default-device"
    selected = _patch(world["client"], url, {"value": str(world["own_device"].pk)})
    assert selected.status_code == 200
    assert selected.json()["value"] == str(world["own_device"].pk)

    openapi = api.get_openapi_schema()
    response_schema = openapi["paths"]["/api/library/default-device"]["patch"][
        "responses"
    ][200]["content"]["application/json"]["schema"]
    assert response_schema == {"$ref": "#/components/schemas/DefaultDeviceOut"}
    assert openapi["components"]["schemas"]["DefaultDeviceOut"]["properties"]["value"][
        "anyOf"
    ] == [
        {"format": "uuid", "type": "string"},
        {"type": "null"},
    ]
    for invalid in (1, "malformed", str(UUID4)):
        assert _patch(world["client"], url, {"value": invalid}).status_code == 422
    assert _patch(world["client"], url, {"value": str(uuid.uuid7())}).status_code == 404
    assert (
        _patch(
            world["client"], url, {"value": str(world["foreign_device"].pk)}
        ).status_code
        == 404
    )
    assert _patch(world["client"], url, {"value": None}).status_code == 200


def test_preset_values_and_delete_identity_are_strict_uuidv7(runtime_world):
    world = runtime_world
    options = world["client"].get("/api/presets/", {"mode": "sessions"}).json()
    assert [option["value"] for option in options] == [str(world["own_preset"].pk)]

    for invalid in (1, "malformed", UUID4):
        assert world["client"].delete(f"/api/presets/{invalid}").status_code == 422
    assert world["client"].delete(f"/api/presets/{uuid.uuid7()}").status_code == 404
    assert (
        world["client"].delete(f"/api/presets/{world['foreign_preset'].pk}").status_code
        == 404
    )
    assert (
        world["client"].delete(f"/api/presets/{world['own_preset'].pk}").status_code
        == 204
    )


def test_session_device_filter_parses_serializes_and_executes_uuidv7(runtime_world):
    world = runtime_world
    payload = json.dumps(
        {
            "device": {
                "value": [{"id": str(world["own_device"].pk), "label": "Own deck"}],
                "modifier": "INCLUDES",
            }
        }
    )
    parsed = parse_session_filter(payload)
    assert parsed == SessionFilter(
        device=UUIDMultiCriterion(value=[world["own_device"].pk])
    )
    assert parsed.to_json()["device"]["value"] == [str(world["own_device"].pk)]
    assert list(Session.objects.filter(parsed.to_q()).values_list("pk", flat=True)) == [
        world["session"].pk
    ]
    assert SessionFilter.fields["device"].lookup == "device_id"
    assert UUIDMultiCriterion(modifier=Modifier.IS_NULL).to_json() == {
        "modifier": "IS_NULL"
    }

    for invalid in ([1], ["malformed"], [str(UUID4)]):
        with pytest.raises(FilterError, match="UUID"):
            parse_session_filter(json.dumps({"device": {"value": invalid}}))
