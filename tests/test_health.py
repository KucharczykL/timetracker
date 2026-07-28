import pytest
from django.db import DatabaseError
from django.test import Client


@pytest.fixture
def strict_hosts(settings):
    settings.ALLOWED_HOSTS = ["allowed.example"]
    settings.DEBUG = False


def test_health_bypasses_host_validation(strict_hosts):
    response = Client().get("/health", SERVER_NAME="127.0.0.1")
    assert response.status_code == 200
    assert response.content == b"ok"


def test_disallowed_host_still_rejected_elsewhere(strict_hosts):
    response = Client(raise_request_exception=False).get("/", SERVER_NAME="127.0.0.1")
    assert response.status_code == 400


def test_health_requires_no_auth(strict_hosts):
    response = Client().get("/health", SERVER_NAME="allowed.example")
    assert response.status_code == 200


@pytest.mark.django_db
def test_ready_ok(strict_hosts):
    response = Client().get("/health/ready", SERVER_NAME="127.0.0.1")
    assert response.status_code == 200
    assert response.content == b"ok"


def test_ready_db_failure_returns_503(strict_hosts, monkeypatch):
    from common import middleware

    class BrokenConnection:
        def cursor(self):
            raise DatabaseError("down")

    monkeypatch.setattr(middleware, "connection", BrokenConnection())
    response = Client().get("/health/ready", SERVER_NAME="127.0.0.1")
    assert response.status_code == 503
