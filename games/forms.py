from django import forms

from games.models import Game, Platform, Purchase, Session, Edition, Device


class SessionForm(forms.ModelForm):
    purchase = forms.ModelChoiceField(
        queryset=Purchase.objects.order_by("edition__name")
    )

    class Meta:
        model = Session
        fields = [
            "purchase",
            "timestamp_start",
            "timestamp_end",
            "duration_manual",
            "device",
            "note",
        ]


class PurchaseForm(forms.ModelForm):
    edition = forms.ModelChoiceField(queryset=Edition.objects.order_by("name"))
    platform = forms.ModelChoiceField(queryset=Platform.objects.order_by("name"))

    class Meta:
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
    platform = forms.ModelChoiceField(queryset=Platform.objects.order_by("name"))

    class Meta:
        model = Edition
        fields = ["game", "name", "platform", "year_released", "wikidata"]


class GameForm(forms.ModelForm):
    class Meta:
        model = Game
        fields = ["name", "wikidata"]


class PlatformForm(forms.ModelForm):
    class Meta:
        model = Platform
        fields = ["name", "group"]


class DeviceForm(forms.ModelForm):
    class Meta:
        model = Device
        fields = ["name", "type"]
