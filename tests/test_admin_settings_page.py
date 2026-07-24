from html.parser import HTMLParser
import re

import pytest
from django import forms
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from games.models import Device, SiteSetting
from timetracker import config as config_module
from timetracker import settings_resolver
from timetracker.config import ResolvedSetting, SettingSource
from timetracker.settings_registry import (
    DATETIME_FORMAT_CHOICES,
    FORMAT_LOCALE_CHOICES,
    LANDING_PAGE_CHOICES,
    PAGE_SIZE_CHOICES,
    THEME_CHOICES,
)

SITE_SETTING_KEYS = (
    "DEFAULT_CURRENCY",
    "DEFAULT_DEVICE",
    "DEFAULT_LANDING_PAGE",
    "DEFAULT_PAGE_SIZE",
    "THEME",
    "DISPLAY_TIME_ZONE",
    "DATE_FORMAT_LOCALE",
    "DATETIME_FORMAT",
)


@pytest.fixture
def clean_site_setting_sources(monkeypatch, tmp_path):
    for key in SITE_SETTING_KEYS:
        monkeypatch.delenv(key, raising=False)
        monkeypatch.delenv(f"{key}__FILE", raising=False)
    monkeypatch.setenv("ENV_FILE", str(tmp_path / "missing.env"))
    monkeypatch.setenv("INI_FILE", str(tmp_path / "missing.ini"))
    config_module.reset_caches()
    settings_resolver.clear_cache()


@pytest.fixture
def normal_user(db):
    return get_user_model().objects.create_user(
        username="settings-user",
        password="pw",
    )


@pytest.fixture
def superuser(db):
    return get_user_model().objects.create_superuser(
        username="settings-admin",
        password="pw",
    )


@pytest.fixture
def normal_client(normal_user):
    client = Client()
    client.force_login(normal_user)
    return client


@pytest.fixture
def superuser_client(superuser):
    client = Client()
    client.force_login(superuser)
    return client


def _opening_control_tag(html: str, field_name: str) -> str:
    match = re.search(
        rf"<(?:input|select)\b[^>]*\bname=\"{re.escape(field_name)}\"[^>]*>",
        html,
    )
    assert match is not None, f"missing native control {field_name!r}"
    return match.group(0)


def _field_source_markup(html: str, key: str, field_name: str) -> str:
    badge_start = html.index(f'<setting-source-badge key="{key}">')
    control_start = html.index(f'name="{field_name}"', badge_start)
    return html[badge_start:control_start]


def _is_disabled(control_tag: str) -> bool:
    return re.search(r"\sdisabled(?:=\"disabled\")?(?=\s|>)", control_tag) is not None


def _theme_toggle_markup(html: str) -> tuple[str, str]:
    start = html.index("<theme-toggle")
    end = html.index("</theme-toggle>", start) + len("</theme-toggle>")
    markup = html[start:end]
    button = re.search(r"<button\b[^>]*\bdata-pop-over-control\b[^>]*>", markup)
    assert button is not None
    return markup, button.group()


class _NavbarAccountActions(HTMLParser):
    _VOID_ELEMENTS = {"input"}

    def __init__(self) -> None:
        super().__init__()
        self.stack: list[tuple[str, dict[str, str | None]]] = []
        self.actions: dict[str, dict[str, object]] = {}

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        attributes = dict(attrs)
        ancestor_ids = {
            value
            for _ancestor_tag, ancestor_attributes in self.stack
            if (value := ancestor_attributes.get("id")) is not None
        }
        in_menu = "navbarMenu" in ancestor_ids
        if tag == "a" and attributes.get("href") == reverse("games:settings"):
            self.actions["settings"] = {"in_menu": in_menu}
        elif tag == "a" and attributes.get("href") == reverse("games:admin_settings"):
            self.actions["admin_settings"] = {"in_menu": in_menu}
        elif tag == "form" and attributes.get("action") == reverse("logout"):
            self.actions["logout"] = {
                "in_menu": in_menu,
                "method": attributes.get("method"),
                "role": attributes.get("role"),
                "csrf": False,
                "button": {},
            }
        elif "logout" in self.actions and self._inside_logout_form():
            if tag == "input" and attributes.get("name") == "csrfmiddlewaretoken":
                self.actions["logout"]["csrf"] = True
            elif tag == "button":
                self.actions["logout"]["button"] = attributes
        if tag not in self._VOID_ELEMENTS:
            self.stack.append((tag, attributes))

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                return

    def _inside_logout_form(self) -> bool:
        return any(
            tag == "form" and attrs.get("action") == reverse("logout")
            for tag, attrs in self.stack
        )


