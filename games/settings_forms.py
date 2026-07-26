"""Settings controls derived from the registry.

Both settings pages render the user-scoped settings; they differ only in how an
inherited value is named and in how each value is resolved. The field set, its
widgets, and its labels come from ``SETTINGS_REGISTRY``, so a new user-scoped
setting needs no edit here.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Final, NamedTuple

from django import forms

from common.components import FormFieldPresentation, SettingFieldState
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

type SettingFieldName = str  # e.g. "default_currency" -- the Django form field name


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
    """The user-scoped definitions, in registry order.

    Both the personal and the site page render this same set — the site page
    shows the values users inherit. A SITE-scoped setting is deliberately absent
    from both, not just this one; it has no per-user override to show.
    """
    return [
        definition
        for definition in SETTINGS_REGISTRY.values()
        if definition.scope is SettingScope.USER
    ]


def field_name_for(definition: SettingDefinition) -> SettingFieldName:
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
    return definition.empty_display


def display_label(definition: SettingDefinition, value: object) -> str:
    """The human label for a resolved value, as used in "Use site default (…)"."""
    if definition.widget is SettingWidget.MODEL:
        return _model_label(definition, value)
    if definition.widget is SettingWidget.SELECT:
        choices = definition.choices or ()
        for choice_value, label in choices:
            if choice_value == value:
                return label
        # An unset value's real destination can be decided by code well away
        # from this list (e.g. the landing page's fallback lives in the index
        # view, not in choice order), so an explicit empty_display names it
        # when the definition has one. Falling back to the first choice is
        # only a default for a SELECT setting that declares no empty_display.
        # Anything else prints itself, so an out-of-choices timezone is not
        # relabeled as another zone.
        if value is None:
            if definition.empty_display:
                return definition.empty_display
            if choices:
                return choices[0][1]
        return str(value)
    if definition.widget is SettingWidget.TEXT:
        return str(value)
    raise ValueError(
        f"{definition.key}: display_label has no case for widget {definition.widget!r}."
    )


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
        raise NotImplementedError(
            "empty_label: a RegistrySettingsForm subclass must implement this."
        )

    @classmethod
    def resolve(cls, definition: SettingDefinition, user: object) -> ResolvedSetting:
        """Resolve one setting the way this page reads it."""
        raise NotImplementedError(
            "resolve: a RegistrySettingsForm subclass must implement this."
        )

    @classmethod
    def keeps_initial(cls, resolved: ResolvedSetting) -> bool:
        """Whether a resolved value is prefilled into the control."""
        raise NotImplementedError(
            "keeps_initial: a RegistrySettingsForm subclass must implement this."
        )

    @classmethod
    def field_state(
        cls,
        definition: SettingDefinition,
        resolved: ResolvedSetting,
        *,
        live_save: bool,
    ) -> SettingFieldState:
        """Per-field settings metadata for this page."""
        raise NotImplementedError(
            "field_state: a RegistrySettingsForm subclass must implement this."
        )

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
        if definition.widget is SettingWidget.TEXT:
            override = _TEXT_FIELD_OVERRIDES.get(definition.key, TextFieldOverride())
            return forms.CharField(
                required=False,
                max_length=override.max_length,
                widget=forms.TextInput(
                    attrs={**override.widget_attrs, "placeholder": empty_label}
                ),
            )
        raise ValueError(
            f"{definition.key}: _build_field has no case for widget "
            f"{definition.widget!r}."
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
        # locked is intentionally omitted (stays False): locking exists for a
        # value frozen by env/ini ahead of the site DB, and this page only
        # ever writes UserPreferences, which nothing upstream of it can freeze.
        return SettingFieldState(
            definition.key,
            str(resolved.source),
            help_text=definition.user_help_text or definition.help_text,
            live_save=live_save,
            # Each control already names the site value it inherits, so an origin
            # badge here would only repeat it.
            show_source=False,
        )


class SettingsPageData(NamedTuple):
    """One settings page's form, per-field state, and the presentations that the
    state policy and the renderer must both see."""

    form: RegistrySettingsForm
    states: dict[SettingFieldName, SettingFieldState]
    presentations: dict[SettingFieldName, FormFieldPresentation]


def settings_page_data(
    form_class: type[RegistrySettingsForm],
    *,
    user: object = None,
    presentations: Mapping[SettingFieldName, FormFieldPresentation] | None = None,
) -> SettingsPageData:
    """Make one pass over the user-scoped definitions to build a page's form and
    per-field state, replacing what used to be two separate passes.

    That single pass is not the only resolve on the personal page: building the
    form also calls ``UserSettingsForm.empty_label``, which separately resolves
    the *site* value for its "Use site default (…)" text, while this function
    resolves each setting the way the page itself reads it (the user's own
    value, for a personal page). They read different things; the resolver's
    cached DB snapshots make the extra read cheap.

    A presentation that replaces the control (``decorate_control``) declares that
    something other than the generic live-save element owns it; a purely cosmetic
    presentation does not. A control someone else owns also skips the reload
    stamp, since the generic element is what would act on it.
    """
    supplied = dict(presentations or {})
    initial: dict[SettingFieldName, object] = {}
    states: dict[SettingFieldName, SettingFieldState] = {}
    reload_field_names: list[SettingFieldName] = []
    for definition in user_setting_definitions():
        field_name = field_name_for(definition)
        resolved = form_class.resolve(definition, user)
        if form_class.keeps_initial(resolved):
            initial[field_name] = resolved.value
        presentation = supplied.get(field_name)
        # A presentation with decorate_control replaces the generic control and
        # is assumed to persist the value itself (as ThemeSetting's PATCH does),
        # so this field is not live-saved by the generic element.
        live_save = presentation is None or presentation.decorate_control is None
        states[field_name] = form_class.field_state(
            definition, resolved, live_save=live_save
        )
        if definition.reload_after_save and live_save:
            reload_field_names.append(field_name)
    form = form_class(initial=initial)
    for field_name in reload_field_names:
        form.fields[field_name].widget.attrs["data-reload-after-save"] = ""
    return SettingsPageData(form, states, supplied)
