import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from games.models import Device, UserPreferences


@pytest.fixture
def user(db):
    return get_user_model().objects.create_user(username="tester", password="pw")


@pytest.fixture
def auth_client(user):
    client = Client()
    client.force_login(user)
    return client


def test_settings_page_requires_login(db):
    response = Client().get("/tracker/settings")

    assert response.status_code == 302
    assert response.url == "/login/?next=/tracker/settings"


def test_settings_page_renders_resolved_preferences(auth_client, user):
    preferred = Device.objects.create(name="Steam Deck", type=Device.HANDHELD)
    Device.objects.create(name="Desktop", type=Device.PC)
    UserPreferences.objects.create(
        user=user,
        default_currency="EUR",
        default_device=preferred,
        default_landing_page="games:list_games",
    )

    response = auth_client.get(reverse("games:settings"))

    assert response.status_code == 200
    html = response.content.decode()
    assert "Settings" in html
    assert 'data-settings-scaffold=""' in html
    assert 'patch-url-template="/api/settings/user/__key__"' in html
    assert 'name="default_currency" value="EUR"' in html
    assert f'<option value="{preferred.pk}" selected>' in html
    assert '<option value="games:list_games" selected>Games</option>' in html
    assert 'data-setting-key="DEFAULT_CURRENCY"' in html
    assert 'data-setting-key="DEFAULT_DEVICE"' in html
    assert 'data-setting-key="DEFAULT_LANDING_PAGE"' in html


def test_settings_page_lists_devices_by_name(auth_client):
    Device.objects.create(name="Steam Deck", type=Device.HANDHELD)
    Device.objects.create(name="Desktop", type=Device.PC)

    html = auth_client.get(reverse("games:settings")).content.decode()

    assert html.index(">Desktop (PC)</option>") < html.index(
        ">Steam Deck (Handheld)</option>"
    )


def test_authenticated_navbar_links_to_settings(auth_client):
    html = auth_client.get(reverse("games:list_sessions")).content.decode()

    assert f'href="{reverse("games:settings")}"' in html
    assert ">Settings</a>" in html


def test_anonymous_navbar_does_not_link_to_settings(db):
    html = Client().get(reverse("login")).content.decode()

    assert 'href="/tracker/settings"' not in html