def _navbar_account_actions(html: str) -> dict[str, dict[str, object]]:
    parser = _NavbarAccountActions()
    parser.feed(html)
    return parser.actions


def test_admin_settings_page_requires_login(db):
    response = Client().get("/tracker/admin-settings")

    assert response.status_code == 302
    assert response.url == "/login/?next=/tracker/admin-settings"


def test_admin_settings_page_returns_component_rendered_403_to_normal_user(
    normal_client,
):
    response = normal_client.get(reverse("games:admin_settings"))

    assert response.status_code == 403
    html = response.content.decode()
    assert html.startswith("<!DOCTYPE html>")
    assert 'id="main-container"' in html
    assert "Admin settings" in html
    assert "Superuser access is required" in html
    assert 'patch-url-template="/api/settings/site/__key__"' not in html


def test_superuser_receives_admin_settings_page(
    superuser_client,
    clean_site_setting_sources,
):
    response = superuser_client.get(reverse("games:admin_settings"))

    assert response.status_code == 200
    html = response.content.decode()
    assert "Admin settings" in html
    assert "Defaults inherited by users who have not saved personal overrides." in html
    assert 'data-settings-scaffold=""' in html


def test_admin_settings_page_explains_site_currency_scope(
    superuser_client,
    clean_site_setting_sources,
):
    html = superuser_client.get(reverse("games:admin_settings")).content.decode()

    assert (
        "Used for purchase entry by users without a personal value, purchases "
        "saved without user context, and the FX/reporting target." in html
    )
    assert (
        "A personal value affects only your purchase entry; purchases saved "
        "without user context and FX/reporting continue to use the site value."
        not in html
    )


def test_admin_settings_page_disables_only_the_navbar_theme_switcher(
    superuser_client,
    clean_site_setting_sources,
):
    html = superuser_client.get(reverse("games:admin_settings")).content.decode()
    toggle_markup, toggle_button = _theme_toggle_markup(html)

    assert 'disabled="true"' in toggle_markup.split(">", 1)[0]
    assert 'disabled="disabled"' in toggle_button
    assert "aria-label" not in toggle_button
    interaction_surface = re.search(
        r"<span\b[^>]*\bdata-pop-over-trigger\b[^>]*>", toggle_markup
    )
    assert interaction_surface is not None
    assert (
        'aria-label="Theme switching is unavailable on settings pages."'
        in interaction_surface.group()
    )
    assert "disabled:opacity-50" in toggle_button
    assert not _is_disabled(_opening_control_tag(html, "theme"))


def test_admin_page_renders_exact_site_setting_slice_in_stable_order(
    superuser_client,
    clean_site_setting_sources,
):
    html = superuser_client.get(reverse("games:admin_settings")).content.decode()

    rendered_keys = re.findall(r'data-setting-key="([^"]+)"', html)
    assert rendered_keys == list(SITE_SETTING_KEYS)
    assert "TZ" not in rendered_keys
    assert not {
        "DEBUG",
        "SECRET_KEY",
        "APP_URL",
        "DEV_LOGIN_PREFILL",
        "ALLOWED_HOSTS",
        "DATA_DIR",
        "HASHED_STATIC",
    }.intersection(rendered_keys)


