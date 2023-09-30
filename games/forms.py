from django import forms

from games.models import Game, Platform, Purchase, Session, Edition, Device

custom_date_widget = forms.DateInput(attrs={"type": "date"})
custom_datetime_widget = forms.DateTimeInput(
    attrs={"type": "datetime-local"}, format="%Y-%m-%d %H:%M"
)
autofocus_select_widget = forms.Select(attrs={"autofocus": "autofocus"})
autofocus_input_widget = forms.TextInput(attrs={"autofocus": "autofocus"})


class SessionForm(forms.ModelForm):
    # purchase = forms.ModelChoiceField(
    #     queryset=Purchase.objects.filter(date_refunded=None).order_by("edition__name")
    # )
    purchase = forms.ModelChoiceField(
        queryset=Purchase.objects.order_by("edition__name"),
        widget=autofocus_select_widget,
    )

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
        return f"{obj.name} ({obj.platform}, {obj.year_released})"


class PurchaseForm(forms.ModelForm):
    edition = EditionChoiceField(
        queryset=Edition.objects.order_by("name"), widget=autofocus_select_widget
    )
    platform = forms.ModelChoiceField(queryset=Platform.objects.order_by("name"))

    class Meta:
        widgets = {
            "date_purchased": custom_date_widget,
            "date_refunded": custom_date_widget,
        }
        model = Purchase
        fields = [
            "edition",
            "platform",
            "date_purchased",
            "date_refunded",
            "price",
            "price_currency",
            "ownership_type",
        ]


class EditionForm(forms.ModelForm):
    game = forms.ModelChoiceField(
        queryset=Game.objects.order_by("name"), widget=autofocus_select_widget
    )
    platform = forms.ModelChoiceField(queryset=Platform.objects.order_by("name"))

    class Meta:
        model = Edition
        fields = ["game", "name", "platform", "year_released", "wikidata"]


class GameForm(forms.ModelForm):
    class Meta:
        model = Game
        fields = ["name", "wikidata"]
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
