"""Isolated server-rendered contracts for the Stage 3 settings UI kit."""

import pytest
from django import forms
from django.test import SimpleTestCase
from django.utils.html import escape

from common.components import (
    Badge,
    Div,
    FormFieldGroup,
    FormFields,
    LiveSettingFields,
    MaskedSecretField,
    SettingFieldState,
    SettingSourceBadge,
    SettingsScaffold,
    SettingsSection,
    collect_media,
)
from games.forms import PrimitiveCheckboxWidget, PrimitiveWidgetsMixin


class KitForm(PrimitiveWidgetsMixin, forms.Form):
    enabled = forms.BooleanField(required=False, label="Enabled")
    destination = forms.ChoiceField(
        choices=[("library", "Library"), ("stats", "Statistics")]
    )
    limit = forms.IntegerField(required=False, min_value=1)
    display_name = forms.CharField(required=False)
    locked_value = forms.CharField(required=False)
    hidden_token = forms.CharField(widget=forms.HiddenInput(), initial="opaque")


class GroupedFormFieldsTest(SimpleTestCase):
    groups = [
        FormFieldGroup(
            "Behavior",
            ("enabled", "destination"),
            "Choose how the application behaves.",
            "behavior-fields",
        ),
        FormFieldGroup("Limits", ("limit",)),
    ]

    def test_groups_extend_the_existing_renderer(self):
        html = str(FormFields(KitForm(), groups=self.groups))
        assert html.count("<fieldset") == 2
        assert (
            '<legend class="text-type-section text-heading">Behavior</legend>' in html
        )
        assert 'id="behavior-fields"' in html
        assert 'aria-describedby="behavior-fields-description"' in html
        assert "Choose how the application behaves." in html
        # Omitted visible fields remain rendered after the explicit fieldsets.
        assert html.index("Limits") < html.index("Display name")
        # Hidden fields stay outside groups and appear exactly once.
        assert html.count('name="hidden_token"') == 1

    def test_grouped_fields_keep_errors_and_checkbox_rows(self):
        form = KitForm({"destination": "library", "limit": "bad"})
        assert not form.is_valid()
        html = str(FormFields(form, groups=self.groups))
        assert "Enter a whole number" in html
        assert "flex flex-row justify-between" in html
        assert isinstance(form.fields["enabled"].widget, PrimitiveCheckboxWidget)

    def test_unknown_or_duplicate_group_names_fail_loudly(self):
        with pytest.raises(ValueError, match="unknown field"):
            str(FormFields(KitForm(), groups=[FormFieldGroup("Bad", ("nope",))]))
        with pytest.raises(ValueError, match="multiple groups"):
            str(
                FormFields(
                    KitForm(),
                    groups=[
                        FormFieldGroup("One", ("limit",)),
                        FormFieldGroup("Two", ("limit",)),
                    ],
                )
            )

    def test_all_plain_setting_widget_types_use_the_mixin_path(self):
        form = KitForm()
        assert isinstance(form.fields["enabled"].widget, PrimitiveCheckboxWidget)
        assert "min-h-control" in form.fields["destination"].widget.attrs["class"]
        assert "min-h-control" in form.fields["limit"].widget.attrs["class"]
        assert "min-h-control" in form.fields["display_name"].widget.attrs["class"]

    def test_label_extras_render_beside_the_label_before_the_control(self):
        html = str(
            FormFields(
                KitForm(),
                label_extras={"display_name": Badge("Personal", size="sm")},
            )
        )
        label_line = html.index('data-form-field-label-line=""')
        badge = html.index(">Personal</span>", label_line)
        control = html.index('name="display_name"', badge)

        assert label_line < badge < control


