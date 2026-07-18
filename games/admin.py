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

# Register your models here.
admin.site.register(Game)
admin.site.register(Purchase)
admin.site.register(Platform)
admin.site.register(Session)
admin.site.register(Device)
admin.site.register(ExchangeRate)


class SiteSettingForm(forms.ModelForm):
    """Route admin writes through the same registry guards as
    ``set_site_setting`` so the admin isn't an unvalidated back door: only
    registered site-scoped keys, and the value must pass the field validator."""

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
        if definition.validator is not None and "value" in cleaned:
            try:
                cleaned["value"] = definition.validator(cleaned["value"])
            except ValidationError as error:
                raise ValidationError({"value": error.messages})
        return cleaned


@admin.register(SiteSetting)
class SiteSettingAdmin(admin.ModelAdmin):
    form = SiteSettingForm
    list_display = ["key", "value", "updated_at"]
