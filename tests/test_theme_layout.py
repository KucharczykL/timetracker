from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from games.models import SiteSetting, UserPreferences
from timetracker import settings_resolver
from common.components import Div, ThemeToggle, assert_unique_element_ids


def _root_tag(html: str) -> str:
    start = html.index("<html")
    return html[start : html.index(">", start) + 1]


def test_anonymous_document_has_browser_theme_configuration(db):
    html = Client().get(reverse("login")).content.decode()
    root = _root_tag(html)

    assert 'data-theme-mode="browser"' in root
    assert 'data-theme-preferences="system light dark"' in root
    assert "data-theme-preference=" not in root
    assert "data-theme-personal-preference=" not in root
    assert "data-theme-inherited-preference=" not in root
    assert "data-theme-source=" not in root
    assert "data-theme-update-url=" not in root
    assert "data-theme-csrf=" not in root


def test_account_document_has_complete_authoritative_theme_configuration(db):
    user = get_user_model().objects.create_user(username="theme-user", password="pw")
    UserPreferences.objects.create(user=user, theme="dark")
    client = Client()
    client.force_login(user)

    html = client.get(reverse("games:settings")).content.decode()
    root = _root_tag(html)

    assert 'data-theme-mode="account"' in root
    assert 'data-theme-preference="dark"' in root
    assert 'data-theme-personal-preference="dark"' in root
    assert 'data-theme-inherited-preference="system"' in root
    assert 'data-theme-source="user"' in root
    update_url = reverse("api-1.0.0:update_user_setting", args=["THEME"])
    assert f'data-theme-update-url="{update_url}"' in root
    assert 'data-theme-csrf="' in root


def test_account_document_represents_null_personal_preference_explicitly(db):
    user = get_user_model().objects.create_user(username="theme-user", password="pw")
    SiteSetting.objects.create(key="THEME", value="dark")
    settings_resolver.clear_cache()
    client = Client()
    client.force_login(user)

    root = _root_tag(client.get(reverse("games:settings")).content.decode())

    assert 'data-theme-preference="dark"' in root
    assert 'data-theme-personal-preference=""' in root
    assert 'data-theme-inherited-preference="dark"' in root
    assert 'data-theme-source="database"' in root


def test_external_classic_bootstrap_is_first_script_and_precedes_css(db):
    html = Client().get(reverse("login")).content.decode()
    bootstrap = 'src="/static/js/dist/theme-bootstrap.js"'

    bootstrap_index = html.index(bootstrap)
    script_start = html.rfind("<script", 0, bootstrap_index)
    script_end = html.index(">", bootstrap_index)
    bootstrap_tag = html[script_start : script_end + 1]

    assert script_start == html.index("<script")
    assert bootstrap_index < html.index('href="/static/base.css"')
    assert 'type="module"' not in bootstrap_tag
    assert " defer" not in bootstrap_tag
    assert " async" not in bootstrap_tag
    assert "readCookie" not in html
    assert 'theme-bootstrap">' not in html


def test_theme_component_keeps_three_icons_and_tooltip(db):
    html = Client().get(reverse("login")).content.decode()

    assert "<theme-toggle" in html
    assert 'data-theme-icon="system"' in html
    assert "data-theme-system-half" in html
    assert 'data-theme-icon="light"' in html
    assert 'data-theme-icon="dark"' in html
    assert "<pop-over" in html
    assert 'role="tooltip"' in html
    assert "data-theme-tooltip" in html
    assert "dist/elements/theme-toggle.js" in html


def test_multiple_theme_toggles_have_unique_tooltip_ids():
    assert_unique_element_ids(
        Div()[ThemeToggle(instance_key="first"), ThemeToggle(instance_key="second")]
    )


def test_layout_removes_legacy_inline_navbar_theme_handler(db):
    html = Client().get(reverse("login")).content.decode()

    assert "themeToggleBtn.addEventListener" not in html
    assert "localStorage.getItem('color-theme')" not in html
