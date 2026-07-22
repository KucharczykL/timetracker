import pytest
from django.contrib.auth import get_user_model
from django.test import Client, override_settings

from games.models import UserPreferences


@pytest.fixture
def login_user(db):
    return get_user_model().objects.create_user(username="theme-user", password="pw")


def test_login_writes_saved_theme_cookie_without_migration_marker(login_user):
    UserPreferences.objects.create(user=login_user, theme="dark")

    response = Client().post(
        "/login/", {"username": login_user.username, "password": "pw"}
    )

    assert response.status_code == 302
    assert response.cookies["color-theme"].value == "dark"
    # A saved account clears any stale marker left by a previous uninitialized
    # login rather than merely omitting the cookie from this response.
    assert response.cookies["color-theme-migrate"]["max-age"] == 0


def test_login_marks_uninitialized_account_for_browser_migration(login_user):
    response = Client().post(
        "/login/", {"username": login_user.username, "password": "pw"}
    )

    assert response.status_code == 302
    assert response.cookies["color-theme"].value == "auto"
    assert response.cookies["color-theme-migrate"].value == "1"


@override_settings(SESSION_COOKIE_SECURE=True)
def test_login_theme_cookies_follow_session_secure_setting(login_user):
    response = Client().post(
        "/login/", {"username": login_user.username, "password": "pw"}
    )

    assert response.cookies["color-theme"]["secure"] is True
    assert response.cookies["color-theme-migrate"]["secure"] is True
