import re

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from games.models import SiteSetting, UserPreferences
from timetracker import settings_resolver


def _named_tag(body: str, tag: str, name: str) -> str:
    match = re.search(rf'<{tag}\b[^>]*\bname="{name}"[^>]*>', body)
    assert match is not None, f"no <{tag} name={name}> in the rendered page"
    return match.group()


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
    UserPreferences.objects.filter(user=user).update(
        default_purchase_currency="EUR",
        default_landing_page="games:list_games",
        theme="dark",
    )

    settings_resolver.clear_cache()
    response = auth_client.get(reverse("games:settings"))

    assert response.status_code == 200
    html = response.content.decode()
    assert "Settings" in html
    assert 'data-settings-scaffold=""' in html
    assert 'patch-url-template="/api/settings/user/__key__"' in html
    assert 'name="default_purchase_currency" value="EUR"' in html
    assert '<option value="games:list_games" selected>Games</option>' in html
    assert '<option value="dark" selected>Dark</option>' in html
    assert 'data-setting-key="DEFAULT_PURCHASE_CURRENCY"' in html
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


def test_settings_page_explains_personal_currency_scope(auth_client):
    html = auth_client.get(reverse("games:settings")).content.decode()

    assert "Preselected when adding a purchase." in html
    assert "Converted totals and statistics." in html


def test_settings_page_disables_only_the_navbar_theme_switcher(auth_client):
    html = auth_client.get(reverse("games:settings")).content.decode()
    toggle_start = html.index("<theme-toggle")
    toggle_end = html.index("</theme-toggle>", toggle_start) + len("</theme-toggle>")
    toggle_markup = html[toggle_start:toggle_end]
    toggle_button = re.search(
        r"<button\b[^>]*\bdata-pop-over-control\b[^>]*>",
        toggle_markup,
    )
    assert toggle_button is not None

    assert 'disabled="true"' in toggle_markup.split(">", 1)[0]
    assert 'disabled="disabled"' in toggle_button.group()
    assert "aria-label" not in toggle_button.group()
    interaction_surface = re.search(
        r"<span\b[^>]*\bdata-pop-over-trigger\b[^>]*>", toggle_markup
    )
    assert interaction_surface is not None
    assert (
        'aria-label="Theme switching is unavailable on settings pages."'
        in interaction_surface.group()
    )
    assert "disabled:opacity-50" in toggle_button.group()
    theme_select = html[
        html.index('<select name="theme"') : html.index(
            "</select>", html.index('<select name="theme"')
        )
    ]
    assert not re.search(r'\sdisabled(?:="disabled")?(?=\s|>)', theme_select)


def test_unset_selects_show_the_effective_builtin_defaults(auth_client):
    html = auth_client.get(reverse("games:settings")).content.decode()

    assert '<option value="" selected>Use site default (Sessions)</option>' in html
    assert '<option value="" selected>Use site default (25)</option>' in html
    assert '<option value="" selected>Use site default (System)</option>' in html
    assert '<option value="" selected>Use site default (ISO 8601)</option>' in html


def test_inherited_currency_is_empty_with_the_site_value_as_placeholder(auth_client):
    """Currency is a text input, so it carries the "Use site default (X)" message
    as a placeholder over an empty box rather than an empty option. Prefilling the
    inherited value instead would render identically to a personal choice."""
    SiteSetting.objects.create(key="DEFAULT_PURCHASE_CURRENCY", value="EUR")
    settings_resolver.clear_cache()

    html = auth_client.get(reverse("games:settings")).content.decode()

    currency = _named_tag(html, "input", "default_purchase_currency")
    assert 'placeholder="Use site default (EUR)"' in currency
    assert 'value="' not in currency


def test_personal_fields_carry_no_source_badge(auth_client):
    """Every personal control states the site value it inherits, so an origin
    badge would only repeat it. Provenance stays where a control cannot express
    it: site defaults and locked/read-only rows (#381)."""
    html = auth_client.get(reverse("games:settings")).content.decode()

    assert "<setting-source-badge" not in html
    assert "data-setting-origin" not in html
    # The controls themselves remain fully wired for live save.
    assert 'data-setting-key="DEFAULT_PURCHASE_CURRENCY"' in html
    assert 'data-live-setting-control=""' in html


def test_personal_theme_is_selected(auth_client, user):
    UserPreferences.objects.filter(user=user).update(theme="light")
    settings_resolver.clear_cache()

    html = auth_client.get(reverse("games:settings")).content.decode()

    assert '<select name="theme"' in html
    assert '<option value="light" selected>Light</option>' in html


def test_personal_page_size_is_selected(auth_client, user):
    UserPreferences.objects.filter(user=user).update(
        extra_preferences={"DEFAULT_PAGE_SIZE": 50}
    )
    settings_resolver.clear_cache()

    html = auth_client.get(reverse("games:settings")).content.decode()

    assert '<option value="50" selected>50</option>' in html


def test_personal_presentation_preferences_are_selected_and_live_saved(
    auth_client, user
):
    UserPreferences.objects.filter(user=user).update(
        display_time_zone="Pacific/Kiritimati",
        date_format_locale="cs",
        datetime_format="mdy_12h",
    )
    settings_resolver.clear_cache()

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
    SiteSetting.objects.create(
        key="DEFAULT_LANDING_PAGE",
        value="games:list_games",
    )
    SiteSetting.objects.create(key="THEME", value="dark")
    SiteSetting.objects.create(key="DATETIME_FORMAT", value="dmy_24h")
    settings_resolver.clear_cache()

    html = auth_client.get(reverse("games:settings")).content.decode()

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
