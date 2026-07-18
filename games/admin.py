from django import forms
from django.contrib import admin
from django.core.exceptions import ValidationError

from games.models import (
    Device,
    ExchangeRate,
    Game,
    Platform,
    Purchase,
    Session,
    SiteSetting,
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
    """Apply the same key/scope/normalize guards as ``set_site_setting`` so the
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
        if definition.scope is not SettingScope.SITE:
            raise ValidationError(
                {"key": f"{key!r} is not site-scoped and cannot be stored in the DB."}
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
