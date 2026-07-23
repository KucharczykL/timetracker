"""Integration coverage for the DEBUG-only settings UI kit gallery."""

import json
import re

import pytest
from django.contrib.auth import get_user_model
from django.test import Client, override_settings
from django.urls import reverse

from games.models import SiteSetting, UserPreferences
from games.urls import _settings_kit_preview_urlpatterns


@pytest.fixture
def preview_user(db):
    return get_user_model().objects.create_user(username="previewer", password="pw")


@pytest.fixture
def preview_client(preview_user):
    client = Client()
    client.force_login(preview_user)
    return client


def _preview_url() -> str:
    return reverse("games:settings_kit_preview")


def _patch_url(key: str) -> str:
    return reverse("games:settings_kit_preview_patch", args=[key])


def _patch(client: Client, key: str, value):
    return client.patch(
        _patch_url(key),
        json.dumps({"value": value}),
        content_type="application/json",
    )


def _named_tag(body: str, tag: str, name: str) -> str:
    match = re.search(rf'<{tag}\b[^>]*\bname="{name}"[^>]*>', body)
    assert match is not None
    return match.group()


def _theme_toggle_markup(body: str) -> tuple[str, str]:
    start = body.index("<theme-toggle")
    end = body.index("</theme-toggle>", start) + len("</theme-toggle>")
    markup = body[start:end]
    button = re.search(r"<button\b[^>]*\bdata-pop-over-trigger\b[^>]*>", markup)
    assert button is not None
    return markup, button.group()


def test_preview_requires_authentication(db):
    response = Client().get(_preview_url())

    assert response.status_code == 302
    assert response.url.startswith(f"/login/?next={_preview_url()}")


def test_preview_renders_the_complete_gallery(preview_client):
    response = preview_client.get(_preview_url())
    body = response.content.decode()

    assert response.status_code == 200
    assert "Settings UI kit preview" in body
    assert "DEBUG only" in body
    assert "No persistence" in body
    assert body.count('data-settings-section=""') == 6
    assert body.count('data-settings-section-header=""') == 6
    assert body.count('data-settings-section-content=""') == 6
    assert body.count("<settings-section-nav") == 1
    assert body.count("<fieldset") == 2
    assert body.count("data-supported-form-layout=") == 3
    assert body.count("data-settings-field-layout") == 4
    assert "Constrained vertical form" in body
    assert "Responsive paired fields" in body
    assert "Responsive compact grid" in body
    assert "Option 1" not in body
    assert "Leading checkbox" not in body
    assert "Divider hierarchy" not in body
    assert "Settings sections bottom sheet" in body
    assert "bottom-sheet and sticky-rail behavior" in body
    assert "More menu" not in body
    assert "priority-plus and sticky-rail" not in body

    assert 'type="checkbox"' in _named_tag(body, "input", "enabled")
    assert _named_tag(body, "select", "destination")
    assert 'type="number"' in _named_tag(body, "input", "limit")
    assert 'type="text"' in _named_tag(body, "input", "display_name")
    assert " disabled" in _named_tag(body, "input", "pinned_url")
    assert "Change APP_URL in the environment and restart" in body

    for source in ("user", "database", "env", "env_file", "dotenv", "ini", "default"):
        assert f'data-setting-origin="{source}"' in body
    for tone in ("Brand", "Neutral", "Success", "Warning", "Danger"):
        assert f">{tone}</span>" in body

    assert body.count("data-masked-secret") == 2
    assert 'value="••••••••"' in body
    assert 'placeholder="Not set"' in body
    assert "super-secret-value" not in body
    assert "dist/elements/settings-section-nav.js" in body
    assert "dist/elements/live-setting-fields.js" in body
    assert "dist/elements/pop-over.js" in body
    assert _patch_url("__key__") in body


def test_preview_disables_only_the_navbar_theme_switcher(preview_client):
    body = preview_client.get(_preview_url()).content.decode()
    toggle_markup, toggle_button = _theme_toggle_markup(body)

    assert 'disabled="true"' in toggle_markup.split(">", 1)[0]
    assert 'disabled="disabled"' in toggle_button
    assert (
        'aria-label="Theme switching is unavailable on settings pages."'
        in toggle_button
    )
    assert "disabled:opacity-50" in toggle_button
    assert not re.search(
        r'\sdisabled(?:="disabled")?(?=\s|>)',
        _named_tag(body, "select", "destination"),
    )


def test_preview_patch_succeeds_with_toast_without_persistence(
    preview_client, preview_user
):
    response = _patch(preview_client, "PREVIEW_DISPLAY_NAME", "Saved name")

    assert response.status_code == 204
    trigger = json.loads(response.headers["HX-Trigger"])
    assert trigger["show-toast"] == {
        "message": "Display name saved (preview only)",
        "type": "success",
    }
    assert not UserPreferences.objects.filter(user=preview_user).exists()
    assert not SiteSetting.objects.exists()


def test_preview_patch_can_exercise_rejection_and_validation(preview_client):
    rejected = _patch(preview_client, "PREVIEW_DISPLAY_NAME", "reject")
    unknown = _patch(preview_client, "UNKNOWN", "value")
    malformed = preview_client.patch(
        _patch_url("PREVIEW_DISPLAY_NAME"),
        "not-json",
        content_type="application/json",
    )
    wrong_method = preview_client.get(_patch_url("PREVIEW_DISPLAY_NAME"))

    assert rejected.status_code == 422
    assert rejected.json()["detail"] == "Rejected intentionally by the preview."
    assert unknown.status_code == 404
    assert malformed.status_code == 400
    assert wrong_method.status_code == 405


@override_settings(DEBUG=False)
def test_preview_routes_are_absent_when_debug_is_off():
    assert _settings_kit_preview_urlpatterns() == []
