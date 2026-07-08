from django import forms
from django.conf import settings
from django.contrib.auth.forms import AuthenticationForm
from django.db import transaction

from common.components import (
    DEFAULT_PREFETCH,
    DISABLED_CONTROL_CLASS,
    SearchSelect,
    SearchSelectOption,
    render,
    searchselect_selected,
)
from common.components.primitives import Checkbox
from games.dev_login import prefill_credentials
from games.models import (
    Device,
    Game,
    GameStatusChange,
    Platform,
    PlayEvent,
    Purchase,
    Session,
)

custom_date_widget = forms.DateInput(attrs={"type": "date"})
custom_datetime_widget = forms.DateTimeInput(
    attrs={"type": "datetime-local"}, format="%Y-%m-%d %H:%M"
)
autofocus_input_widget = forms.TextInput(attrs={"autofocus": "autofocus"})

# Form controls self-style: these utility strings live on the elements (applied
# by PrimitiveWidgetsMixin), so there is no form styling in input.css and no
# selector reaching in to style them. The disabled appearance is the shared
# DISABLED_CONTROL_CLASS so every form element looks the same disabled.
_DISABLED_CONTROL = DISABLED_CONTROL_CLASS
INPUT_CLASS = (
    "mb-3 bg-neutral-secondary-medium border border-default-medium text-heading "
    "text-sm rounded-base focus:ring-brand focus:border-brand block w-full "
    f"px-3 py-2.5 shadow-xs placeholder:text-body {_DISABLED_CONTROL}"
)
# No horizontal padding here: @tailwindcss/forms (base strategy) styles every
# bare <select> with appearance:none, a chevron pinned to the right edge, AND the
# right padding (~2.5rem/40px) that clears it. A px-*/pr-* utility can't win over
# that plugin rule for the right side, and px-* *does* override it symmetrically —
# pulling the right padding down so option text slides under the chevron (the old
# px-3 did exactly this on narrow selects, e.g. the field-comparison operator
# select). So set only vertical padding and let the plugin own the horizontal.
SELECT_CLASS = (
    "w-full py-2.5 bg-neutral-secondary-medium border border-default-medium "
    "text-heading text-sm rounded-base focus:ring-brand focus:border-brand "
    f"shadow-xs placeholder:text-body {_DISABLED_CONTROL}"
)
TEXTAREA_CLASS = (
    "bg-neutral-secondary-medium border border-default-medium text-heading "
    "text-sm rounded-base focus:ring-brand focus:border-brand block w-full p-3.5 "
    f"shadow-xs placeholder:text-body {_DISABLED_CONTROL}"
)


class PrimitiveCheckboxWidget(forms.CheckboxInput):
    """Adapts Django's CheckboxInput to use our Checkbox component."""

    def render(self, name, value, attrs=None, renderer=None):
        final_attrs = self.build_attrs(self.attrs, attrs)
        checked = self.check_test(value)
        attributes = [
            (k, str(v))
            for k, v in final_attrs.items()
            if k not in ("type", "name", "value", "checked")
        ]

        # Django uses boolean values differently for checkboxes, we omit value if empty
        # render() returns a safe string (Django widgets must not be autoescaped).
        return render(
            Checkbox(
                attributes,
                name=name,
                label=None,
                checked=checked,
                value=str(value) if value else "1",
            )
        )


