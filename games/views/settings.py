"""Authenticated personal settings page shared with later settings stages."""

from typing import cast

from django import forms
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.middleware.csrf import get_token
from django.urls import reverse

from common.components import (
    ContentContainer,
    Div,
    FormFieldPresentation,
    LiveSettingFields,
    PageHeading,
    SettingFieldState,
    SettingsScaffold,
    SettingsSection,
    ThemeSetting,
)
from common.layout import render_page
from games.forms import PrimitiveWidgetsMixin
from games.models import Device
from timetracker.config import SettingSource
from timetracker.settings_registry import (
    DATETIME_FORMAT_CHOICES,
    DISPLAY_TIME_ZONE_CHOICES,
    FORMAT_LOCALE_CHOICES,
    LANDING_PAGE_CHOICES,
    PAGE_SIZE_CHOICES,
    THEME_CHOICES,
    get_definition,
)
from timetracker.settings_resolver import (
    resolve_for_user_with_origin,
    resolve_with_origin,
)

_FIELD_KEYS = {
    "default_currency": "DEFAULT_CURRENCY",
    "default_device": "DEFAULT_DEVICE",
    "default_landing_page": "DEFAULT_LANDING_PAGE",
    "default_page_size": "DEFAULT_PAGE_SIZE",
    "theme": "THEME",
    "display_time_zone": "DISPLAY_TIME_ZONE",
    "date_format_locale": "DATE_FORMAT_LOCALE",
    "datetime_format": "DATETIME_FORMAT",
}


