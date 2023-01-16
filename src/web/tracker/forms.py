from django import forms

from .models import Game, Platform, Purchase, Session


class SessionForm(forms.ModelForm):
    custom_datetime_widget = forms.SplitDateTimeWidget(
        date_format=("%d-%m-%Y"),
        time_format=("%H:%M"),
        date_attrs={"type": "date"},
        time_attrs={"type": "time"},
    )
    timestamp_start = forms.SplitDateTimeField(
        input_date_formats="['%d-%m-%Y]",
        input_time_formats="['%H:%M']",
        widget=custom_datetime_widget,
    )
    timestamp_end = forms.SplitDateTimeField(
        input_date_formats="['%d-%m-%Y]",
        input_time_formats="['%H:%M']",
        widget=custom_datetime_widget,
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

        # fields_classes = {
        #     "timestamp_start": custom_datetime_field,
        #     "timestamp_end": custom_datetime_field,
        # }
        # widgets = {
        #     "timestamp_start": custom_datetime_widget,
        #     "timestamp_end": custom_datetime_widget,
        # }


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