class PrimitiveWidgetsMixin:
    """Automatically applies primitive custom widgets to native Django form fields."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            if isinstance(field, forms.BooleanField):
                field.widget = PrimitiveCheckboxWidget()
                # Maintain the field's explicit required status (usually False for booleans)
                continue
            widget = field.widget
            # SearchSelect is a self-styled composite component; never stamp the
            # native-control classes onto it.
            if isinstance(widget, SearchSelectWidget):
                continue
            if isinstance(widget, forms.Select):
                control_class = SELECT_CLASS
            elif isinstance(widget, forms.Textarea):
                control_class = TEXTAREA_CLASS
            else:
                control_class = INPUT_CLASS
            existing = widget.attrs.get("class", "")
            widget.attrs["class"] = f"{existing} {control_class}".strip()


class MultipleGameChoiceField(forms.ModelMultipleChoiceField):
    def label_from_instance(self, obj) -> str:
        return obj.search_label


class SingleGameChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj) -> str:
        return obj.search_label


def game_option_data(game: Game) -> dict[str, str]:
    """The data-* payload of a game option, shared by the games search API and
    this module's resolver — one producer, so the two sites cannot drift.
    Callers must select_related("platform")."""
    return {
        "platform": str(game.platform_id) if game.platform_id else "",
        "platform_name": game.platform.name if game.platform else "",
    }


def _game_options(values) -> list[SearchSelectOption]:
    """Resolve game ids (or instances) to SearchSelectOptions via one pk__in query."""
    return [
        {
            "value": g.id,
            "label": g.search_label,
            "data": game_option_data(g),
        }
        for g in Game.objects.filter(pk__in=values).select_related("platform")
    ]


def _device_options(values) -> list[SearchSelectOption]:
    return [
        {"value": d.id, "label": d.name, "data": {}}
        for d in Device.objects.filter(pk__in=values)
    ]


def _platform_options(values) -> list[SearchSelectOption]:
    return [
        {"value": p.id, "label": p.name, "data": {}}
        for p in Platform.objects.filter(pk__in=values)
    ]


class SearchSelectWidget(forms.Widget):
    """Thin Django adapter that renders a `SearchSelect()` component.

    The only place that knows about Django/forms — the component itself stays
    reusable outside forms.
    """

    def __init__(
        self,
        *,
        search_url,
        options_resolver,
        multi_select=False,
        items_visible=5,
        items_scroll=10,
        prefetch=DEFAULT_PREFETCH,
        always_visible=False,
        placeholder="Search…",
        attrs=None,
    ):
        super().__init__(attrs)
        self.search_url = search_url
        self.options_resolver = options_resolver
        self.multi_select = multi_select
        self.items_visible = items_visible
        self.items_scroll = items_scroll
        self.prefetch = prefetch
        self.always_visible = always_visible
        self.placeholder = placeholder

    @staticmethod
    def _values(value) -> list:
        if value is None:
            return []
        if isinstance(value, (list, tuple)):
            return [v for v in value if v not in (None, "")]
        return [value] if value not in (None, "") else []

    def render(self, name, value, attrs=None, renderer=None):
        selected = searchselect_selected(self._values(value), self.options_resolver)
        autofocus = bool((attrs or {}).get("autofocus"))
        # Django widgets must return a safe string; the component is a node.
        return render(
            SearchSelect(
                name=name,
                selected=selected,
                options=None,
                search_url=self.search_url,
                multi_select=self.multi_select,
                items_visible=self.items_visible,
                items_scroll=self.items_scroll,
                prefetch=self.prefetch,
                always_visible=self.always_visible,
                placeholder=self.placeholder,
                id=(attrs or {}).get("id", ""),
                autofocus=autofocus,
            )
        )

    def value_from_datadict(self, data, files, name):
        return data.get(name)


class SearchSelectMultiple(SearchSelectWidget):
    def value_from_datadict(self, data, files, name):
        if hasattr(data, "getlist"):
            return data.getlist(name)
        return data.get(name)


class SessionForm(PrimitiveWidgetsMixin, forms.ModelForm):
    game = SingleGameChoiceField(
        queryset=Game.objects.order_by("sort_name"),
        widget=SearchSelectWidget(
            search_url="/api/games/search", options_resolver=_game_options
        ),
    )

    duration_manual = forms.DurationField(
        required=False,
        widget=forms.TextInput(
            attrs={"x-mask": "99:99:99", "placeholder": "HH:MM:SS", "x-data": ""}
        ),
        label="Manual duration",
    )
    device = forms.ModelChoiceField(
        queryset=Device.objects.order_by("name"),
        required=False,
        widget=SearchSelectWidget(
            search_url="/api/devices/search", options_resolver=_device_options
        ),
    )

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


class PurchaseForm(PrimitiveWidgetsMixin, forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["platform"].queryset = Platform.objects.order_by("name")
        # The bundle Price is optional: in price-per-game mode it is hidden and
        # the per-game inputs carry the prices instead. Empty falls back to 0.
        self.fields["price"].required = False

    games = MultipleGameChoiceField(
        queryset=Game.objects.order_by("sort_name"),
        widget=SearchSelectMultiple(
            search_url="/api/games/search",
            options_resolver=_game_options,
            multi_select=True,
        ),
    )
    platform = forms.ModelChoiceField(
        queryset=Platform.objects.order_by("name"),
        required=False,
        widget=SearchSelectWidget(
            search_url="/api/platforms/search", options_resolver=_platform_options
        ),
    )
    related_game = forms.ModelChoiceField(
        queryset=Game.objects.order_by("sort_name"),
        required=False,
        widget=SearchSelectWidget(
            search_url="/api/games/search", options_resolver=_game_options
        ),
    )

    price_currency = forms.CharField(
        required=False,
        widget=forms.TextInput(
            attrs={
                "x-mask": "aaa",
                "placeholder": settings.DEFAULT_CURRENCY,
                "x-data": "",
                "class": "uppercase",
            }
        ),
        label="Currency",
    )

    class Meta:
        widgets = {
            "date_purchased": custom_date_widget,
            "date_refunded": custom_date_widget,
        }
        model = Purchase
        fields = [
            "games",
            "platform",
            "date_purchased",
            "date_refunded",
            "infinite",
            "price",
            "price_currency",
            "ownership_type",
            "type",
            "related_game",
            "name",
        ]

    def clean(self):
        cleaned_data = super().clean()
        purchase_type = cleaned_data.get("type")
        related_game = cleaned_data.get("related_game")
        name = cleaned_data.get("name")

        # Set the type on the instance to use get_type_display()
        # This is safe because we're not saving the instance.
        self.instance.type = purchase_type

        if purchase_type != Purchase.GAME:
            type_display = self.instance.get_type_display()
            if not related_game:
                self.add_error(
                    "related_game",
                    f"{type_display} must have a related game.",
                )
            if not name:
                self.add_error("name", f"{type_display} must have a name.")

        # An empty bundle Price (price-per-game mode) saves as 0, not NULL.
        if cleaned_data.get("price") is None:
            cleaned_data["price"] = 0

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


class GameForm(PrimitiveWidgetsMixin, forms.ModelForm):
    platform = forms.ModelChoiceField(
        queryset=Platform.objects.order_by("name"),
        required=False,
        widget=SearchSelectWidget(
            search_url="/api/platforms/search", options_resolver=_platform_options
        ),
    )

    class Meta:
        model = Game
        fields = [
            "name",
            "sort_name",
            "platform",
            "year_released",
            "original_year_released",
            "status",
            "mastered",
            "wikidata",
        ]
        widgets = {"name": autofocus_input_widget}


class PlatformForm(PrimitiveWidgetsMixin, forms.ModelForm):
    class Meta:
        model = Platform
        fields = [
            "name",
            "icon",
            "group",
        ]
        widgets = {"name": autofocus_input_widget}


class DeviceForm(PrimitiveWidgetsMixin, forms.ModelForm):
    class Meta:
        model = Device
        fields = ["name", "type"]
        widgets = {"name": autofocus_input_widget}


class PlayEventForm(PrimitiveWidgetsMixin, forms.ModelForm):
    game = SingleGameChoiceField(
        queryset=Game.objects.order_by("sort_name"),
        widget=SearchSelectWidget(
            search_url="/api/games/search",
            options_resolver=_game_options,
            attrs={"autofocus": "autofocus"},
        ),
    )

    mark_as_finished = forms.BooleanField(
        required=False,
        initial={"mark_as_finished": True},
        label="Set game status to Finished",
    )

    class Meta:
        model = PlayEvent
        fields = ["game", "started", "ended", "note", "mark_as_finished"]
        widgets = {
            "started": custom_date_widget,
            "ended": custom_date_widget,
        }

    def save(self, commit=True):
        with transaction.atomic():
            session = super().save(commit=False)
            if self.cleaned_data.get("mark_as_finished"):
                game_instance = session.game
                game_instance.status = "f"
                game_instance.save()
            session.save()
        return session


class GameStatusChangeForm(PrimitiveWidgetsMixin, forms.ModelForm):
    class Meta:
        model = GameStatusChange
        fields = [
            "game",
            "old_status",
            "new_status",
            "timestamp",
        ]
        widgets = {
            "timestamp": custom_datetime_widget,
        }


class LoginForm(PrimitiveWidgetsMixin, AuthenticationForm):
    """Django's auth form with our primitive widget styling so login inputs
    self-style like every other form (no styling-at-a-distance)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Dev/staging prefill only: Django's PasswordInput omits the value by
        # default; allow it to render so the login page can be pre-typed. Never
        # enabled when DEV_LOGIN_PREFILL is unset, so production never emits a
        # password value.
        if prefill_credentials():
            self.fields["password"].widget.render_value = True