def test_admin_page_uses_generic_site_patch_for_theme_and_reload_controls(
    superuser_client,
    clean_site_setting_sources,
):
    html = superuser_client.get(reverse("games:admin_settings")).content.decode()

    assert 'patch-url-template="/api/settings/site/__key__"' in html
    assert "<theme-setting" not in html
    for field_name in (
        "theme",
        "display_time_zone",
        "date_format_locale",
        "datetime_format",
    ):
        tag = _opening_control_tag(html, field_name)
        assert 'data-live-setting-control=""' in tag
        assert 'data-reload-after-save=""' in tag


def test_site_settings_form_uses_typed_fields_and_registry_choices(
    clean_site_setting_sources,
):
    from games.views.settings import SiteSettingsForm

    form = SiteSettingsForm()

    assert isinstance(form.fields["default_currency"], forms.CharField)
    assert isinstance(form.fields["default_device"], forms.ModelChoiceField)
    assert isinstance(form.fields["default_landing_page"], forms.ChoiceField)
    assert isinstance(form.fields["default_page_size"], forms.TypedChoiceField)
    assert isinstance(form.fields["theme"], forms.ChoiceField)
    assert isinstance(form.fields["display_time_zone"], forms.ChoiceField)
    assert isinstance(form.fields["date_format_locale"], forms.ChoiceField)
    assert isinstance(form.fields["datetime_format"], forms.ChoiceField)
    assert list(form.fields["default_landing_page"].choices) == [
        ("", "Use configured default"),
        *LANDING_PAGE_CHOICES,
    ]
    assert list(form.fields["default_page_size"].choices) == [
        ("", "Use configured default"),
        *((size, str(size)) for size in PAGE_SIZE_CHOICES),
    ]
    assert list(form.fields["theme"].choices) == [
        ("", "Use configured default"),
        *THEME_CHOICES,
    ]
    assert list(form.fields["date_format_locale"].choices) == [
        ("", "Use configured default"),
        *FORMAT_LOCALE_CHOICES,
    ]
    assert list(form.fields["datetime_format"].choices) == [
        ("", "Use configured default"),
        *DATETIME_FORMAT_CHOICES,
    ]


def test_admin_page_lists_device_rows_and_select_options(
    superuser_client,
    clean_site_setting_sources,
):
    Device.objects.create(name="Steam Deck", type=Device.HANDHELD)
    desktop = Device.objects.create(name="Desktop", type=Device.PC)

    html = superuser_client.get(reverse("games:admin_settings")).content.decode()

    assert html.count(">Use configured default</option>") == 7
    assert html.index(
        f'<option value="{desktop.pk}">Desktop (PC)</option>'
    ) < html.index(">Steam Deck (Handheld)</option>")
    for value, label in (
        *LANDING_PAGE_CHOICES,
        *THEME_CHOICES,
        *FORMAT_LOCALE_CHOICES,
        *DATETIME_FORMAT_CHOICES,
        ("Pacific/Kiritimati", "Pacific/Kiritimati"),
    ):
        assert f'<option value="{value}"' in html
        assert f">{label}</option>" in html
    for size in PAGE_SIZE_CHOICES:
        assert f'<option value="{size}"' in html


def test_admin_page_renders_database_and_default_values_with_source_badges(
    superuser_client,
    clean_site_setting_sources,
):
    SiteSetting.objects.create(key="DEFAULT_CURRENCY", value="EUR")
    settings_resolver.clear_cache()

    html = superuser_client.get(reverse("games:admin_settings")).content.decode()

    currency = _opening_control_tag(html, "default_currency")
    assert 'value="EUR"' in currency
    assert 'data-setting-origin="database"' in _field_source_markup(
        html, "DEFAULT_CURRENCY", "default_currency"
    )
    page_size = _opening_control_tag(html, "default_page_size")
    assert not _is_disabled(page_size)
    assert '<option value="25" selected>25</option>' in html
    assert 'data-setting-origin="default"' in _field_source_markup(
        html, "DEFAULT_PAGE_SIZE", "default_page_size"
    )


