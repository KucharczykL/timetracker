"""Authenticated personal settings page shared with later settings stages."""

from django import forms
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.middleware.csrf import get_token
from django.urls import reverse

from common.components import (
    ContentContainer,
    Div,
    LiveSettingFields,
    PageHeading,
    SettingFieldState,
    SettingsScaffold,
    SettingsSection,
)
from common.layout import render_page
from games.forms import PrimitiveWidgetsMixin
from games.models import Device
from timetracker.settings_registry import LANDING_PAGE_CHOICES, get_definition
from timetracker.settings_resolver import resolve_for_user_with_origin

_FIELD_KEYS = {
    "default_currency": "DEFAULT_CURRENCY",
    "default_device": "DEFAULT_DEVICE",
    "default_landing_page": "DEFAULT_LANDING_PAGE",
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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["default_device"].queryset = Device.objects.order_by("name")
        for field_name, key in _FIELD_KEYS.items():
            self.fields[field_name].label = get_definition(key).label


def _form_and_states(
    user: object,
) -> tuple[UserSettingsForm, dict[str, SettingFieldState]]:
    initial: dict[str, object] = {}
    states: dict[str, SettingFieldState] = {}
    for field_name, key in _FIELD_KEYS.items():
        definition = get_definition(key)
        resolved = resolve_for_user_with_origin(user, key)
        initial[field_name] = resolved.value
        states[field_name] = SettingFieldState(
            key,
            str(resolved.source),
            help_text=definition.help_text,
        )
    return UserSettingsForm(initial=initial), states


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
