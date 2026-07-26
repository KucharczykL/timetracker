import pytest
from django import forms

from games.forms import INPUT_CLASS, SELECT_CLASS, apply_primitive_widget_classes
from games.models import Device, SiteSetting
from games.settings_forms import SiteSettingsForm, UserSettingsForm, display_label
from timetracker import settings_resolver
from timetracker.settings_registry import (
    LANDING_PAGE_CHOICES,
    PAGE_SIZE_OPTIONS,
    SETTINGS_REGISTRY,
    ApplyTiming,
    SettingDefinition,
    SettingScope,
    SettingWidget,
    get_definition,
)


def test_stamping_applies_the_shared_control_classes_by_widget_type():
    fields: dict[str, forms.Field] = {
        "choice": forms.ChoiceField(choices=(("a", "A"),)),
        "text": forms.CharField(),
    }

    apply_primitive_widget_classes(fields)

    assert fields["choice"].widget.attrs["class"] == SELECT_CLASS
    assert fields["text"].widget.attrs["class"] == INPUT_CLASS


def _user_field_names() -> list[str]:
    return [
        key.lower()
        for key, definition in SETTINGS_REGISTRY.items()
        if definition.scope is SettingScope.USER
    ]


@pytest.mark.django_db
def test_both_forms_expose_every_user_scoped_key_in_registry_order():
    assert list(UserSettingsForm().fields) == _user_field_names()
    assert list(SiteSettingsForm().fields) == _user_field_names()


@pytest.mark.django_db
def test_field_classes_match_pairwise_across_the_two_pages():
    site_fields = SiteSettingsForm().fields
    for field_name, field in UserSettingsForm().fields.items():
        assert type(field) is type(site_fields[field_name]), field_name


@pytest.mark.django_db
def test_page_size_is_typed_on_both_pages():
    assert isinstance(
        UserSettingsForm().fields["default_page_size"], forms.TypedChoiceField
    )
    assert isinstance(
        SiteSettingsForm().fields["default_page_size"], forms.TypedChoiceField
    )


@pytest.mark.django_db
def test_currency_keeps_its_mask_and_length_while_a_plain_text_setting_would_not(
    monkeypatch,
):
    synthetic_key = "SYNTHETIC_PLAIN_TEXT"
    monkeypatch.setitem(
        SETTINGS_REGISTRY,
        synthetic_key,
        SettingDefinition(
            synthetic_key,
            scope=SettingScope.USER,
            apply_timing=ApplyTiming.LIVE,
            label="Synthetic",
            default_factory=lambda: "unset",
            widget=SettingWidget.TEXT,
        ),
    )
    settings_resolver.clear_cache()

    fields = UserSettingsForm().fields
    currency = fields["default_currency"]
    plain_text = fields[synthetic_key.lower()]

    assert currency.max_length == 3
    assert currency.widget.attrs["x-mask"] == "aaa"
    assert "uppercase" in currency.widget.attrs["class"]

    assert plain_text.max_length is None
    assert "x-mask" not in plain_text.widget.attrs


@pytest.mark.django_db
def test_the_site_page_uses_the_static_empty_label():
    fields = SiteSettingsForm().fields

    assert list(fields["default_landing_page"].choices) == [
        ("", "Use configured default"),
        *LANDING_PAGE_CHOICES,
    ]
    assert list(fields["default_page_size"].choices) == [
        ("", "Use configured default"),
        *PAGE_SIZE_OPTIONS,
    ]


@pytest.mark.django_db
def test_the_user_page_names_the_inherited_site_value():
    # A value that differs from DEFAULT_CURRENCY's built-in default, so the
    # assertion below can only pass by reading the DATABASE layer through
    # resolve_with_origin — not by taking a shortcut to settings.DEFAULT_CURRENCY.
    SiteSetting.objects.create(key="DEFAULT_CURRENCY", value="EUR")
    settings_resolver.clear_cache()

    fields = UserSettingsForm().fields

    assert fields["default_landing_page"].choices[0] == (
        "",
        "Use site default (Sessions)",
    )
    assert fields["default_page_size"].choices[0] == ("", "Use site default (25)")
    assert fields["default_device"].empty_label == "Use site default (No device)"
    assert fields["default_currency"].widget.attrs["placeholder"] == (
        "Use site default (EUR)"
    )


@pytest.mark.django_db
def test_display_label_falls_back_to_the_first_choice_only_for_none():
    landing_page = get_definition("DEFAULT_LANDING_PAGE")
    assert display_label(landing_page, None) == "Sessions"
    assert display_label(landing_page, "games:list_games") == "Games"

    # A timezone outside the frozen choices tuple must print itself, not the
    # alphabetically first zone.
    time_zone = get_definition("DISPLAY_TIME_ZONE")
    assert display_label(time_zone, "Europe/Prague") == "Europe/Prague"
    assert display_label(time_zone, "Factory/Unknown") == "Factory/Unknown"


@pytest.mark.django_db
def test_display_label_names_the_device_or_reports_none():
    device = Device.objects.create(name="Desktop", type="pc")
    definition = get_definition("DEFAULT_DEVICE")

    assert display_label(definition, device.pk) == str(device)
    assert display_label(definition, None) == "No device"
    assert display_label(definition, device.pk + 1000) == "No device"
