import json

import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db


@pytest.fixture
def logged_in_client(client, django_user_model):
    user = django_user_model.objects.create_user(username="u", password="p")
    client.force_login(user)
    return client


@pytest.mark.parametrize("model", ["game", "session", "purchase", "playevent"])
def test_builder_page_renders(logged_in_client, model):
    response = logged_in_client.get(reverse("games:filter_builder", args=[model]))
    assert response.status_code == 200
    body = response.content.decode()
    assert "<filter-group" in body
    assert "<filter-builder" in body
    assert "<filter-summary" in body
    assert "<filter-count" in body
    # CSRF token present so preset save/delete fetches can send X-CSRFToken.
    assert "csrfmiddlewaretoken" in body


def test_builder_rejects_unknown_model(logged_in_client):
    response = logged_in_client.get(reverse("games:filter_builder", args=["nope"]))
    assert response.status_code == 404


def test_builder_prefills_filter_prop(logged_in_client):
    filter_json = json.dumps({"AND": [{"name": {"modifier": "EQUALS", "value": "Zelda"}}]})
    response = logged_in_client.get(
        reverse("games:filter_builder", args=["game"]), {"filter": filter_json}
    )
    assert response.status_code == 200
    # The raw JSON is escaped into the filter attribute; assert a distinctive token.
    assert "Zelda" in response.content.decode()


def test_builder_requires_login(client):
    response = client.get(reverse("games:filter_builder", args=["game"]))
    assert response.status_code == 302  # redirect to login
