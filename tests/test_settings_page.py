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


def _picker(body: str, name: str) -> str:
    match = re.search(
        rf'<search-select\b[^>]*\bname="{name}".*?</search-select>', body, re.DOTALL
    )
    assert match is not None, f"no <search-select name={name}> in the rendered page"
    return match.group()


def _search_box(picker: str) -> str:
    match = re.search(r"<input\b[^>]*\bdata-search-select-search\b[^>]*>", picker)
    assert match is not None
    return match.group()


def _held(body: str, name: str) -> tuple[str | None, str]:
    """The held value (None for none) and the box text."""
    picker = _picker(body, name)
    hidden = re.search(rf'<input\b[^>]*\bname="{name}"[^>]*>', picker)
    assert hidden is not None, f"{name} holds nothing"
    value = re.search(r'\bvalue="([^"]*)"', hidden.group())
    assert value is not None
    box = re.search(r'\bvalue="([^"]*)"', _search_box(picker))
    held = None if "data-search-select-none" in hidden.group() else value.group(1)
    return held, box.group(1) if box else ""


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
    assert 'data-sectioned-page-scaffold=""' in html
    assert 'patch-url-template="/api/settings/user/__key__"' in html
    assert 'name="default_purchase_currency" value="EUR"' in html
    assert _held(html, "default_landing_page") == ("games:list_games", "Games")
    assert _held(html, "theme") == ("dark", "Dark")
    assert 'data-setting-key="DEFAULT_PURCHASE_CURRENCY"' in html
    assert 'data-setting-key="DEFAULT_LANDING_PAGE"' in html
    assert 'data-setting-key="DEFAULT_PAGE_SIZE"' in html
    assert 'data-setting-key="THEME"' in html
    assert '<theme-setting class="block w-full">' in html
    theme_picker = _picker(html, "theme")
    assert " required" not in theme_picker
    assert "data-live-setting-control" not in theme_picker
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
    theme_box = _search_box(_picker(html, "theme"))
    assert not re.search(r'\sdisabled(?:="[^"]*")?(?=\s|>)', theme_box)


def test_unset_selects_show_the_effective_builtin_defaults(auth_client):
    html = auth_client.get(reverse("games:settings")).content.decode()

    assert _held(html, "default_landing_page") == (None, "Use site default (Playtime)")
    assert _held(html, "default_page_size") == (None, "Use site default (25)")
    assert _held(html, "theme") == (None, "Use site default (System)")
    assert _held(html, "datetime_format") == (None, "Use site default (ISO 8601)")
    assert 'data-label="Use site default (Playtime)"' in _picker(
        html, "default_landing_page"
    )


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

    assert _held(html, "theme") == ("light", "Light")


def test_personal_page_size_is_selected(auth_client, user):
    UserPreferences.objects.filter(user=user).update(
        extra_preferences={"DEFAULT_PAGE_SIZE": 50}
    )
    settings_resolver.clear_cache()

    html = auth_client.get(reverse("games:settings")).content.decode()

    assert _held(html, "default_page_size") == ("50", "50")


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

    assert _held(html, "display_time_zone") == (
        "Pacific/Kiritimati",
        "Pacific/Kiritimati",
    )
    assert _held(html, "date_format_locale") == ("cs", "Čeština")
    assert _held(html, "datetime_format") == ("mdy_12h", "MM/DD/YYYY, 12-hour")
    assert 'data-setting-key="DISPLAY_TIME_ZONE"' in html
    assert 'data-setting-key="DATE_FORMAT_LOCALE"' in html
    assert 'data-setting-key="DATETIME_FORMAT"' in html
    datetime_picker = _picker(html, "datetime_format")
    assert "data-reload-after-save" in datetime_picker
    assert 'revert-on-leave="true"' in datetime_picker


def test_unset_selects_show_configured_site_defaults(auth_client):
    SiteSetting.objects.create(
        key="DEFAULT_LANDING_PAGE",
        value="games:list_games",
    )
    SiteSetting.objects.create(key="THEME", value="dark")
    SiteSetting.objects.create(key="DATETIME_FORMAT", value="dmy_24h")
    settings_resolver.clear_cache()

    html = auth_client.get(reverse("games:settings")).content.decode()

    assert _held(html, "default_landing_page") == (None, "Use site default (Games)")
    assert _held(html, "theme") == (None, "Use site default (Dark)")
    assert _held(html, "datetime_format") == (
        None,
        "Use site default (DD/MM/YYYY, 24-hour)",
    )


def test_unset_datetime_format_shows_environment_default(auth_client, monkeypatch):
    monkeypatch.setenv("DATETIME_FORMAT", "mdy_12h")
    settings_resolver.clear_cache()

    html = auth_client.get(reverse("games:settings")).content.decode()

    assert _held(html, "datetime_format") == (
        None,
        "Use site default (MM/DD/YYYY, 12-hour)",
    )


def test_authenticated_navbar_links_to_settings(auth_client):
    html = auth_client.get(reverse("games:list_sessions")).content.decode()

    assert f'href="{reverse("games:settings")}"' in html
    assert ">Settings</a>" in html


def test_anonymous_navbar_does_not_link_to_settings(db):
    html = Client().get(reverse("login")).content.decode()

    assert 'href="/tracker/settings"' not in html
