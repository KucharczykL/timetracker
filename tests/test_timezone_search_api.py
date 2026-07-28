"""/api/timezones/search: the SearchSelect option feed for the per-timestamp
zone picker — the /api/platforms/groups list[StringOption] pattern over tzdata,
plus the pinned clear-to-NULL row on the browse-all response."""

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

pytestmark = pytest.mark.django_db


@pytest.fixture
def auth_client(db):
    user = get_user_model().objects.create_user(username="tester", password="pw")
    client = Client()
    client.force_login(user)
    return client


def test_requires_auth():
    response = Client().get("/api/timezones/search")
    assert response.status_code == 401


def test_returns_zone_options_capped_at_limit(auth_client):
    response = auth_client.get("/api/timezones/search")
    assert response.status_code == 200
    options = response.json()
    assert len(options) == 10  # the default limit, clear row included
    assert options[0] == {"value": "", "label": "Use account display zone", "data": {}}
    zone_option = options[1]
    assert set(zone_option) == {"value", "label", "data"}
    assert zone_option["value"] == zone_option["label"]
    assert zone_option["data"] == {}


def test_query_filters_case_insensitively_and_omits_the_clear_row(auth_client):
    response = auth_client.get("/api/timezones/search", {"q": "tokyo", "limit": 50})
    values = [option["value"] for option in response.json()]
    assert values == ["Asia/Tokyo"]  # no "" row while filtering


def test_the_clear_row_is_the_way_back_to_null(auth_client):
    """Every add-form session captures a zone, so a ""-valued option is the
    only reachable route back to NULL ("assume the account display zone")."""
    response = auth_client.get("/api/timezones/search", {"limit": 3})
    options = response.json()
    assert options[0]["value"] == ""
    assert len(options) == 3
    assert all(option["value"] != "" for option in options[1:])


def test_results_are_sorted(auth_client):
    response = auth_client.get("/api/timezones/search", {"q": "Europe/P", "limit": 50})
    values = [option["value"] for option in response.json()]
    assert values == sorted(values)
    assert "Europe/Prague" in values