class SettingsBadgeAndFieldStateTest(SimpleTestCase):
    def test_badge_tone_is_a_real_palette_parameter(self):
        assert "bg-brand-soft" in str(Badge("Default"))
        assert "bg-neutral-secondary-medium" in str(Badge("Database", tone="neutral"))
        assert "bg-warning-soft" in str(Badge("Locked", tone="warning"))

    def test_source_lock_composite_is_one_badge_with_an_icon(self):
        node = SettingSourceBadge(
            "env_file",
            locked=True,
            reason="Change SECRET__FILE and restart.",
            id="env-file-source-tip",
        )
        html = str(node)
        assert "Environment file" in html
        assert html.count('data-setting-origin="env_file"') == 1
        assert html.count("<svg") == 1
        assert 'data-setting-origin="env_file"' in html
        assert 'data-setting-locked=""' in html
        assert 'aria-label="Environment file source, locked"' in html
        assert 'id="env-file-source-tip"' in html
        assert 'role="tooltip"' in html
        assert (
            "Source: Loaded from a file referenced by an environment variable." in html
        )
        assert "Locked: Change SECRET__FILE and restart." in html
        assert "dist/elements/pop-over.js" in collect_media(node).js
        assert "data-pill" not in html

    def test_every_unlocked_source_badge_explains_its_origin(self):
        descriptions = {
            "user": "Saved for your account and overrides the site default.",
            "database": "Saved in the application database as the current site-wide value.",
            "env": "Loaded from an environment variable.",
            "env_file": "Loaded from a file referenced by an environment variable.",
            "dotenv": "Loaded from the application's .env file.",
            "ini": "Loaded from the application's settings.ini file.",
            "default": "The built-in default, used because no higher-priority value is set.",
        }
        for source, description in descriptions.items():
            html = str(SettingSourceBadge(source, id=f"{source}-source-tip"))
            assert 'role="tooltip"' in html
            assert str(escape(f"Source: {description}")) in html
            assert "Locked:" not in html

    def test_locked_state_disables_the_real_django_field_and_adds_reason(self):
        form = KitForm()
        states = {
            "locked_value": SettingFieldState(
                key="APP_URL",
                source="env",
                locked=True,
                reason="Change APP_URL in the environment and restart.",
            )
        }
        html = str(
            LiveSettingFields(
                form,
                states=states,
                patch_url_template="/api/settings/site/__key__",
                csrf="token",
            )
        )
        assert form.fields["locked_value"].disabled is True
        assert " disabled" in html
        assert "disabled:opacity-50" in html
        assert 'data-setting-key="APP_URL"' in html
        assert "Environment" in html
        assert 'data-setting-locked=""' in html
        assert "Change APP_URL in the environment and restart." in html
        assert 'aria-describedby="id_locked_value_setting_metadata"' in html
        assert 'id="id_locked_value_setting_source_tooltip"' in html
        assert 'role="tooltip"' in html
        assert "Source: Loaded from an environment variable." in html
        assert "Locked: Change APP_URL in the environment and restart." in html
        label_line = html.index('data-form-field-label-line=""')
        badge = html.index('data-setting-origin="env"', label_line)
        control = html.index('name="locked_value"', badge)
        reason = html.index("Change APP_URL", control)
        assert label_line < badge < control < reason


class SettingsScaffoldTest(SimpleTestCase):
    def _sections(self):
        return [
            SettingsSection("general", "General", Div()["General fields"]),
            SettingsSection("privacy", "Privacy", Div()["Privacy fields"]),
        ]

    def test_same_dom_carries_mobile_chips_and_desktop_rail_classes(self):
        scaffold = SettingsScaffold(self._sections())
        html = str(scaffold)
        assert html.count("<settings-section-nav") == 1
        assert html.count('data-section-nav-item=""') == 2
        assert 'href="#general"' in html and 'href="#privacy"' in html
        assert "@4xl:grid-cols-[12rem_minmax(0,1fr)]" in html
        assert "@4xl:sticky" in html
        assert html.count('data-settings-section=""') == 2
        assert "text-type-section" in html

        media = collect_media(scaffold)
        assert "dist/elements/settings-section-nav.js" in media.js
        assert "dist/elements/drop-down.js" in media.js

    def test_section_ids_are_valid_and_unique(self):
        with pytest.raises(ValueError, match="at least one"):
            SettingsScaffold([])
        with pytest.raises(ValueError, match="Invalid"):
            SettingsScaffold([SettingsSection("not valid", "Bad", Div())])
        with pytest.raises(ValueError, match="Duplicate"):
            SettingsScaffold(
                [
                    SettingsSection("same", "One", Div()),
                    SettingsSection("same", "Two", Div()),
                ]
            )


class LiveAndSecretComponentTest(SimpleTestCase):
    def test_live_wrapper_uses_registered_codegen_attributes_and_media(self):
        node = LiveSettingFields(
            KitForm(),
            states={
                "display_name": SettingFieldState(
                    key="DISPLAY_NAME", source="user", help_text="Shown to you."
                )
            },
            patch_url_template="/api/settings/user/__key__",
            csrf="csrf-token",
            groups=[FormFieldGroup("Profile", ("display_name",))],
        )
        html = str(node)
        assert html.startswith("<live-setting-fields")
        assert 'patch-url-template="/api/settings/user/__key__"' in html
        assert 'csrf="csrf-token"' in html
        assert 'event="setting-saved"' in html
        assert "dist/elements/live-setting-fields.js" in collect_media(node).js

    def test_live_wrapper_requires_a_key_placeholder(self):
        with pytest.raises(ValueError, match="__key__"):
            LiveSettingFields(
                KitForm(),
                states={},
                patch_url_template="/api/settings/user",
                csrf="token",
            )

    def test_masked_secret_never_accepts_or_renders_a_secret_value(self):
        html = str(MaskedSecretField(label="Secret key", present=True))
        assert 'type="password"' in html
        assert 'readonly="readonly"' in html
        assert 'aria-readonly="true"' in html
        assert "••••••••" in html
        assert "super-secret-value" not in html
        assert "min-h-control" in html

    def test_absent_secret_has_an_explicit_empty_state(self):
        html = str(MaskedSecretField(label="Secret key", present=False))
        assert 'value=""' in html
        assert 'placeholder="Not set"' in html
