from django import forms
from django.urls import reverse

from common.utils import safe_getattr
from games.models import Device, Game, Platform, Purchase, Session

custom_date_widget = forms.DateInput(attrs={"type": "date"})
custom_datetime_widget = forms.DateTimeInput(
    attrs={"type": "datetime-local"}, format="%Y-%m-%d %H:%M"
)
autofocus_input_widget = forms.TextInput(attrs={"autofocus": "autofocus"})


class GameChoiceField(forms.ModelMultipleChoiceField):
    def label_from_instance(self, obj) -> str:
        return f"{obj.sort_name} ({obj.platform}, {obj.year_released})"


class SessionForm(forms.ModelForm):
    game = GameChoiceField(
        queryset=Game.objects.order_by("sort_name"),
        widget=forms.Select(attrs={"autofocus": "autofocus"}),
    )

    device = forms.ModelChoiceField(queryset=Device.objects.order_by("name"))

    mark_as_played = forms.BooleanField(
        required=False,
        initial={"mark_as_played": True},
        label="Set game status to Played if Unplayed",
    )

    class Meta:
        widgets = {
            "timestamp_start": custom_datetime_widget,
            "timestamp_end": custom_datetime_widget,
        }
        model = Session
        fields = [
            "game",
            "timestamp_start",
            "timestamp_end",
            "duration_manual",
            "emulated",
            "device",
            "note",
            "mark_as_played",
        ]

    def save(self, commit=True):
        session = super().save(commit=False)
        if self.cleaned_data.get("mark_as_played"):
            game_instance = session.game
            if game_instance.status == "u":
                game_instance.status = "p"
            if commit:
                game_instance.save()
        if commit:
            session.save()
        return session


class IncludePlatformSelect(forms.SelectMultiple):
    def create_option(self, name, value, *args, **kwargs):
        option = super().create_option(name, value, *args, **kwargs)
        if platform_id := safe_getattr(value, "instance.platform.id"):
            option["attrs"]["data-platform"] = platform_id
        return option


class PurchaseForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Automatically update related_purchase <select/>
        # to only include purchases of the selected game.
        related_purchase_by_game_url = reverse("related_purchase_by_game")
        self.fields["games"].widget.attrs.update(
            {
                "hx-trigger": "load, click",
                "hx-get": related_purchase_by_game_url,
                "hx-target": "#id_related_purchase",
                "hx-swap": "outerHTML",
            }
        )

    games = GameChoiceField(
        queryset=Game.objects.order_by("sort_name"),
        widget=IncludePlatformSelect(attrs={"autoselect": "autoselect"}),
    )
    platform = forms.ModelChoiceField(queryset=Platform.objects.order_by("name"))
    related_purchase = forms.ModelChoiceField(
        queryset=Purchase.objects.filter(type=Purchase.GAME),
        required=False,
    )

    class Meta:
        widgets = {
            "date_purchased": custom_date_widget,
            "date_refunded": custom_date_widget,
            "date_finished": custom_date_widget,
            "date_dropped": custom_date_widget,
        }
        model = Purchase
        fields = [
            "games",
            "platform",
            "date_purchased",
            "date_refunded",
            "date_finished",
            "date_dropped",
            "infinite",
            "price",
            "price_currency",
            "ownership_type",
            "type",
            "related_purchase",
            "name",
        ]

    def clean(self):
        cleaned_data = super().clean()
        purchase_type = cleaned_data.get("type")
        related_purchase = cleaned_data.get("related_purchase")
        name = cleaned_data.get("name")

        # Set the type on the instance to use get_type_display()
        # This is safe because we're not saving the instance.
        self.instance.type = purchase_type

        if purchase_type != Purchase.GAME:
            type_display = self.instance.get_type_display()
            if not related_purchase:
                self.add_error(
                    "related_purchase",
                    f"{type_display} must have a related purchase.",
                )
            if not name:
                self.add_error("name", f"{type_display} must have a name.")
        return cleaned_data


class IncludeNameSelect(forms.Select):
    def create_option(self, name, value, *args, **kwargs):
        option = super().create_option(name, value, *args, **kwargs)
        if value:
            option["attrs"]["data-name"] = value.instance.name
            option["attrs"]["data-year"] = value.instance.year_released
        return option


class GameModelChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        # Use sort_name as the label for the option
        return obj.sort_name


class GameForm(forms.ModelForm):
    platform = forms.ModelChoiceField(
        queryset=Platform.objects.order_by("name"), required=False
    )

    class Meta:
        model = Game
        fields = [
            "name",
            "sort_name",
            "platform",
            "year_released",
            "status",
            "wikidata",
        ]
        widgets = {"name": autofocus_input_widget}


class PlatformForm(forms.ModelForm):
    class Meta:
        model = Platform
        fields = [
            "name",
            "icon",
            "group",
        ]
        widgets = {"name": autofocus_input_widget}


class DeviceForm(forms.ModelForm):
    class Meta:
        model = Device
        fields = ["name", "type"]
        widgets = {"name": autofocus_input_widget}
