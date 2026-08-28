import datetime
from collections.abc import Callable, Mapping
from functools import partial
from typing import ClassVar, Final, cast
from zoneinfo import ZoneInfo

from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone

from common.components import (
    DEFAULT_PREFETCH,
    DISABLED_CONTROL_CLASS,
    DatePicker,
    DateTimeCopyTarget,
    DateTimePicker,
    SearchSelect,
    SearchSelectOption,
    TimeZoneRow,
    render,
    searchselect_selected,
)
from common.components.primitives import Checkbox
from common.date_time_presentation import DateTimePresentation, zone_or_none
from games.dev_login import prefill_credentials
from games.external_references import normalize_provider_key
from games.models import (
    Device,
    ExternalReference,
    Game,
    GameStatusChange,
    Platform,
    PlayEvent,
    Purchase,
    Session,
    UserLibrary,
)
from timetracker.settings_registry import DISPLAY_TIME_ZONE_CHOICES
from timetracker.settings_resolver import resolve_str_for_user

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
            widget,
            (
                SearchSelectWidget,
                DatePickerWidget,
                DateTimeFieldWidget,
                TimeZoneRowWidget,
            ),
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


class LibraryPreferencesForm(PrimitiveWidgetsMixin, forms.Form):
    """Library-owned preferences rendered through the shared settings field kit."""

    default_device = forms.ModelChoiceField(
        queryset=Device.objects.none(),
        label="Default device",
        required=False,
        empty_label="No default device",
    )

    def __init__(
        self,
        *,
        devices: QuerySet[Device],
        default_device: Device | None,
    ) -> None:
        super().__init__()
        default_device_field = cast(
            forms.ModelChoiceField, self.fields["default_device"]
        )
        default_device_field.queryset = devices
        self.initial["default_device"] = default_device


class MultipleGameChoiceField(forms.ModelMultipleChoiceField):
    def label_from_instance(self, obj) -> str:
        return obj.search_label


class SingleGameChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj) -> str:
        return obj.search_label


def game_option_data(game: Game) -> dict[str, str]:
    """The data-* payload of a game option, shared by the games search API and
    this module's resolver — one producer, so the two sites cannot drift.

    Reads the platform's own pk rather than the foreign key attname, which is
    the identity the platform combobox's options carry. Callers must
    select_related("platform")."""
    return {
        "platform": str(game.platform.id) if game.platform else "",
        "platform_name": game.platform.name if game.platform else "",
    }


def _game_options(values, *, library: UserLibrary) -> list[SearchSelectOption]:
    """Resolve game ids (or instances) to SearchSelectOptions via one pk__in query."""
    return [
        {
            "value": g.id,
            "label": g.search_label,
            "data": game_option_data(g),
        }
        for g in Game.objects.for_library(library)
        .filter(pk__in=values)
        .select_related("platform")
    ]


def _device_options(values, *, library: UserLibrary) -> list[SearchSelectOption]:
    return [
        {"value": d.id, "label": d.name, "data": {}}
        for d in Device.objects.for_library(library).filter(pk__in=values)
    ]


def _platform_options(values, *, library: UserLibrary) -> list[SearchSelectOption]:
    return [
        {"value": p.id, "label": p.name, "data": {}}
        for p in Platform.objects.visible_to(library).filter(pk__in=values)
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

    ``zone_resolver`` (set by ``SessionForm``) is the paired zone picker's
    current zone. The offset-qualified value the widget normally submits binds
    the same under any active zone; the *naive* fallback shape (a DST-gap
    submission) must be interpreted — and gap/ambiguity-checked — in the zone
    the digits were typed against, not the account zone.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.zone_resolver: Callable[[], ZoneInfo] | None = None

    def prepare_value(self, value):
        return value

    def to_python(self, value):
        if self.zone_resolver is None:
            return super().to_python(value)
        with timezone.override(self.zone_resolver()):
            return super().to_python(value)


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
        zone_field_name: str = "",
        zone_resolver: Callable[[], ZoneInfo] | None = None,
        attrs=None,
    ):
        super().__init__(attrs)
        self.presentation = presentation
        self.label = label
        self.copy_target = copy_target
        self.zone_field_name = zone_field_name
        self.zone_resolver = zone_resolver

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
                zone = (
                    self.zone_resolver()
                    if self.zone_resolver
                    else self.presentation.timezone
                )
                value = timezone.localtime(value, zone)
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
                zone_field_name=self.zone_field_name,
            )
        )

    def value_from_datadict(self, data, files, name):
        return data.get(name)


