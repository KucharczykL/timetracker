from django import forms

from games.models import Game, Platform, Purchase, Session, Edition, Device

custom_date_widget = forms.DateInput(attrs={"type": "date"})
custom_datetime_widget = forms.DateTimeInput(
    attrs={"type": "datetime-local"}, format="%Y-%m-%d %H:%M"
)
autofocus_input_widget = forms.TextInput(attrs={"autofocus": "autofocus"})


class SessionForm(forms.ModelForm):
    # purchase = forms.ModelChoiceField(
    #     queryset=Purchase.objects.filter(date_refunded=None).order_by("edition__name")
    # )
    purchase = forms.ModelChoiceField(
        queryset=Purchase.objects.order_by("edition__sort_name"),
        widget=forms.Select(attrs={"autofocus": "autofocus"}),
    )

    device = forms.ModelChoiceField(queryset=Device.objects.order_by("name"))

    class Meta:
        widgets = {
            "timestamp_start": custom_datetime_widget,
            "timestamp_end": custom_datetime_widget,
        }
        model = Session
        fields = [
            "purchase",
            "timestamp_start",
            "timestamp_end",
            "duration_manual",
            "device",
            "note",
        ]


class EditionChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj) -> str:
        return f"{obj.sort_name} ({obj.platform}, {obj.year_released})"


class IncludePlatformSelect(forms.Select):
    def create_option(self, name, value, *args, **kwargs):
        option = super().create_option(name, value, *args, **kwargs)
        if value:
            option["attrs"]["data-platform"] = value.instance.platform.id
        return option


class PurchaseForm(forms.ModelForm):
    edition = EditionChoiceField(
        queryset=Edition.objects.order_by("sort_name"),
        widget=IncludePlatformSelect(attrs={"autoselect": "autoselect"}),
    )
    platform = forms.ModelChoiceField(queryset=Platform.objects.order_by("name"))

    class Meta:
        widgets = {
            "date_purchased": custom_date_widget,
            "date_refunded": custom_date_widget,
            "date_finished": custom_date_widget,
        }
        model = Purchase
        fields = [
            "edition",
            "platform",
            "date_purchased",
            "date_refunded",
            "date_finished",
            "price",
            "price_currency",
            "ownership_type",
        ]


class IncludeNameSelect(forms.Select):
    def create_option(self, name, value, *args, **kwargs):
        option = super().create_option(name, value, *args, **kwargs)
        if value:
            option["attrs"]["data-name"] = value.instance.name
        return option


class GameModelChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        # Use sort_name as the label for the option
        return obj.sort_name


class EditionForm(forms.ModelForm):
    game = GameModelChoiceField(
        queryset=Game.objects.order_by("sort_name"),
        widget=IncludeNameSelect(attrs={"autofocus": "autofocus"}),
    )
    platform = forms.ModelChoiceField(
        queryset=Platform.objects.order_by("name"), required=False
    )

    class Meta:
        model = Edition
        fields = ["game", "name", "sort_name", "platform", "year_released", "wikidata"]


class GameForm(forms.ModelForm):
    class Meta:
        model = Game
        fields = ["name", "sort_name", "year_released", "wikidata"]
        widgets = {"name": autofocus_input_widget}


class PlatformForm(forms.ModelForm):
    class Meta:
        model = Platform
        fields = ["name", "group"]
        widgets = {"name": autofocus_input_widget}


class DeviceForm(forms.ModelForm):
    class Meta:
        model = Device
        fields = ["name", "type"]
        widgets = {"name": autofocus_input_widget}
