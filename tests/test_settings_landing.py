from datetime import datetime

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from games.models import UserPreferences


@pytest.fixture
def auth_client(db):
    user = get_user_model().objects.create_user(username="tester", password="pw")
    client = Client()
    client.force_login(user)
    return client, user


@pytest.mark.parametrize(
    ("url_name", "expected_name"),
    [
        ("games:list_sessions", "games:list_sessions"),
        ("games:list_games", "games:list_games"),
        ("games:list_purchases", "games:list_purchases"),
    ],
)
def test_index_redirects_to_selected_landing_page(auth_client, url_name, expected_name):
    client, user = auth_client
    UserPreferences.objects.create(user=user, default_landing_page=url_name)

    response = client.get(reverse("games:index"))

    assert response.status_code == 302
    assert response.url == reverse(expected_name)


def test_index_redirects_to_current_year_stats(auth_client):
    client, user = auth_client
    UserPreferences.objects.create(
        user=user,
        default_landing_page="games:stats_by_year",
    )

    response = client.get(reverse("games:index"))

    assert response.status_code == 302
    assert response.url == reverse("games:stats_by_year", args=[datetime.now().year])


def test_index_falls_back_to_sessions_for_poisoned_landing_page(auth_client):
    client, user = auth_client
    UserPreferences.objects.create(
        user=user, default_landing_page="https://example.com"
    )

    response = client.get(reverse("games:index"))

    assert response.status_code == 302
    assert response.url == reverse("games:list_sessions")