@pytest.mark.parametrize(
    "source",
    (
        SettingSource.ENV_FILE,
        SettingSource.ENV,
        SettingSource.DOTENV,
        SettingSource.INI,
    ),
)
def test_locked_source_renders_effective_value_badge_reason_and_disabled_control(
    source,
    superuser_client,
    clean_site_setting_sources,
    monkeypatch,
    tmp_path,
):
    from games.views import settings as settings_view

    if source is SettingSource.ENV_FILE:
        # No editable site key currently opts into __FILE. Exercise the page's
        # resolver contract, as the command-boundary tests do for this source.
        original_resolve = settings_view.resolve_with_origin
        monkeypatch.setattr(
            settings_view,
            "resolve_with_origin",
            lambda key: (
                ResolvedSetting("USD", SettingSource.ENV_FILE, True)
                if key == "DEFAULT_CURRENCY"
                else original_resolve(key)
            ),
        )
    elif source is SettingSource.ENV:
        monkeypatch.setenv("DEFAULT_CURRENCY", "USD")
    elif source is SettingSource.DOTENV:
        env_path = tmp_path / "settings.env"
        env_path.write_text("DEFAULT_CURRENCY=USD\n")
        monkeypatch.setenv("ENV_FILE", str(env_path))
    else:
        ini_path = tmp_path / "settings.ini"
        ini_path.write_text("[timetracker]\nDEFAULT_CURRENCY = USD\n")
        monkeypatch.setenv("INI_FILE", str(ini_path))
    config_module.reset_caches()
    settings_resolver.clear_cache()

    html = superuser_client.get(reverse("games:admin_settings")).content.decode()

    currency = _opening_control_tag(html, "default_currency")
    assert 'value="USD"' in currency
    assert _is_disabled(currency)
    source_markup = _field_source_markup(
        html,
        "DEFAULT_CURRENCY",
        "default_currency",
    )
    assert f'data-setting-origin="{source}"' in source_markup
    assert 'data-setting-locked=""' in source_markup
    source_label = {
        SettingSource.ENV_FILE: "Environment file",
        SettingSource.ENV: "Environment",
        SettingSource.DOTENV: ".env",
        SettingSource.INI: "settings.ini",
    }[source]
    assert f"Managed by {source_label}; it cannot be changed here." in html


def test_navbar_keeps_personal_settings_for_normal_user_without_admin_link(
    normal_client,
):
    html = normal_client.get(reverse("games:list_sessions")).content.decode()
    actions = _navbar_account_actions(html)

    assert set(actions) == {"settings", "logout"}
    assert actions["settings"]["in_menu"] is True
    assert actions["logout"]["in_menu"] is True
    assert actions["logout"]["method"] == "post"
    assert actions["logout"]["role"] == "presentation"
    assert actions["logout"]["csrf"] is True
    assert actions["logout"]["button"] == {
        "type": "submit",
        "role": "menuitem",
        "tabindex": "-1",
        "class": (
            "block w-full text-left px-4 py-2 cursor-pointer no-underline "
            "rounded-base hover:bg-neutral-tertiary-medium text-body "
            "hover:text-heading focus:bg-neutral-tertiary-medium "
            "dark:focus:text-white focus:outline-hidden "
            "aria-disabled:opacity-50 aria-disabled:cursor-not-allowed"
        ),
    }


def test_navbar_menu_shows_all_account_actions_to_superuser(
    superuser_client,
):
    html = superuser_client.get(reverse("games:list_sessions")).content.decode()
    actions = _navbar_account_actions(html)

    assert set(actions) == {"settings", "admin_settings", "logout"}
    assert all(action["in_menu"] is True for action in actions.values())


def test_anonymous_navbar_omits_all_account_actions(db):
    html = Client().get(reverse("login")).content.decode()

    assert _navbar_account_actions(html) == {}
