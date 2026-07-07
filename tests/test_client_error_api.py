"""Tests for the client-error report endpoint (POST /api/client-error).

The endpoint exists so a malformed-JSON-prop failure in the browser produces a
real server log line (issue #232) instead of an invisible console.warn.
"""

import pytest
from django.contrib.auth import get_user_model
from django.test import Client


@pytest.fixture
def user(db):
    return get_user_model().objects.create_user(username="tester", password="pw")


@pytest.fixture
def auth_client(user):
    client = Client()
    client.force_login(user)
    return client


def _url() -> str:
    return "/api/client-error/"  # trailing slash: router `.post("/")`, matches /api/presets/


def _payload(**overrides) -> dict:
    payload = {
        "error_id": "abcd1234",
        "context": "filter-widgets[data-included]",
        "detail": "SyntaxError: Unexpected token",
        "url": "https://example.test/games/",
    }
    payload.update(overrides)
    return payload


def test_anonymous_is_rejected(db):
    anonymous = Client()
    response = anonymous.post(_url(), _payload(), content_type="application/json")
    assert response.status_code == 401


def test_valid_report_returns_204_and_logs(auth_client, capture_client_errors_logger):
    with capture_client_errors_logger() as caplog:
        response = auth_client.post(_url(), _payload(), content_type="application/json")
    assert response.status_code == 204
    records = [r for r in caplog.records if r.name == "client_errors"]
    assert len(records) == 1
    message = records[0].getMessage()
    assert "abcd1234" in message
    assert "filter-widgets[data-included]" in message


def test_crlf_is_stripped_from_log_line(auth_client, capture_client_errors_logger):
    with capture_client_errors_logger() as caplog:
        response = auth_client.post(
            _url(),
            _payload(detail="line one\r\nFORGED: fake entry"),
            content_type="application/json",
        )
    assert response.status_code == 204
    message = caplog.records[0].getMessage()
    assert "\n" not in message
    assert "\r" not in message


@pytest.mark.parametrize("field", ["error_id", "context", "detail", "url"])
def test_overlength_field_rejected_with_422(auth_client, field):
    response = auth_client.post(
        _url(), _payload(**{field: "x" * 1000}), content_type="application/json"
    )
    assert response.status_code == 422
