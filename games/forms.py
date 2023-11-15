from django import forms
from django.urls import reverse
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
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Automatically update related_purchase <select/>
        # to only include purchases of the selected edition.
        related_purchase_by_edition_url = reverse("related_purchase_by_edition")
        self.fields["edition"].widget.attrs.update(
            {
                "hx-get": related_purchase_by_edition_url,
                "hx-target": "#id_related_purchase",
                "hx-swap": "outerHTML",
            }
        )

    edition = EditionChoiceField(
        queryset=Edition.objects.order_by("sort_name"),
        widget=IncludePlatformSelect(attrs={"autoselect": "autoselect"}),
    )
    platform = forms.ModelChoiceField(queryset=Platform.objects.order_by("name"))
    related_purchase = forms.ModelChoiceField(
        queryset=Purchase.objects.filter(type=Purchase.GAME).order_by(
            "edition__sort_name"
        ),
        required=False,
    )

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
