import json
from datetime import UTC, date, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import NoReverseMatch, Resolver404, resolve, reverse

from games.models import Device, Game, GameStatusChange, PlayEvent, Session

pytestmark = pytest.mark.django_db

ROUTE_UUID = UUID("018f5e66-e800-7000-8000-000000000001")
UUID4 = UUID("018f5e66-e800-4000-8000-000000000001")

HTML_IDENTITY_ROUTES = [
    ("games:edit_playevent", "playevent_id"),
    ("games:delete_playevent", "playevent_id"),
    ("games:list_sessions_start_session_from_session", "session_id"),
    ("games:edit_session", "session_id"),
    ("games:finish_session", "session_id"),
    ("games:reset_session", "session_id"),
    ("games:delete_session", "session_id"),
    ("games:edit_statuschange", "statuschange_id"),
    ("games:delete_statuschange", "pk"),
]


@pytest.mark.parametrize(("route_name", "parameter"), HTML_IDENTITY_ROUTES)
def test_promoted_html_routes_reverse_and_resolve_uuidv7(route_name, parameter):
    url = reverse(route_name, kwargs={parameter: ROUTE_UUID})

    match = resolve(url)

    assert match.view_name == route_name
    assert match.kwargs == {parameter: ROUTE_UUID}


@pytest.mark.parametrize(("route_name", "parameter"), HTML_IDENTITY_ROUTES)
@pytest.mark.parametrize(
    "invalid_id", [pytest.param(1, id="integer"), pytest.param(UUID4, id="uuid4")]
)
def test_promoted_html_routes_reject_non_uuidv7_ids(route_name, parameter, invalid_id):
    with pytest.raises(NoReverseMatch):
        reverse(route_name, kwargs={parameter: invalid_id})

    valid_url = reverse(route_name, kwargs={parameter: ROUTE_UUID})
    invalid_url = valid_url.replace(str(ROUTE_UUID), str(invalid_id))
    with pytest.raises(Resolver404):
        resolve(invalid_url)


@pytest.fixture
def runtime_world(db):
    owner = get_user_model().objects.create_user(username="runtime-owner")
    foreign_user = get_user_model().objects.create_user(username="runtime-foreign")
    client = Client()
    client.force_login(owner)

    own_game = Game.objects.create(library=owner.library, name="Owned runtime game")
    foreign_game = Game.objects.create(
        library=foreign_user.library, name="Foreign runtime game"
    )
    own_device = Device.objects.create(library=owner.library, name="Owned device")
    foreign_device = Device.objects.create(
        library=foreign_user.library, name="Foreign device"
    )
    own_session = Session.objects.create(
        game=own_game,
        device=own_device,
        timestamp_start=datetime(2026, 8, 20, 8, tzinfo=UTC),
    )
    foreign_session = Session.objects.create(
        game=foreign_game,
        device=foreign_device,
        timestamp_start=datetime(2026, 8, 20, 9, tzinfo=UTC),
    )
    own_playevent = PlayEvent.objects.create(
        game=own_game, started=date(2026, 8, 20), note="Owned event"
    )
    foreign_playevent = PlayEvent.objects.create(
        game=foreign_game, started=date(2026, 8, 20), note="Foreign event"
    )
    foreign_statuschange = GameStatusChange.objects.create(
        game=foreign_game,
        old_status=Game.Status.UNPLAYED,
        new_status=Game.Status.PLAYED,
        timestamp=datetime(2026, 8, 20, 10, tzinfo=UTC),
    )
    return SimpleNamespace(**locals())


def _api_request(client, method, path, payload=None):
    if payload is None:
        return getattr(client, method)(path)
    return getattr(client, method)(
        path, data=json.dumps(payload), content_type="application/json"
    )


