from django import forms

from games.models import Game, Platform, Purchase, Session, Edition


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
            "note",
        ]


class PurchaseForm(forms.ModelForm):
    edition = forms.ModelChoiceField(queryset=Edition.objects.order_by("name"))
    platform = forms.ModelChoiceField(queryset=Platform.objects.order_by("name"))

    class Meta:
        model = Purchase
        fields = ["edition", "platform", "date_purchased", "date_refunded"]


class EditionForm(forms.ModelForm):
    class Meta:
        model = Edition
        fields = ["game", "name", "platform"]


class GameForm(forms.ModelForm):
    class Meta:
        model = Game
        fields = ["name", "wikidata"]


class PlatformForm(forms.ModelForm):
    class Meta:
        model = Platform
        fields = ["name", "group"]
