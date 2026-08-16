import dataclasses

import pytest
from django import forms
from django.test import Client
from django.urls import reverse

from common.components import FormFieldPresentation, Span
from games.forms import INPUT_CLASS, SELECT_CLASS, apply_primitive_widget_classes
from games.models import Platform, SiteSetting
from games.settings_forms import (
    SiteSettingsForm,
    UserSettingsForm,
    display_label,
    settings_page_data,
    user_setting_definitions,
)
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
from timetracker.settings_resolver import clear_cache


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
    currency = fields["default_purchase_currency"]
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
    # A value that differs from DEFAULT_PURCHASE_CURRENCY's built-in default, so the
    # assertion below can only pass by reading the DATABASE layer through
    # resolve_with_origin — not by taking a shortcut to settings.DEFAULT_PURCHASE_CURRENCY.
    SiteSetting.objects.create(key="DEFAULT_PURCHASE_CURRENCY", value="EUR")
    settings_resolver.clear_cache()

    fields = UserSettingsForm().fields

    assert fields["default_landing_page"].choices[0] == (
        "",
        "Use site default (Sessions)",
    )
    assert fields["default_page_size"].choices[0] == ("", "Use site default (25)")
    assert fields["default_purchase_currency"].widget.attrs["placeholder"] == (
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
def test_display_label_names_the_unset_landing_page_regardless_of_choice_order():
    landing_page = get_definition("DEFAULT_LANDING_PAGE")
    choices = landing_page.choices
    assert choices is not None
    reordered = dataclasses.replace(landing_page, choices=tuple(reversed(choices)))

    # The reordered first choice is no longer "Sessions", so a pass here can
    # only be explained by empty_display, not choices[0].
    reordered_choices = reordered.choices
    assert reordered_choices is not None
    assert reordered_choices[0][1] != "Sessions"
    assert display_label(reordered, None) == "Sessions"


@pytest.fixture
def synthetic_model_setting(monkeypatch):
    """A MODEL-widget setting with an empty_display distinct from every real
    MODEL setting's, so a hardcoded "No device" cannot pass for it by luck."""
    definition = SettingDefinition(
        "SYNTHETIC_MODEL",
        scope=SettingScope.USER,
        apply_timing=ApplyTiming.LIVE,
        label="Synthetic model",
        default_factory=lambda: None,
        widget=SettingWidget.MODEL,
        model_queryset=lambda: Platform.objects.order_by("name"),
        empty_display="No synthetic platform",
    )
    monkeypatch.setitem(SETTINGS_REGISTRY, definition.key, definition)
    clear_cache()
    yield definition
    clear_cache()


@pytest.mark.django_db
def test_display_label_reads_the_empty_display_from_the_definition(
    synthetic_model_setting,
):
    assert display_label(synthetic_model_setting, None) == "No synthetic platform"


@pytest.mark.django_db
def test_the_personal_page_names_the_synthetic_model_empty_display(
    synthetic_model_setting,
):
    field = UserSettingsForm().fields["synthetic_model"]

    assert field.empty_label == "Use site default (No synthetic platform)"
    assert "No device" not in field.empty_label


_SYNTHETIC_CHOICES = (("alpha", "Alpha"), ("beta", "Beta"))


@pytest.fixture
def synthetic_setting(monkeypatch):
    """A ninth user-scoped setting added to the registry and nowhere else."""
    definition = SettingDefinition(
        "SYNTHETIC_NINTH",
        scope=SettingScope.USER,
        apply_timing=ApplyTiming.LIVE,
        label="Synthetic ninth",
        help_text="Added by a test.",
        default_factory=lambda: "alpha",
        widget=SettingWidget.SELECT,
        choices=_SYNTHETIC_CHOICES,
    )
    monkeypatch.setitem(SETTINGS_REGISTRY, definition.key, definition)
    clear_cache()
    yield definition
    clear_cache()


@pytest.mark.django_db
def test_a_new_registry_entry_reaches_both_forms_with_no_form_edit(synthetic_setting):
    user_field = UserSettingsForm().fields["synthetic_ninth"]
    site_field = SiteSettingsForm().fields["synthetic_ninth"]

    assert isinstance(user_field, forms.ChoiceField)
    assert user_field.label == "Synthetic ninth"
    assert list(user_field.choices) == [
        ("", "Use site default (Alpha)"),
        *_SYNTHETIC_CHOICES,
    ]
    assert list(site_field.choices) == [
        ("", "Use configured default"),
        *_SYNTHETIC_CHOICES,
    ]


@pytest.mark.django_db
def test_a_new_registry_entry_reaches_both_state_builders(synthetic_setting):
    user_page = settings_page_data(UserSettingsForm, user=None)
    site_page = settings_page_data(SiteSettingsForm)

    assert user_page.states["synthetic_ninth"].key == "SYNTHETIC_NINTH"
    assert user_page.states["synthetic_ninth"].source == "default"
    assert user_page.states["synthetic_ninth"].show_source is False
    assert site_page.states["synthetic_ninth"].help_text == "Added by a test."
    assert site_page.form.initial["synthetic_ninth"] == "alpha"


@pytest.mark.django_db
def test_a_new_registry_entry_renders_on_both_real_settings_pages(
    django_user_model, synthetic_setting
):
    """Reaching both forms and both state builders in isolation does not prove
    the full page survives prepare_setting_fields and the PATCH-URL/namespace
    wiring; only a real request through each view does."""
    normal_user = django_user_model.objects.create_user(
        username="settings-form-user", password="pw"
    )
    superuser = django_user_model.objects.create_superuser(
        username="settings-form-admin", password="pw"
    )

    personal_client = Client()
    personal_client.force_login(normal_user)
    personal_response = personal_client.get(reverse("games:settings"))
    assert personal_response.status_code == 200
    assert (
        f'data-setting-key="{synthetic_setting.key}"'
        in personal_response.content.decode()
    )

    admin_client = Client()
    admin_client.force_login(superuser)
    admin_response = admin_client.get(reverse("games:admin_settings"))
    assert admin_response.status_code == 200
    assert (
        f'data-setting-key="{synthetic_setting.key}"' in admin_response.content.decode()
    )


@pytest.mark.django_db
def test_the_personal_page_prefills_only_its_own_overrides(django_user_model):
    user = django_user_model.objects.create_user(username="tester", password="pw")
    page = settings_page_data(UserSettingsForm, user=user)

    assert page.form.initial == {}
    assert page.states["default_page_size"].source == "default"


@pytest.mark.django_db
def test_a_control_decorator_takes_over_saving_and_its_reload_stamp():
    page = settings_page_data(
        UserSettingsForm,
        user=None,
        presentations={
            "theme": FormFieldPresentation(decorate_control=lambda node: node)
        },
    )

    assert page.states["theme"].live_save is False
    assert "data-reload-after-save" not in page.form.fields["theme"].widget.attrs
    assert "data-reload-after-save" in page.form.fields["datetime_format"].widget.attrs


@pytest.mark.django_db
def test_a_cosmetic_presentation_keeps_the_field_live_saving():
    page = settings_page_data(
        UserSettingsForm,
        user=None,
        presentations={"theme": FormFieldPresentation(after_control=Span()["hint"])},
    )

    assert page.states["theme"].live_save is True
    assert "data-reload-after-save" in page.form.fields["theme"].widget.attrs


@pytest.mark.django_db
def test_the_site_page_stamps_every_display_setting_for_reload():
    page = settings_page_data(SiteSettingsForm)

    for field_name in (
        "theme",
        "display_time_zone",
        "date_format_locale",
        "datetime_format",
    ):
        assert "data-reload-after-save" in page.form.fields[field_name].widget.attrs
    for field_name in (
        "default_purchase_currency",
        "default_display_currency",
        "default_page_size",
    ):
        assert "data-reload-after-save" not in page.form.fields[field_name].widget.attrs


@pytest.mark.django_db
def test_every_user_scoped_field_label_matches_its_definition_on_both_forms():
    """Django's auto-generated label from a field name coincidentally matches
    a definition's label for some settings (e.g. "default_purchase_currency" ->
    "Default currency") but not others (e.g. "default_page_size" ->
    "Default page size" vs. the registry's "Default rows per page"), so this
    must compare every field against its definition, not spot-check a few."""
    user_fields = UserSettingsForm().fields
    site_fields = SiteSettingsForm().fields

    for definition in user_setting_definitions():
        field_name = definition.key.lower()
        assert user_fields[field_name].label == definition.label, field_name
        assert site_fields[field_name].label == definition.label, field_name
