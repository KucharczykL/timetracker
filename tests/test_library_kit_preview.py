import pytest
from django.contrib.auth import get_user_model
from django.test import Client, override_settings
from django.urls import reverse

from games.urls import _library_kit_preview_urlpatterns


@pytest.fixture
def preview_client(db):
    user = get_user_model().objects.create_user(
        username="library-kit-preview-user",
        password="pw",
    )
    client = Client()
    client.force_login(user)
    return client


def test_preview_requires_authentication(db):
    response = Client().get(reverse("games:library_kit_preview"))

    assert response.status_code == 302
    assert response.url.startswith("/login/?next=/tracker/library-kit-preview/")


def test_preview_renders_static_component_states(preview_client):
    body = preview_client.get(reverse("games:library_kit_preview")).content.decode()
    assert "Library UI component kit" in body
    assert body.count('data-statistic-card=""') >= 3
    assert 'aria-label="0 Devices"' in body
    assert 'data-fact-list=""' in body
    assert "018f0000-0000-7000-8000-000000000000" in body
    assert "<copy-control" in body
    assert body.count('data-entity-summary-row=""') >= 3
    assert body.count('data-account-menu-trigger=""') == 2
    assert body.count("Admin settings") == 1
    assert body.count("data-preview-conversion-toast") == 3
    assert "dist/elements/copy-control.js" in body
    assert "dist/elements/library-kit-preview.js" in body


@override_settings(DEBUG=False)
def test_preview_patterns_are_absent_when_debug_is_off():
    assert _library_kit_preview_urlpatterns() == []


def test_preview_is_absent_from_production_navigation(preview_client):
    body = preview_client.get(reverse("games:list_sessions")).content.decode()
    assert "library-kit-preview" not in body
    assert "Library UI component kit" not in body