class TimeZoneRowWidget(forms.Widget):
    """Thin Django adapter that renders a `TimeZoneRow()` component for a
    per-timestamp zone field. The row's picker trigger is always visible; the
    hidden input inside the component is the submitted channel this widget
    reads back."""

    def __init__(
        self,
        *,
        label: str,
        display_zone: str,
        capture_default: bool,
        attrs=None,
    ):
        super().__init__(attrs)
        self.label = label
        self.display_zone = display_zone
        self.capture_default = capture_default

    def render(self, name, value, attrs=None, renderer=None):
        return render(
            TimeZoneRow(
                field_name=name,
                label=self.label,
                stored_zone=str(value) if value else "",
                display_zone=self.display_zone,
                capture_default=self.capture_default,
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
_TIME_ZONE_FORM_CHOICES: Final[tuple[tuple[str, str], ...]] = (
    ("", "Account display zone"),
    *DISPLAY_TIME_ZONE_CHOICES,
)
_TIMESTAMP_TIMEZONE_LABELS: Final[dict[str, str]] = {
    "timestamp_start_timezone": "Start time zone",
    "timestamp_end_timezone": "End time zone",
}
# The FormFields `embedded` mapping: each zone picker renders inside its
# timestamp's row, not as a labelled row of its own.
SESSION_TIMEZONE_EMBEDS: Final[dict[str, str]] = {
    "timestamp_start_timezone": "timestamp_start",
    "timestamp_end_timezone": "timestamp_end",
}
# Host timestamp → its zone field: the inverse view the datetime widgets need.
_TIMESTAMP_ZONE_FIELDS: Final[dict[str, str]] = {
    host_name: zone_name for zone_name, host_name in SESSION_TIMEZONE_EMBEDS.items()
}


class SessionForm(PrimitiveWidgetsMixin, forms.ModelForm):
    def __init__(
        self,
        *args,
        library: UserLibrary,
        presentation: DateTimePresentation,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.library = library
        cast(
            forms.ModelChoiceField, self.fields["game"]
        ).queryset = Game.objects.for_library(library).order_by("sort_name")
        self.fields["game"].widget.options_resolver = partial(
            _game_options, library=library
        )
        cast(
            forms.ModelChoiceField, self.fields["device"]
        ).queryset = Device.objects.for_library(library).order_by("name")
        self.fields["device"].widget.options_resolver = partial(
            _device_options, library=library
        )
        self._presentation = presentation
        for field_name, copy_target in _TIMESTAMP_COPY_TARGETS.items():
            zone_field_name = _TIMESTAMP_ZONE_FIELDS[field_name]
            zone_resolver = partial(self._resolved_field_zone, zone_field_name)
            self.fields[field_name].widget = DateTimeFieldWidget(
                presentation=presentation,
                label=str(self.fields[field_name].label or field_name),
                copy_target=copy_target,
                zone_field_name=zone_field_name,
                zone_resolver=zone_resolver,
            )
            timestamp_field = self.fields[field_name]
            assert isinstance(timestamp_field, AwareDateTimeField)
            timestamp_field.zone_resolver = zone_resolver
        is_new_record = self.instance._state.adding
        # The end zone is only meaningful once an end timestamp exists: an open
        # session stamped at creation would carry that zone into a finish that
        # happens elsewhere, hours later. The start is always about to be
        # committed on a new record, so it captures unconditionally.
        end_timestamp_supplied = bool(
            self.initial.get("timestamp_end")
            or (self.is_bound and self.data.get("timestamp_end"))
        )
        captures_by_field = {
            "timestamp_start_timezone": is_new_record,
            "timestamp_end_timezone": is_new_record and end_timestamp_supplied,
        }
        for field_name, zone_label in _TIMESTAMP_TIMEZONE_LABELS.items():
            self.fields[field_name].widget = TimeZoneRowWidget(
                label=zone_label,
                display_zone=presentation.timezone.key,
                capture_default=captures_by_field[field_name],
            )

    def _resolved_field_zone(self, zone_field_name: str) -> ZoneInfo:
        """The zone this timestamp's digits are meant in: the paired zone
        picker's current value when usable, else the account display zone."""
        if self.is_bound:
            raw_zone = self.data.get(zone_field_name)
        else:
            raw_zone = self.initial.get(zone_field_name)
        zone = zone_or_none(raw_zone if isinstance(raw_zone, str) else None)
        return zone or self._presentation.timezone

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

    timestamp_start_timezone = forms.TypedChoiceField(
        required=False, choices=_TIME_ZONE_FORM_CHOICES, empty_value=None
    )
    timestamp_end_timezone = forms.TypedChoiceField(
        required=False, choices=_TIME_ZONE_FORM_CHOICES, empty_value=None
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
            "timestamp_start_timezone",
            "timestamp_end",
            "timestamp_end_timezone",
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
        library: UserLibrary,
        user: User,
        presentation: DateTimePresentation,
        **kwargs,
    ):
        self.library = library
        self.default_currency = resolve_str_for_user(user, "DEFAULT_PURCHASE_CURRENCY")
        super().__init__(*args, **kwargs)
        self.instance.library = library
        games = Game.objects.for_library(library).order_by("sort_name")
        visible_platforms = Platform.objects.visible_to(library).order_by("name")
        cast(forms.ModelMultipleChoiceField, self.fields["games"]).queryset = games
        self.fields["games"].widget.options_resolver = partial(
            _game_options, library=library
        )
        cast(forms.ModelChoiceField, self.fields["related_game"]).queryset = games
        self.fields["related_game"].widget.options_resolver = partial(
            _game_options, library=library
        )
        platform_field = cast(forms.ModelChoiceField, self.fields["platform"])
        platform_field.queryset = visible_platforms
        platform_field.widget.options_resolver = partial(
            _platform_options, library=library
        )
        # The bundle Price is optional: in price-per-game mode it is hidden and
        # the per-game inputs carry the prices instead. Empty falls back to 0.
        self.fields["price"].required = False
        if not self.initial.get("price_currency"):
            self.initial["price_currency"] = self.default_currency
        self.fields["price_currency"].widget.attrs["placeholder"] = (
            self.default_currency
        )
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


class _LibraryBoundConstraintValidationMixin:
    def _get_validation_exclusions(self):
        exclusions = super()._get_validation_exclusions()
        # ``library`` is assigned by the constructor rather than submitted by
        # the browser. Django otherwise excludes it from model constraint
        # validation because it is not a form field, allowing a per-library
        # duplicate to reach the database as an IntegrityError.
        exclusions.discard("library")
        # ``tombstoned_at`` is the same story, with a sharper edge.
        # Django skips a conditional constraint whose condition
        # names an excluded field. A form row is live, so it
        # contributes the NULL the condition expects.
        exclusions.discard("tombstoned_at")
        return exclusions


class GameForm(
    _LibraryBoundConstraintValidationMixin, PrimitiveWidgetsMixin, forms.ModelForm
):
    def __init__(self, *args, library: UserLibrary, **kwargs):
        super().__init__(*args, **kwargs)
        self.library = library
        self.instance.library = library
        cast(
            forms.ModelChoiceField, self.fields["platform"]
        ).queryset = Platform.objects.visible_to(library).order_by("name")
        self.fields["platform"].widget.options_resolver = partial(
            _platform_options, library=library
        )
        #: model_to_dict no longer covers these two, because they left
        #: Meta.fields, so an edit form would open at the column defaults.
        if self.instance.pk is not None:
            self.initial.setdefault("status", self.instance.status)
            self.initial.setdefault("mastered", self.instance.mastered)

    platform = forms.ModelChoiceField(
        queryset=Platform.objects.order_by("name"),
        required=False,
        widget=SearchSelectWidget(
            search_url="/api/platforms/search", options_resolver=_platform_options
        ),
    )

    #: Plain form fields rather than model fields: form.save() must not write
    #: either column. The write path is the single writer, and #678 deletes
    #: these two when the reads move to the projection.
    status = forms.ChoiceField(choices=Game.Status.choices, required=True)
    mastered = forms.BooleanField(required=False)

    #: A declared field naming no model field is appended after the model
    #: fields, so without this the two would drop to the bottom of the form.
    field_order = (
        "name",
        "sort_name",
        "platform",
        "year_released",
        "original_year_released",
        "status",
        "mastered",
        "wikidata",
    )

    def save(self, commit=True):
        game = super().save(commit=False)
        #: A new row starts at the state the form states, so the mirror finds
        #: the catalog and the projection already equal. Creating it at the
        #: column default and letting the mirror move it would append a
        #: GameStatusChange that does not exist today: the pre_save audit
        #: signal returns early when no previous row exists.
        if game._state.adding:
            game.status = self.cleaned_data["status"]
            game.mastered = self.cleaned_data["mastered"]
        if commit:
            game.save()
            self.save_m2m()
        return game

    def clean_wikidata(self) -> str:
        value = self.cleaned_data["wikidata"]
        if not value.strip():
            return ""

        try:
            _, canonical_key = normalize_provider_key(
                provider="wikidata", provider_key=value
            )
        except forms.ValidationError as error:
            raise forms.ValidationError(error.messages) from error

        references = ExternalReference.objects.filter(
            provider="wikidata",
            entity_kind="game",
            provider_key=canonical_key,
        )
        if self.instance.pk is not None:
            references = references.exclude(game_id=self.instance.pk)
        if references.exists():
            raise forms.ValidationError(
                "This Wikidata entity ID already belongs to another game."
            )
        return canonical_key

    class Meta:
        model = Game
        fields = (
            "name",
            "sort_name",
            "platform",
            "year_released",
            "original_year_released",
            "wikidata",
        )
        widgets: ClassVar[dict[str, forms.Widget]] = {"name": autofocus_input_widget}


class PlatformForm(
    _LibraryBoundConstraintValidationMixin, PrimitiveWidgetsMixin, forms.ModelForm
):
    def __init__(self, *args, library: UserLibrary, **kwargs):
        super().__init__(*args, **kwargs)
        self.library = library
        self.instance.library = library

    class Meta:
        model = Platform
        fields = (
            "name",
            "icon",
            "group",
        )
        widgets: ClassVar[dict[str, forms.Widget]] = {"name": autofocus_input_widget}


class DeviceForm(PrimitiveWidgetsMixin, forms.ModelForm):
    def __init__(self, *args, library: UserLibrary, **kwargs):
        super().__init__(*args, **kwargs)
        self.library = library
        self.instance.library = library

    class Meta:
        model = Device
        fields = ("name", "type")
        widgets: ClassVar[dict[str, forms.Widget]] = {"name": autofocus_input_widget}


class PlayEventForm(PrimitiveWidgetsMixin, forms.ModelForm):
    def __init__(
        self,
        *args,
        library: UserLibrary,
        presentation: DateTimePresentation,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.library = library
        cast(
            forms.ModelChoiceField, self.fields["game"]
        ).queryset = Game.objects.for_library(library).order_by("sort_name")
        self.fields["game"].widget.options_resolver = partial(
            _game_options, library=library
        )
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
    def __init__(
        self,
        *args,
        library: UserLibrary,
        presentation: DateTimePresentation,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.library = library
        cast(
            forms.ModelChoiceField, self.fields["game"]
        ).queryset = Game.objects.for_library(library).order_by("sort_name")
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
