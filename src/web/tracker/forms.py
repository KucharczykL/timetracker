from django import forms

from .models import Game, Platform, Purchase, Session


class SessionForm(forms.ModelForm):
    class Meta:
        model = Session
        fields = [
            "purchase",
            "timestamp_start",
            "timestamp_end",
            "duration_manual",
            "note",
        ]
        custom_datetime_widget = forms.SplitDateTimeWidget(
            date_attrs={"type": "date"}, time_attrs={"type": "time"}
        )
        widgets = {
            "timestamp_start": custom_datetime_widget,
            "timestamp_end": custom_datetime_widget,
        }


class PurchaseForm(forms.ModelForm):
    class Meta:
        model = Purchase
        fields = ["game", "platform", "date_purchased", "date_refunded"]
        custom_date_widget = forms.DateInput(
            format=("%d-%m-%Y"), attrs={"type": "date"}
        )
        widgets = {
            "date_purchased": custom_date_widget,
            "date_refunded": custom_date_widget,
        }


class GameForm(forms.ModelForm):
    class Meta:
        model = Game
        fields = ["name", "wikidata"]


class PlatformForm(forms.ModelForm):
    class Meta:
        model = Platform
        fields = ["name", "group"]