class UserSettingsForm(PrimitiveWidgetsMixin, forms.Form):
    """Typed controls for the initial personal-preference slice."""

    default_currency = forms.CharField(
        required=False,
        max_length=3,
        widget=forms.TextInput(
            attrs={"x-mask": "aaa", "x-data": "", "class": "uppercase"}
        ),
    )
    default_device = forms.ModelChoiceField(
        queryset=Device.objects.none(),
        required=False,
        empty_label="Use site default",
    )
    default_landing_page = forms.ChoiceField(
        required=False,
        choices=(("", "Use site default"), *LANDING_PAGE_CHOICES),
    )
    default_page_size = forms.ChoiceField(
        required=False,
        choices=(
            ("", "Use site default"),
            *((size, str(size)) for size in PAGE_SIZE_CHOICES),
        ),
    )
    theme = forms.ChoiceField(required=False, choices=THEME_CHOICES)
    display_time_zone = forms.ChoiceField(required=False, choices=())
    date_format_locale = forms.ChoiceField(required=False, choices=())
    datetime_format = forms.ChoiceField(required=False, choices=())

    def __init__(
        self,
        *args,
        default_device_label: str = "No device",
        default_landing_page_label: str = "Sessions",
        default_page_size_label: str = "25",
        default_theme_label: str = "System",
        default_display_time_zone_label: str = "UTC",
        default_date_format_locale_label: str = "English (United States)",
        default_datetime_format_label: str = "ISO 8601",
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        device_field = cast(forms.ModelChoiceField, self.fields["default_device"])
        device_field.queryset = Device.objects.order_by("name")
        device_field.empty_label = f"Use site default ({default_device_label})"
        landing_page_field = cast(
            forms.ChoiceField, self.fields["default_landing_page"]
        )
        landing_page_field.choices = (
            ("", f"Use site default ({default_landing_page_label})"),
            *LANDING_PAGE_CHOICES,
        )
        page_size_field = cast(forms.ChoiceField, self.fields["default_page_size"])
        page_size_field.choices = (
            ("", f"Use site default ({default_page_size_label})"),
            *((size, str(size)) for size in PAGE_SIZE_CHOICES),
        )
        theme_field = cast(forms.ChoiceField, self.fields["theme"])
        theme_field.choices = (
            ("", f"Use site default ({default_theme_label})"),
            *THEME_CHOICES,
        )
        time_zone_field = cast(forms.ChoiceField, self.fields["display_time_zone"])
        time_zone_field.choices = (
            ("", f"Use site default ({default_display_time_zone_label})"),
            *DISPLAY_TIME_ZONE_CHOICES,
        )
        locale_field = cast(forms.ChoiceField, self.fields["date_format_locale"])
        locale_field.choices = (
            ("", f"Use site default ({default_date_format_locale_label})"),
            *FORMAT_LOCALE_CHOICES,
        )
        datetime_format_field = cast(forms.ChoiceField, self.fields["datetime_format"])
        datetime_format_field.choices = (
            ("", f"Use site default ({default_datetime_format_label})"),
            *DATETIME_FORMAT_CHOICES,
        )
        for field_name, key in _FIELD_KEYS.items():
            self.fields[field_name].label = get_definition(key).label
        for field_name in (
            "display_time_zone",
            "date_format_locale",
            "datetime_format",
        ):
            self.fields[field_name].widget.attrs["data-reload-after-save"] = ""


def _device_label(value: object) -> str:
    if isinstance(value, int) and not isinstance(value, bool):
        device = Device.objects.filter(pk=value).first()
        if device is not None:
            return str(device)
    return "No device"


def _landing_page_label(value: object) -> str:
    labels = dict(LANDING_PAGE_CHOICES)
    return labels.get(value, "Sessions") if isinstance(value, str) else "Sessions"


def _format_locale_label(value: object) -> str:
    labels = dict(FORMAT_LOCALE_CHOICES)
    return (
        labels.get(value, "English (United States)")
        if isinstance(value, str)
        else "English (United States)"
    )


def _datetime_format_label(value: object) -> str:
    labels = dict(DATETIME_FORMAT_CHOICES)
    return labels.get(value, "ISO 8601") if isinstance(value, str) else "ISO 8601"


def _form_and_states(
    user: object,
) -> tuple[UserSettingsForm, dict[str, SettingFieldState]]:
    initial: dict[str, object] = {}
    states: dict[str, SettingFieldState] = {}
    for field_name, key in _FIELD_KEYS.items():
        definition = get_definition(key)
        resolved = resolve_for_user_with_origin(user, key)
        if field_name == "default_currency" or resolved.source is SettingSource.USER:
            initial[field_name] = resolved.value
        states[field_name] = SettingFieldState(
            key,
            str(resolved.source),
            help_text=definition.help_text,
            live_save=field_name != "theme",
        )
    site_device = resolve_with_origin("DEFAULT_DEVICE").value
    site_landing_page = resolve_with_origin("DEFAULT_LANDING_PAGE").value
    site_page_size = resolve_with_origin("DEFAULT_PAGE_SIZE").value
    site_theme = resolve_with_origin("THEME").value
    site_display_time_zone = resolve_with_origin("DISPLAY_TIME_ZONE").value
    site_date_format_locale = resolve_with_origin("DATE_FORMAT_LOCALE").value
    site_datetime_format = resolve_with_origin("DATETIME_FORMAT").value
    return (
        UserSettingsForm(
            initial=initial,
            default_device_label=_device_label(site_device),
            default_landing_page_label=_landing_page_label(site_landing_page),
            default_page_size_label=str(site_page_size),
            default_theme_label=dict(THEME_CHOICES).get(str(site_theme), "System"),
            default_display_time_zone_label=str(site_display_time_zone),
            default_date_format_locale_label=_format_locale_label(
                site_date_format_locale
            ),
            default_datetime_format_label=_datetime_format_label(site_datetime_format),
        ),
        states,
    )


@login_required
def user_settings(request: HttpRequest) -> HttpResponse:
    form, states = _form_and_states(request.user)
    patch_url = reverse(
        "api-1.0.0:update_user_setting",
        kwargs={"key": "__key__"},
    )
    sections = [
        SettingsSection(
            "preferences",
            "Preferences",
            LiveSettingFields(
                form,
                states=states,
                patch_url_template=patch_url,
                csrf=get_token(request),
                presentations={
                    "theme": FormFieldPresentation(decorate_control=ThemeSetting)
                },
            ),
            "Defaults used when creating records and opening Timetracker.",
        )
    ]
    content = Div(class_="flex flex-col")[
        ContentContainer(class_="mb-6")[PageHeading(["Settings"])],
        SettingsScaffold(sections),
    ]
    return render_page(request, content, title="Settings")


__all__ = ["UserSettingsForm", "user_settings"]
