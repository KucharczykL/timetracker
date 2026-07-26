"""Settings controls derived from the registry.

Both settings pages render the same eight user-scoped settings; they differ only
in how an inherited value is named and in how each value is resolved. The field
set, its widgets, and its labels come from ``SETTINGS_REGISTRY``, so a new
user-scoped setting needs no edit here.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Final

from django import forms

from common.components import SettingFieldState
from games.forms import apply_primitive_widget_classes
from timetracker.config import SettingSource
from timetracker.settings_registry import (
    SETTINGS_REGISTRY,
    SettingDefinition,
    SettingKey,
    SettingScope,
    SettingWidget,
)
from timetracker.settings_resolver import (
    ResolvedSetting,
    resolve_for_user_with_origin,
    resolve_with_origin,
)

# DEFAULT_DEVICE is the only MODEL setting; this is the label its unset state
# reads as in "Use site default (…)".
_EMPTY_MODEL_LABEL: Final = "No device"


@dataclass(frozen=True, slots=True)
class TextFieldOverride:
    """Per-setting extras for a TEXT control.

    Currency is masked to three uppercase letters; a plain text setting must not
    inherit that, so the specifics live here rather than in the TEXT branch.
    """

    max_length: int | None = None
    widget_attrs: Mapping[str, str] = field(default_factory=dict)


_TEXT_FIELD_OVERRIDES: Final[dict[SettingKey, TextFieldOverride]] = {
    "DEFAULT_CURRENCY": TextFieldOverride(
        max_length=3,
        widget_attrs={"x-mask": "aaa", "x-data": "", "class": "uppercase"},
    ),
}


def user_setting_definitions() -> list[SettingDefinition]:
    """The user-scoped definitions, in registry order."""
    return [
        definition
        for definition in SETTINGS_REGISTRY.values()
        if definition.scope is SettingScope.USER
    ]


def field_name_for(definition: SettingDefinition) -> str:
    """The Django form field name for a registry key."""
    return definition.key.lower()


def _model_label(definition: SettingDefinition, value: object) -> str:
    # bool is an int subclass; a stray True must not look up pk=1.
    if isinstance(value, int) and not isinstance(value, bool):
        queryset_factory = definition.model_queryset
        if queryset_factory is not None:
            instance = queryset_factory().filter(pk=value).first()
            if instance is not None:
                return str(instance)
    return _EMPTY_MODEL_LABEL


def display_label(definition: SettingDefinition, value: object) -> str:
    """The human label for a resolved value, as used in "Use site default (…)"."""
    if definition.widget is SettingWidget.MODEL:
        return _model_label(definition, value)
    if definition.widget is SettingWidget.SELECT:
        choices = definition.choices or ()
        for choice_value, label in choices:
            if choice_value == value:
                return label
        # Only an unset value means "the first option"; anything else prints
        # itself, so an out-of-choices timezone is not relabeled as another zone.
        if value is None and choices:
            return choices[0][1]
    return str(value)


class RegistrySettingsForm(forms.Form):
    """Controls for every user-scoped setting, built from the registry.

    Fields are built after ``super().__init__()`` and assigned to ``self.fields``:
    ``base_fields`` is a ClassVar in django-stubs, so a per-instance assignment
    fails mypy. That also puts the fields outside ``PrimitiveWidgetsMixin``'s
    reach, hence the direct stamping call. Merging ``self.fields`` last keeps a
    field a subclass declares the ordinary way.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.fields = {**self._build_fields(), **self.fields}
        apply_primitive_widget_classes(self.fields)

    def empty_label(self, definition: SettingDefinition) -> str:
        """Text of the option/placeholder meaning "inherit"."""
        raise NotImplementedError

    @classmethod
    def resolve(cls, definition: SettingDefinition, user: object) -> ResolvedSetting:
        """Resolve one setting the way this page reads it."""
        raise NotImplementedError

    @classmethod
    def keeps_initial(cls, resolved: ResolvedSetting) -> bool:
        """Whether a resolved value is prefilled into the control."""
        raise NotImplementedError

    @classmethod
    def field_state(
        cls,
        definition: SettingDefinition,
        resolved: ResolvedSetting,
        *,
        live_save: bool,
    ) -> SettingFieldState:
        """Per-field settings metadata for this page."""
        raise NotImplementedError

    def _build_fields(self) -> dict[str, forms.Field]:
        fields: dict[str, forms.Field] = {}
        for definition in user_setting_definitions():
            built = self._build_field(definition)
            built.label = definition.label
            fields[field_name_for(definition)] = built
        return fields

    def _build_field(self, definition: SettingDefinition) -> forms.Field:
        empty_label = self.empty_label(definition)
        if definition.widget is SettingWidget.MODEL:
            queryset_factory = definition.model_queryset
            if queryset_factory is None:
                raise ValueError(f"{definition.key}: MODEL widget without a queryset.")
            return forms.ModelChoiceField(
                queryset=queryset_factory(),
                required=False,
                empty_label=empty_label,
            )
        if definition.widget is SettingWidget.SELECT:
            choices = (("", empty_label), *(definition.choices or ()))
            if definition.cast is not None:
                return forms.TypedChoiceField(
                    required=False,
                    choices=choices,
                    coerce=definition.cast,
                    empty_value=None,
                )
            return forms.ChoiceField(required=False, choices=choices)
        override = _TEXT_FIELD_OVERRIDES.get(definition.key, TextFieldOverride())
        return forms.CharField(
            required=False,
            max_length=override.max_length,
            widget=forms.TextInput(
                attrs={**override.widget_attrs, "placeholder": empty_label}
            ),
        )


class SiteSettingsForm(RegistrySettingsForm):
    """Site defaults. Every control shows the resolved value, so the empty option
    names the configured fallback rather than a value."""

    def empty_label(self, definition: SettingDefinition) -> str:
        return "Use configured default"

    @classmethod
    def resolve(cls, definition: SettingDefinition, user: object) -> ResolvedSetting:
        return resolve_with_origin(definition.key)

    @classmethod
    def keeps_initial(cls, resolved: ResolvedSetting) -> bool:
        return True

    @classmethod
    def field_state(
        cls,
        definition: SettingDefinition,
        resolved: ResolvedSetting,
        *,
        live_save: bool,
    ) -> SettingFieldState:
        return SettingFieldState(
            definition.key,
            str(resolved.source),
            locked=resolved.locked,
            help_text=definition.help_text,
            live_save=live_save,
        )


class UserSettingsForm(RegistrySettingsForm):
    """Personal preferences. An empty control inherits, and says which site value
    it inherits."""

    def empty_label(self, definition: SettingDefinition) -> str:
        site_value = resolve_with_origin(definition.key).value
        return f"Use site default ({display_label(definition, site_value)})"

    @classmethod
    def resolve(cls, definition: SettingDefinition, user: object) -> ResolvedSetting:
        return resolve_for_user_with_origin(user, definition.key)

    @classmethod
    def keeps_initial(cls, resolved: ResolvedSetting) -> bool:
        return resolved.source is SettingSource.USER

    @classmethod
    def field_state(
        cls,
        definition: SettingDefinition,
        resolved: ResolvedSetting,
        *,
        live_save: bool,
    ) -> SettingFieldState:
        return SettingFieldState(
            definition.key,
            str(resolved.source),
            help_text=definition.user_help_text or definition.help_text,
            live_save=live_save,
            # Each control already names the site value it inherits, so an origin
            # badge here would only repeat it.
            show_source=False,
        )
