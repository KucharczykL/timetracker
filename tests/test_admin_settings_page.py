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

    assert f'href="{reverse("games:settings")}"' in html
    assert ">Settings</a>" in html
    assert f'href="{reverse("games:admin_settings")}"' not in html
    assert ">Admin settings</a>" not in html


def test_navbar_shows_adjacent_distinct_admin_link_only_to_superuser(
    superuser_client,
):
    html = superuser_client.get(reverse("games:list_sessions")).content.decode()

    settings_link = f'href="{reverse("games:settings")}"'
    admin_link = f'href="{reverse("games:admin_settings")}"'
    settings_index = html.index(settings_link)
    admin_index = html.index(admin_link)
    logout_index = html.index('action="/logout/"')
    assert settings_index < admin_index < logout_index
    assert ">Settings</a>" in html
    assert ">Admin settings</a>" in html


def test_anonymous_navbar_omits_both_settings_links(db):
    html = Client().get(reverse("login")).content.decode()

    assert f'href="{reverse("games:settings")}"' not in html
    assert f'href="{reverse("games:admin_settings")}"' not in html
