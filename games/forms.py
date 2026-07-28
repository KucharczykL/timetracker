import datetime
from collections.abc import Mapping
from typing import ClassVar, cast

from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.db import transaction
from django.utils import timezone

from common.components import (
    DEFAULT_PREFETCH,
    DISABLED_CONTROL_CLASS,
    DatePicker,
    DateTimeCopyTarget,
    DateTimePicker,
    SearchSelect,
    SearchSelectOption,
    render,
    searchselect_selected,
)
from common.components.primitives import Checkbox
from common.date_time_presentation import DateTimePresentation
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

autofocus_input_widget = forms.TextInput(attrs={"autofocus": "autofocus"})

# Form controls self-style: these utility strings live on the elements (applied
# by PrimitiveWidgetsMixin), so there is no form styling in input.css and no
# selector reaching in to style them. The disabled appearance is the shared
# DISABLED_CONTROL_CLASS so every form element looks the same disabled.
_DISABLED_CONTROL = DISABLED_CONTROL_CLASS
# text-type-input owns the 16px flat size — 16px everywhere stops iOS
# Safari auto-zooming focused inputs (#427) and needs no responsive pair.
# text-heading is the colour; placeholder:text-body the placeholder colour.
INPUT_CLASS = (
    "bg-neutral-secondary-medium border border-default-medium text-heading "
    "text-type-input rounded-base focus:ring-brand focus:border-brand block w-full "
    f"px-3 min-h-control shadow-xs placeholder:text-body {_DISABLED_CONTROL}"
)
# No horizontal padding here: @tailwindcss/forms (base strategy) styles every
# bare <select> with appearance:none, a chevron pinned to the right edge, AND the
# right padding (~2.5rem/40px) that clears it. A px-*/pr-* utility can't win over
# that plugin rule for the right side, and px-* *does* override it symmetrically —
# pulling the right padding down so option text slides under the chevron (the old
# px-3 did exactly this on narrow selects, e.g. the field-comparison operator
# select). So set the shared control height and let the plugin own the horizontal.
SELECT_CLASS = (
    "w-full min-h-control bg-neutral-secondary-medium border border-default-medium "
    "text-heading text-type-input rounded-base focus:ring-brand focus:border-brand "
    f"shadow-xs placeholder:text-body {_DISABLED_CONTROL}"
)
# A textarea is multiline: it keeps its own vertical padding and is excluded
# from the min-h-control single-height scale.
TEXTAREA_CLASS = (
    "bg-neutral-secondary-medium border border-default-medium text-heading "
    "text-type-input rounded-base focus:ring-brand focus:border-brand block w-full "
    "px-3 py-2.5 "  # control-ok: multiline textarea keeps its own vertical padding
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


def apply_primitive_widget_classes(fields: Mapping[str, forms.Field]) -> None:
    """Stamp the shared native-control classes over a form's fields.

    Callable on its own so a form that builds fields after ``super().__init__()``
    can opt in; :class:`PrimitiveWidgetsMixin` is the declarative path.
    """
    for field in fields.values():
        if isinstance(field, forms.BooleanField):
            field.widget = PrimitiveCheckboxWidget()
            # Maintain the field's explicit required status (usually False for booleans)
            continue
        widget = field.widget
        # SearchSelect/DatePicker/DateTimeField are self-styled composite
        # components; never stamp the native-control classes onto them.
        if isinstance(
            widget, (SearchSelectWidget, DatePickerWidget, DateTimeFieldWidget)
        ):
            continue
        if isinstance(widget, forms.Select):
            control_class = SELECT_CLASS
        elif isinstance(widget, forms.Textarea):
            control_class = TEXTAREA_CLASS
        else:
            control_class = INPUT_CLASS
        existing = widget.attrs.get("class", "")
        widget.attrs["class"] = f"{existing} {control_class}".strip()


class PrimitiveWidgetsMixin:
    """Automatically applies primitive custom widgets to native Django form fields."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        apply_primitive_widget_classes(self.fields)


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
        autofocus=False,
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
        self.autofocus = autofocus

    @staticmethod
    def _values(value) -> list:
        if value is None:
            return []
        if isinstance(value, (list, tuple)):
            return [v for v in value if v not in (None, "")]
        return [value] if value not in (None, "") else []

    def render(self, name, value, attrs=None, renderer=None):
        selected = searchselect_selected(self._values(value), self.options_resolver)
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
                autofocus=self.autofocus,
                # Host the form combobox in <drop-down behavior="inline-combobox">
                # so its panel uses the shared attachMenu open/close/position/dismiss
                # engine (issue #348). The widget's own input stays the trigger.
                host_dropdown=True,
            )
        )

    def value_from_datadict(self, data, files, name):
        return data.get(name)


class SearchSelectMultiple(SearchSelectWidget):
    def value_from_datadict(self, data, files, name):
        if hasattr(data, "getlist"):
            return data.getlist(name)
        return data.get(name)


class DatePickerWidget(forms.Widget):
    """Thin Django adapter that renders a `DatePicker()` component in place
    of a native `<input type="date">` (issue #485), so the account's
    DATETIME_FORMAT preference controls the visible segment order. Submits
    and binds canonical ISO ``YYYY-MM-DD`` through the hidden input
    unchanged — Django's default `DateField` parsing is untouched."""

    def __init__(self, *, presentation: DateTimePresentation, label: str, attrs=None):
        super().__init__(attrs)
        self.presentation = presentation
        self.label = label

    def _iso_value(self, value) -> str:
        if value in (None, ""):
            return ""
        if isinstance(value, datetime.datetime):
            # An aware initial (e.g. add_purchase seeds timezone.now()) is
            # localized to the active account timezone before taking the
            # date part, so "today" means today in the user's own zone.
            localized = timezone.localtime(value, self.presentation.timezone)
            return localized.date().isoformat()
        if isinstance(value, datetime.date):
            return value.isoformat()
        return str(value)

    def render(self, name, value, attrs=None, renderer=None):
        final_attrs = self.build_attrs(self.attrs, attrs)
        return render(
            DatePicker(
                presentation=self.presentation,
                label=self.label,
                name=name,
                value=self._iso_value(value),
                input_id=str(final_attrs.get("id", "")),
                required=bool(final_attrs.get("required")),
                invalid=final_attrs.get("aria-invalid") == "true",
            )
        )

    def value_from_datadict(self, data, files, name):
        return data.get(name)


class AwareDateTimeField(forms.DateTimeField):
    """A ``DateTimeField`` that hands its widget the *aware* stored value.

    Django's ``prepare_value`` runs ``to_current_timezone()``, so a widget
    normally receives a bare wall clock. For the one hour a DST fall-back
    repeats, that wall clock happens twice and the naive form no longer says
    which instant was stored — and Django refuses to bind an ambiguous naive
    value back, so an untouched edit of such a session could not be saved at
    all. Keeping it aware lets the widget emit the offset alongside the wall
    clock, which is exactly what the client commits, so the round-trip is
    lossless for every instant.
    """

    def prepare_value(self, value):
        return value


class DateTimeFieldWidget(forms.Widget):
    """Thin Django adapter that renders a `DateTimePicker()` component in place
    of a native `<input type="datetime-local">` (issue #511), so the account's
    DATETIME_FORMAT preference controls the visible segment order and the hour
    cycle.

    The submitted value is an offset-qualified wall clock, which
    ``DateTimeField.to_python`` parses as aware — so `from_current_timezone`
    no-ops and the field binds to exactly the instant the user saw. Two wire
    shapes therefore reach `render()`: the offset-qualified one this emits, and
    the bare wall clock a DST-gap submission posts back. `datetime_part_values`
    reads both, so a rejected form re-renders what was typed."""

    def __init__(
        self,
        *,
        presentation: DateTimePresentation,
        label: str,
        copy_target: DateTimeCopyTarget | None = None,
        attrs=None,
    ):
        super().__init__(attrs)
        self.presentation = presentation
        self.label = label
        self.copy_target = copy_target

    def _wire_value(self, value) -> str:
        if value in (None, ""):
            return ""
        if isinstance(value, datetime.datetime):
            # Django's DateTimeField.prepare_value has already run
            # to_current_timezone() on anything that reaches a widget, so a
            # datetime here is naive and reads as the *active* zone's wall
            # clock — which is the presentation's own zone (both resolve from
            # DISPLAY_TIME_ZONE). localtime() is for the aware value a caller
            # can still hand a widget directly.
            if timezone.is_aware(value):
                value = timezone.localtime(value, self.presentation.timezone)
            return value.isoformat()
        return str(value)

    def render(self, name, value, attrs=None, renderer=None):
        final_attrs = self.build_attrs(self.attrs, attrs)
        return render(
            DateTimePicker(
                presentation=self.presentation,
                label=self.label,
                name=name,
                value=self._wire_value(value),
                input_id=str(final_attrs.get("id", "")),
                required=bool(final_attrs.get("required")),
                invalid=final_attrs.get("aria-invalid") == "true",
                copy_target=self.copy_target,
            )
        )

    def value_from_datadict(self, data, files, name):
        return data.get(name)


# Each session timestamp can copy itself into the other one. The arrow points
# the way the target sits in the form, so the control reads as a direction.
_TIMESTAMP_COPY_TARGETS = {
    "timestamp_start": DateTimeCopyTarget(
        "timestamp_end", "Copy start value to end", "↓"
    ),
    "timestamp_end": DateTimeCopyTarget(
        "timestamp_start", "Copy end value to start", "↑"
    ),
}


class SessionForm(PrimitiveWidgetsMixin, forms.ModelForm):
    def __init__(self, *args, presentation: DateTimePresentation, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, copy_target in _TIMESTAMP_COPY_TARGETS.items():
            self.fields[field_name].widget = DateTimeFieldWidget(
                presentation=presentation,
                label=str(self.fields[field_name].label or field_name),
                copy_target=copy_target,
            )

    game = SingleGameChoiceField(
        queryset=Game.objects.order_by("sort_name"),
        widget=SearchSelectWidget(
            search_url="/api/games/search",
            options_resolver=_game_options,
            autofocus=True,
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
        # timestamp_start/timestamp_end get DateTimeFieldWidget in __init__
        # (needs the per-request presentation, unavailable to a class body);
        # the field class is declarative because it depends on nothing.
        # TODO(py3.15, ~Oct 2026): the ClassVar dict annotations on these Meta
        # tables satisfy RUF012 — candidates for the builtin ``frozendict``
        # (PEP 814) on 3.15; see the note on GameFilter.fields in filters.py.
        field_classes: ClassVar[dict[str, type[forms.Field]]] = {
            "timestamp_start": AwareDateTimeField,
            "timestamp_end": AwareDateTimeField,
        }
        model = Session
        fields = (
            "game",
            "timestamp_start",
            "timestamp_end",
            "duration_manual",
            "emulated",
            "device",
            "note",
            "mark_as_played",
        )

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
    def __init__(
        self,
        *args,
        default_currency: str,
        presentation: DateTimePresentation,
        **kwargs,
    ):
        self.default_currency = default_currency
        super().__init__(*args, **kwargs)
        platform_field = cast(forms.ModelChoiceField, self.fields["platform"])
        platform_field.queryset = Platform.objects.order_by("name")
        # The bundle Price is optional: in price-per-game mode it is hidden and
        # the per-game inputs carry the prices instead. Empty falls back to 0.
        self.fields["price"].required = False
        if not self.initial.get("price_currency"):
            self.initial["price_currency"] = default_currency
        self.fields["price_currency"].widget.attrs["placeholder"] = default_currency
        for field_name in ("date_purchased", "date_refunded"):
            self.fields[field_name].widget = DatePickerWidget(
                presentation=presentation,
                label=str(self.fields[field_name].label or field_name),
            )

    games = MultipleGameChoiceField(
        queryset=Game.objects.order_by("sort_name"),
        widget=SearchSelectMultiple(
            search_url="/api/games/search",
            options_resolver=_game_options,
            multi_select=True,
            autofocus=True,
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
        label="Base game",
    )

    price_currency = forms.CharField(
        required=False,
        widget=forms.TextInput(
            attrs={
                "x-mask": "aaa",
                # placeholder is set in __init__ from the caller's user context.
                "x-data": "",
                "class": "uppercase",
            }
        ),
        label="Currency",
    )

    class Meta:
        # date_purchased/date_refunded get DatePickerWidget in __init__
        # (needs the per-request presentation, unavailable to a class body).
        model = Purchase
        fields = (
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
        )

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
        if not cleaned_data.get("price_currency"):
            cleaned_data["price_currency"] = self.default_currency

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
        fields = (
            "name",
            "sort_name",
            "platform",
            "year_released",
            "original_year_released",
            "status",
            "mastered",
            "wikidata",
        )
        widgets: ClassVar[dict[str, forms.Widget]] = {"name": autofocus_input_widget}


class PlatformForm(PrimitiveWidgetsMixin, forms.ModelForm):
    class Meta:
        model = Platform
        fields = (
            "name",
            "icon",
            "group",
        )
        widgets: ClassVar[dict[str, forms.Widget]] = {"name": autofocus_input_widget}


class DeviceForm(PrimitiveWidgetsMixin, forms.ModelForm):
    class Meta:
        model = Device
        fields = ("name", "type")
        widgets: ClassVar[dict[str, forms.Widget]] = {"name": autofocus_input_widget}


class PlayEventForm(PrimitiveWidgetsMixin, forms.ModelForm):
    def __init__(self, *args, presentation: DateTimePresentation, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name in ("started", "ended"):
            self.fields[field_name].widget = DatePickerWidget(
                presentation=presentation,
                label=str(self.fields[field_name].label or field_name),
            )

    game = SingleGameChoiceField(
        queryset=Game.objects.order_by("sort_name"),
        widget=SearchSelectWidget(
            search_url="/api/games/search",
            options_resolver=_game_options,
            autofocus=True,
        ),
    )

    mark_as_finished = forms.BooleanField(
        required=False,
        initial={"mark_as_finished": True},
        label="Set game status to Finished",
    )

    class Meta:
        # started/ended get DatePickerWidget in __init__ (needs the
        # per-request presentation, unavailable to a class body).
        model = PlayEvent
        fields = ("game", "started", "ended", "note", "mark_as_finished")

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
    def __init__(self, *args, presentation: DateTimePresentation, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["timestamp"].widget = DateTimeFieldWidget(
            presentation=presentation,
            label=str(self.fields["timestamp"].label or "timestamp"),
        )

    class Meta:
        # timestamp gets DateTimeFieldWidget in __init__ (needs the
        # per-request presentation, unavailable to a class body); the field
        # class is declarative because it depends on nothing.
        field_classes: ClassVar[dict[str, type[forms.Field]]] = {
            "timestamp": AwareDateTimeField
        }
        model = GameStatusChange
        fields = (
            "game",
            "old_status",
            "new_status",
            "timestamp",
        )


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
