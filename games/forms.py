from django import forms

from games.models import Game, Platform, Purchase, Session


class SessionForm(forms.ModelForm):
    purchase = forms.ModelChoiceField(queryset=Purchase.objects.order_by("game__name"))

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
    game = forms.ModelChoiceField(queryset=Game.objects.order_by("name"))
    platform = forms.ModelChoiceField(queryset=Platform.objects.order_by("name"))

    class Meta:
        model = Purchase
        fields = ["game", "platform", "date_purchased", "date_refunded"]


class GameForm(forms.ModelForm):
    class Meta:
        model = Game
        fields = ["name", "wikidata"]


class PlatformForm(forms.ModelForm):
    class Meta:
        model = Platform
        fields = ["name", "group"]
