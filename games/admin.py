from django import forms
from django.contrib import admin
from django.core.exceptions import ValidationError

from games.models import (
    USER_PREFERENCE_FIELD_BY_KEY,
    Device,
    ExchangeRate,
    Game,
    Platform,
    Purchase,
    Session,
    SiteSetting,
    UserPreferences,
)
from timetracker.settings_registry import (
    SettingScope,
    UnregisteredSettingError,
    get_definition,
)
from timetracker.settings_resolver import normalize_setting_value

# Register your models here.
admin.site.register(Game)
admin.site.register(Purchase)
admin.site.register(Platform)
admin.site.register(Session)
admin.site.register(Device)
admin.site.register(ExchangeRate)


class SiteSettingForm(forms.ModelForm):
    """Apply the same key/scope/normalize guards as the site command so the
    admin isn't an unvalidated back door into the resolver's DB layer."""

    class Meta:
        model = SiteSetting
        fields = ["key", "value"]

    def clean(self):
        cleaned = super().clean()
        key = cleaned.get("key")
        if not key:
            return cleaned
        try:
            definition = get_definition(key)
        except UnregisteredSettingError:
            raise ValidationError({"key": f"{key!r} is not a registered setting."})
        if definition.scope is SettingScope.INFRA:
            raise ValidationError(
                {"key": f"{key!r} is infra-scoped and cannot be stored in the DB."}
            )
        if "value" in cleaned:
            try:
                cleaned["value"] = normalize_setting_value(cleaned["value"], definition)
            except ValidationError as error:
                raise ValidationError({"value": error.messages})
            except (ValueError, TypeError) as error:
                raise ValidationError({"value": [str(error)]})
        return cleaned


@admin.register(SiteSetting)
class SiteSettingAdmin(admin.ModelAdmin):
    form = SiteSettingForm
    list_display = ["key", "value", "updated_at"]


class UserPreferencesForm(forms.ModelForm):
    """Validate each typed column and the extension bag through the registry, so
    the admin is not an unvalidated back door into the per-user resolver layer."""

    #: Typed column -> the USER key whose validator normalizes it.
    _COLUMN_KEYS = {
        "default_currency": "DEFAULT_CURRENCY",
        "default_device": "DEFAULT_DEVICE",
        "default_landing_page": "DEFAULT_LANDING_PAGE",
        "theme": "THEME",
        "display_time_zone": "DISPLAY_TIME_ZONE",
        "date_format_locale": "DATE_FORMAT_LOCALE",
        "datetime_format": "DATETIME_FORMAT",
    }

    class Meta:
        model = UserPreferences
        fields = [
            "user",
            "default_currency",
            "default_device",
            "default_landing_page",
            "theme",
            "display_time_zone",
            "date_format_locale",
            "datetime_format",
            "extra_preferences",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Nullable CharFields clean blank input to "" by default, which would
        # store an empty-string sentinel (and fail the currency validator).
        # Map blank -> None so "unset" stays NULL.
        for field_name in (
            "default_currency",
            "default_landing_page",
            "theme",
            "display_time_zone",
            "date_format_locale",
            "datetime_format",
        ):
            self.fields[field_name].empty_value = None

    def clean(self):
        cleaned = super().clean()
        for field_name, key in self._COLUMN_KEYS.items():
            value = cleaned.get(field_name)
            if value is None:
                continue
            definition = get_definition(key)
            # default_device cleans to a Device instance; the validator wants its
            # id. The FK widget already guarantees the device exists.
            raw = value.pk if field_name == "default_device" else value
            try:
                normalized = normalize_setting_value(raw, definition)
            except ValidationError as error:
                raise ValidationError({field_name: error.messages})
            except (ValueError, TypeError) as error:
                raise ValidationError({field_name: [str(error)]})
            if field_name != "default_device":
                cleaned[field_name] = normalized
        cleaned["extra_preferences"] = self._normalize_extra_preferences(
            cleaned.get("extra_preferences") or {}
        )
        return cleaned

    def _normalize_extra_preferences(self, extra):
        normalized = {}
        for key, value in extra.items():
            if key in USER_PREFERENCE_FIELD_BY_KEY:
                raise ValidationError(
                    {"extra_preferences": f"{key!r} has a typed column; use it."}
                )
            try:
                definition = get_definition(key)
            except UnregisteredSettingError:
                raise ValidationError(
                    {"extra_preferences": f"{key!r} is not a registered setting."}
                )
            if definition.scope is not SettingScope.USER:
                raise ValidationError(
                    {"extra_preferences": f"{key!r} is not a user-scoped setting."}
                )
            if value is None:
                continue
            try:
                normalized[key] = normalize_setting_value(value, definition)
            except ValidationError as error:
                raise ValidationError({"extra_preferences": error.messages})
            except (ValueError, TypeError) as error:
                raise ValidationError({"extra_preferences": [str(error)]})
        return normalized


@admin.register(UserPreferences)
class UserPreferencesAdmin(admin.ModelAdmin):
    form = UserPreferencesForm
    list_display = [
        "user",
        "default_currency",
        "default_device",
        "theme",
        "display_time_zone",
        "date_format_locale",
        "datetime_format",
        "updated_at",
    ]