@pytest.mark.parametrize(
    ("method", "payload", "expected_status"),
    [
        pytest.param("get", None, 200, id="get"),
        pytest.param("patch", {"note": "Updated event"}, 200, id="patch"),
        pytest.param("delete", None, 204, id="delete"),
    ],
)
def test_playevent_api_uses_uuidv7_paths(
    runtime_world, method, payload, expected_status
):
    event = runtime_world.own_playevent

    response = _api_request(
        runtime_world.client, method, f"/api/playevent/{event.pk}", payload
    )

    assert response.status_code == expected_status
    if method == "delete":
        assert not PlayEvent.objects.filter(pk=event.pk).exists()
    else:
        assert response.json()["id"] == str(event.pk)


def test_session_get_uses_a_uuidv7_path_and_serializes_the_id(runtime_world):
    session = runtime_world.own_session

    response = runtime_world.client.get(f"/api/session/{session.pk}")

    assert response.status_code == 200
    assert response.json()["id"] == str(session.pk)


def test_session_detail_patch_uses_a_uuidv7_path(runtime_world):
    session = runtime_world.own_session

    response = _api_request(
        runtime_world.client,
        "patch",
        f"/api/session/{session.pk}",
        {"timestamp_end": "2026-08-20T11:00:00Z"},
    )

    assert response.status_code == 200
    assert response.json()["id"] == str(session.pk)


def test_session_device_patch_uses_uuidv7_session_and_device_ids(
    runtime_world,
):
    session = runtime_world.own_session
    replacement = Device.objects.create(
        library=runtime_world.owner.library, name="Replacement device"
    )

    response = _api_request(
        runtime_world.client,
        "patch",
        f"/api/session/{session.pk}/device",
        {"device_id": str(replacement.pk)},
    )

    assert response.status_code == 204
    session.refresh_from_db()
    assert session.device == replacement


API_IDENTITY_PATHS = [
    ("get", "/api/playevent/{identity}", None),
    ("patch", "/api/playevent/{identity}", {"note": "Updated"}),
    ("delete", "/api/playevent/{identity}", None),
    ("get", "/api/session/{identity}", None),
    (
        "patch",
        "/api/session/{identity}",
        {"timestamp_end": "2026-08-20T11:00:00Z"},
    ),
    ("patch", "/api/session/{identity}/device", {"device_id": None}),
]


@pytest.mark.parametrize(("method", "path_template", "payload"), API_IDENTITY_PATHS)
def test_promoted_api_paths_reject_integer_ids(
    runtime_world, method, path_template, payload
):
    response = _api_request(
        runtime_world.client, method, path_template.format(identity=1), payload
    )

    assert response.status_code == 422


@pytest.mark.parametrize(("method", "path_template", "payload"), API_IDENTITY_PATHS)
def test_promoted_api_paths_reject_uuid4_ids(
    runtime_world, method, path_template, payload
):
    response = _api_request(
        runtime_world.client, method, path_template.format(identity=UUID4), payload
    )

    assert response.status_code == 422
    assert "version 7" in response.content.decode()


@pytest.mark.parametrize(
    ("method", "route_name", "object_name"),
    [
        ("get", "games:edit_playevent", "foreign_playevent"),
        (
            "post",
            "games:list_sessions_start_session_from_session",
            "foreign_session",
        ),
        ("get", "games:delete_statuschange", "foreign_statuschange"),
    ],
)
def test_promoted_html_views_keep_foreign_rows_undisclosed(
    runtime_world, method, route_name, object_name
):
    foreign_object = getattr(runtime_world, object_name)

    response = getattr(runtime_world.client, method)(
        reverse(route_name, args=[foreign_object.pk])
    )

    assert response.status_code == 404


@pytest.mark.parametrize(
    ("method", "path_template", "object_name", "payload"),
    [
        ("get", "/api/playevent/{identity}", "foreign_playevent", None),
        (
            "patch",
            "/api/session/{identity}",
            "foreign_session",
            {"timestamp_end": "2026-08-20T11:00:00Z"},
        ),
    ],
)
def test_promoted_api_views_keep_foreign_rows_undisclosed(
    runtime_world, method, path_template, object_name, payload
):
    foreign_object = getattr(runtime_world, object_name)

    response = _api_request(
        runtime_world.client,
        method,
        path_template.format(identity=foreign_object.pk),
        payload,
    )

    assert response.status_code == 404
