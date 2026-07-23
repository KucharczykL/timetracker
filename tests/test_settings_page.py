import re

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from games.models import Device, SiteSetting, UserPreferences
from timetracker import settings_resolver


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
        theme="dark",
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
    assert '<option value="dark" selected>Dark</option>' in html
    assert 'data-setting-key="DEFAULT_CURRENCY"' in html
    assert 'data-setting-key="DEFAULT_DEVICE"' in html
    assert 'data-setting-key="DEFAULT_LANDING_PAGE"' in html
    assert 'data-setting-key="DEFAULT_PAGE_SIZE"' in html
    assert 'data-setting-key="THEME"' in html
    assert '<theme-setting class="block w-full">' in html
    theme_select = html[
        html.index('<select name="theme"') : html.index(
            "</select>", html.index('<select name="theme"')
        )
    ]
    assert " required" not in theme_select
    assert "data-live-setting-control" not in theme_select
    assert "System follows the operating-system theme." in html


def test_settings_page_disables_only_the_navbar_theme_switcher(auth_client):
    html = auth_client.get(reverse("games:settings")).content.decode()
    toggle_start = html.index("<theme-toggle")
    toggle_end = html.index("</theme-toggle>", toggle_start) + len("</theme-toggle>")
    toggle_markup = html[toggle_start:toggle_end]
    toggle_button = re.search(
        r"<button\b[^>]*\bdata-pop-over-trigger\b[^>]*>",
        toggle_markup,
    )
    assert toggle_button is not None

    assert 'disabled="true"' in toggle_markup.split(">", 1)[0]
    assert 'disabled="disabled"' in toggle_button.group()
    assert (
        'aria-label="Theme switching is unavailable on settings pages."'
        in toggle_button.group()
    )
    assert "disabled:opacity-50" in toggle_button.group()
    theme_select = html[
        html.index('<select name="theme"') : html.index(
            "</select>", html.index('<select name="theme"')
        )
    ]
    assert not re.search(r'\sdisabled(?:="disabled")?(?=\s|>)', theme_select)


def test_settings_page_lists_devices_by_name(auth_client):
    Device.objects.create(name="Steam Deck", type=Device.HANDHELD)
    Device.objects.create(name="Desktop", type=Device.PC)

    html = auth_client.get(reverse("games:settings")).content.decode()

    assert html.index(">Desktop (PC)</option>") < html.index(
        ">Steam Deck (Handheld)</option>"
    )


def test_unset_selects_show_the_effective_builtin_defaults(auth_client):
    html = auth_client.get(reverse("games:settings")).content.decode()

    assert '<option value="" selected>Use site default (No device)</option>' in html
    assert '<option value="" selected>Use site default (Sessions)</option>' in html
    assert '<option value="" selected>Use site default (25)</option>' in html
    assert '<option value="" selected>Use site default (System)</option>' in html
    assert '<option value="" selected>Use site default (ISO 8601)</option>' in html


def test_personal_theme_is_selected(auth_client, user):
    UserPreferences.objects.create(user=user, theme="light")

    html = auth_client.get(reverse("games:settings")).content.decode()

    assert '<select name="theme"' in html
    assert '<option value="light" selected>Light</option>' in html


def test_personal_page_size_is_selected(auth_client, user):
    UserPreferences.objects.create(
        user=user, extra_preferences={"DEFAULT_PAGE_SIZE": 50}
    )

    html = auth_client.get(reverse("games:settings")).content.decode()

    assert '<option value="50" selected>50</option>' in html


def test_personal_presentation_preferences_are_selected_and_live_saved(
    auth_client, user
):
    UserPreferences.objects.create(
        user=user,
        display_time_zone="Pacific/Kiritimati",
        date_format_locale="cs",
        datetime_format="mdy_12h",
    )

    html = auth_client.get(reverse("games:settings")).content.decode()

    assert '<select name="display_time_zone"' in html
    assert (
        '<option value="Pacific/Kiritimati" selected>Pacific/Kiritimati</option>'
        in html
    )
    assert '<select name="date_format_locale"' in html
    assert '<option value="cs" selected>Čeština</option>' in html
    assert '<select name="datetime_format"' in html
    assert '<option value="mdy_12h" selected>MM/DD/YYYY, 12-hour</option>' in html
    assert 'data-setting-key="DISPLAY_TIME_ZONE"' in html
    assert 'data-setting-key="DATE_FORMAT_LOCALE"' in html
    assert 'data-setting-key="DATETIME_FORMAT"' in html
    datetime_select = html[
        html.index('<select name="datetime_format"') : html.index(
            "</select>", html.index('<select name="datetime_format"')
        )
    ]
    assert "data-reload-after-save" in datetime_select


def test_unset_selects_show_configured_site_defaults(auth_client):
    desktop = Device.objects.create(name="Desktop", type=Device.PC)
    SiteSetting.objects.create(key="DEFAULT_DEVICE", value=desktop.pk)
    SiteSetting.objects.create(
        key="DEFAULT_LANDING_PAGE",
        value="games:list_games",
    )
    SiteSetting.objects.create(key="THEME", value="dark")
    SiteSetting.objects.create(key="DATETIME_FORMAT", value="dmy_24h")
    settings_resolver.clear_cache()

    html = auth_client.get(reverse("games:settings")).content.decode()

    assert '<option value="" selected>Use site default (Desktop (PC))</option>' in html
    assert '<option value="" selected>Use site default (Games)</option>' in html
    assert '<option value="" selected>Use site default (Dark)</option>' in html
    assert (
        '<option value="" selected>Use site default (DD/MM/YYYY, 24-hour)</option>'
        in html
    )


def test_unset_datetime_format_shows_environment_default(auth_client, monkeypatch):
    monkeypatch.setenv("DATETIME_FORMAT", "mdy_12h")
    settings_resolver.clear_cache()

    html = auth_client.get(reverse("games:settings")).content.decode()

    assert (
        '<option value="" selected>Use site default (MM/DD/YYYY, 12-hour)</option>'
        in html
    )


def test_authenticated_navbar_links_to_settings(auth_client):
    html = auth_client.get(reverse("games:list_sessions")).content.decode()

    assert f'href="{reverse("games:settings")}"' in html
    assert ">Settings</a>" in html


def test_anonymous_navbar_does_not_link_to_settings(db):
    html = Client().get(reverse("login")).content.decode()

    assert 'href="/tracker/settings"' not in html
