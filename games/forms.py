import datetime
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import partial
from typing import Any, ClassVar, Final, cast
from zoneinfo import ZoneInfo

from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.models import User
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
    TemporalField,
    TimeZoneRow,
    render,
    searchselect_selected,
)
from common.components.primitives import Checkbox
from common.date_time_presentation import DateTimePresentation, zone_or_none
from games.commands.playersession import (
    CorrectedTiming,
    DurationOnlyTiming,
    TimedTiming,
    TimingStatement,
)
from games.dev_login import prefill_credentials
from games.models import (
    Device,
    Game,
    Platform,
    PlayerGame,
    PlayerGameStatus,
    PlayerSession,
    Playthrough,
    Purchase,
    UserLibrary,
)
from games.reads.companion_status import played_is_offered
from games.reads.playthrough_numbering import display_name, numbered_for
from games.reads.playthrough_runs import library_runs, tracked_game
from timetracker.settings_registry import DISPLAY_TIME_ZONE_CHOICES
from timetracker.settings_resolver import resolve_str_for_user
from timetracker.temporal import (
    EMPTY_TEMPORAL_DRAFT_DATA,
    TemporalDraft,
    TemporalDraftData,
    TemporalValue,
    TemporalValueParseError,
    parse_temporal_value,
    temporal_draft_data,
    temporal_draft_from_data,
    temporal_input_name,
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
            # An explicitly hidden boolean is a choice the form made: a
            # checkbox here puts the field back on the page, and
            # `is_hidden` renderers then leave it out of the POST entirely.
            if not field.widget.is_hidden:
                field.widget = PrimitiveCheckboxWidget()
            # Maintain the field's explicit required status (usually False for booleans)
            continue
        widget = field.widget
        # SearchSelect/DatePicker/DateTimeField/Temporal are self-styled
        # composite components; never stamp the native classes onto them.
        if isinstance(
            widget,
            (
                SearchSelectWidget,
                DatePickerWidget,
                DateTimeFieldWidget,
                TimeZoneRowWidget,
                TemporalWidget,
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


class TemporalWidget(forms.Widget):
    """Renders a `TemporalField()` component in place of a native control.

    Follows `DatePickerWidget`: one field name yields several inputs, and
    `value_from_datadict` reads them all back. What it returns is the raw
    posted text, not a parsed draft, so a submission the grammar refuses
    re-renders the characters a person typed.

    A widget renders to text, so the node tree ends here and the custom
    element's `Media` never reaches `collect_media()`. The hosting view
    must thread `scripts=ModuleScript("dist/elements/temporal-field.js")`
    itself, the way the purchase and play-event pages already do for the
    date picker. #969 is the first page that hosts one.
    """

    def __init__(
        self, *, presentation: DateTimePresentation, label: str, attrs=None
    ) -> None:
        super().__init__(attrs)
        self.presentation = presentation
        self.label = label

    def _data(self, value) -> TemporalDraftData:
        if isinstance(value, dict):
            return cast(TemporalDraftData, value)
        if value in (None, ""):
            return temporal_draft_data(TemporalDraft())
        stored = parse_temporal_value(value)
        return temporal_draft_data(TemporalDraft.from_value(stored))

    def render(self, name, value, attrs=None, renderer=None):
        final_attrs = self.build_attrs(self.attrs, attrs)
        return render(
            TemporalField(
                name=name,
                data=self._data(value),
                label=self.label,
                presentation=self.presentation,
                input_id=str(final_attrs.get("id", "")),
                required=bool(final_attrs.get("required")),
                invalid=final_attrs.get("aria-invalid") == "true",
            )
        )

    def value_from_datadict(self, data, files, name) -> TemporalDraftData:
        return TemporalDraftData(
            kind=data.get(temporal_input_name(name, "kind"), ""),
            start_year=data.get(temporal_input_name(name, "start_year"), ""),
            start_month=data.get(temporal_input_name(name, "start_month"), ""),
            start_day=data.get(temporal_input_name(name, "start_day"), ""),
            start_decade=data.get(temporal_input_name(name, "start_decade"), ""),
            start_approximate=data.get(
                temporal_input_name(name, "start_approximate"), ""
            ),
            start_uncertain=data.get(temporal_input_name(name, "start_uncertain"), ""),
            end_year=data.get(temporal_input_name(name, "end_year"), ""),
            end_month=data.get(temporal_input_name(name, "end_month"), ""),
            end_day=data.get(temporal_input_name(name, "end_day"), ""),
            end_decade=data.get(temporal_input_name(name, "end_decade"), ""),
            end_approximate=data.get(temporal_input_name(name, "end_approximate"), ""),
            end_uncertain=data.get(temporal_input_name(name, "end_uncertain"), ""),
        )

    def value_omitted_from_data(self, data, files, name) -> bool:
        """The real name is in no POST body. The kind is."""
        return temporal_input_name(name, "kind") not in data


class TemporalFormField(forms.Field):
    """Cleans a temporal control's inputs to one `TemporalValue`.

    An unknown value cleans to ``None``, which is what the model field
    stores for one — so a form and a column agree on what nothing is.
    """

    def __init__(
        self, *, presentation: DateTimePresentation, label: str = "Date", **kwargs
    ) -> None:
        kwargs.setdefault(
            "widget", TemporalWidget(presentation=presentation, label=label)
        )
        kwargs.setdefault("required", False)
        super().__init__(label=label, **kwargs)

    def to_python(self, value) -> TemporalValue | None:
        try:
            built = temporal_draft_from_data(self._data(value)).build()
        except TemporalValueParseError as error:
            raise forms.ValidationError(str(error), code=error.code) from error
        return None if built.is_unknown else built

    def has_changed(self, initial, data) -> bool:
        # Django's own guard: nobody touches a disabled control.
        if self.disabled:
            return False
        try:
            submitted = self.to_python(data)
        except forms.ValidationError:
            return True
        return submitted != self._stored(initial)

    @staticmethod
    def _data(value) -> TemporalDraftData:
        if isinstance(value, dict):
            return cast(TemporalDraftData, value)
        if value in (None, ""):
            return EMPTY_TEMPORAL_DRAFT_DATA
        return temporal_draft_data(
            TemporalDraft.from_value(parse_temporal_value(value))
        )

    @staticmethod
    def _stored(initial) -> TemporalValue | None:
        if initial in (None, ""):
            return None
        stored = parse_temporal_value(initial)
        return None if stored.is_unknown else stored


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


# Each session instant can copy itself into the other one. The arrow points
# the way the target sits in the form, so the control reads as a direction.
_INSTANT_COPY_TARGETS = {
    "started_at": DateTimeCopyTarget("ended_at", "Copy start value to end", "↓"),
    "ended_at": DateTimeCopyTarget("started_at", "Copy end value to start", "↑"),
}
_TIME_ZONE_FORM_CHOICES: Final[tuple[tuple[str, str], ...]] = (
    ("", "Account display zone"),
    *DISPLAY_TIME_ZONE_CHOICES,
)
_INSTANT_ZONE_LABELS: Final[dict[str, str]] = {
    "started_at_zone": "Start time zone",
    "ended_at_zone": "End time zone",
}
# The FormFields `embedded` mapping: each zone picker renders inside its
# instant's row, not as a labelled row of its own.
SESSION_TIMEZONE_EMBEDS: Final[dict[str, str]] = {
    "started_at_zone": "started_at",
    "ended_at_zone": "ended_at",
}
# Host instant → its zone field: the inverse view the datetime widgets need.
_INSTANT_ZONE_FIELDS: Final[dict[str, str]] = {
    host_name: zone_name for zone_name, host_name in SESSION_TIMEZONE_EMBEDS.items()
}

#: The picker's route: `?game=` narrows it to one game's runs.
PLAYTHROUGH_API_URL: Final = "/api/playthrough/"

#: The two refusals the derivation states, on the field that caused each.
START_WITH_DURATION_ALONE = (
    "Give an end as well, or leave the start empty and state the day."
)
DAY_BESIDE_AN_INSTANT = "State either a day or a start time, not both."
NEITHER_START_NOR_DAY = "Give a start time, or a day and how long it lasted."
DAY_WITHOUT_DURATION = "State how long it lasted on that day."
END_WITHOUT_START = "An end needs a start."
END_BEFORE_START = "The end is before the start."


@dataclass(frozen=True, slots=True)
class TimingDraft:
    """The parts one submit stated; the zone the library counts days in
    arrives later, from the calendar, so the statement is built on demand."""

    started_at: datetime.datetime | None
    started_at_zone: str | None
    ended_at: datetime.datetime | None
    ended_at_zone: str | None
    day: datetime.date | None
    duration: datetime.timedelta | None

    def statement(self, day_zone: str) -> TimingStatement:
        """The one statement these parts derive to; `clean()` refused the rest."""

        if self.started_at is None:
            assert self.day is not None and self.duration is not None
            return DurationOnlyTiming(day=self.day, duration=self.duration)
        if self.ended_at is not None and self.duration is not None:
            return CorrectedTiming(
                started_at=self.started_at,
                ended_at=self.ended_at,
                duration=self.duration,
                day_zone=day_zone,
                started_at_zone=self.started_at_zone,
                ended_at_zone=self.ended_at_zone,
            )
        return TimedTiming(
            started_at=self.started_at,
            day_zone=day_zone,
            started_at_zone=self.started_at_zone,
            ended_at=self.ended_at,
            ended_at_zone=self.ended_at_zone,
        )


class PlaythroughSelectWidget(forms.Select):
    """A native ``<select>`` inside ``<playthrough-select>``.

    The options the server renders are the runs of the game the form
    already knows; the element refills them when the game changes and
    hides itself while the game holds one run.
    """

    def __init__(self, *, game_field: str, api_url: str, attrs=None):
        super().__init__(attrs)
        self.game_field = game_field
        self.api_url = api_url

    def render(self, name, value, attrs=None, renderer=None):
        from common.components import Safe
        from common.components.custom_elements import _PlaythroughSelect

        select = super().render(name, value, attrs=attrs, renderer=renderer)
        return render(
            _PlaythroughSelect(
                game_field=self.game_field,
                api_url=self.api_url,
                selected="" if value in (None, "") else str(value),
                class_="block",
            )[Safe(select)]
        )


def _run_choices(library: UserLibrary, game: Game | None) -> list[tuple[str, str]]:
    """The game's live ordinary runs, each by its display name."""
    if game is None:
        return []
    tracked = tracked_game(library, game)
    if tracked is None:
        return []
    return [
        (str(run.pk), display_name(run)) for run in numbered_for(library, [tracked.pk])
    ]


class SessionForm(PrimitiveWidgetsMixin, forms.Form):
    """One session, in the projection's words.

    No mode control: the statement is derived from which fields are
    filled. A start alone is a running Timed session; a start and an end
    a finished one; both with a duration a Corrected one; a day and a
    duration alone a Duration-only one. Anything else is refused on the
    field that caused it.
    """

    def __init__(
        self,
        *args,
        library: UserLibrary,
        presentation: DateTimePresentation,
        instance: PlayerSession | None = None,
        **kwargs,
    ):
        initial = dict(kwargs.pop("initial", None) or {})
        if instance is not None:
            initial = {**_session_initial(instance), **initial}
        super().__init__(*args, initial=initial, **kwargs)
        self.library = library
        self.instance = instance
        cast(
            forms.ModelChoiceField, self.fields["game"]
        ).queryset = Game.objects.for_library(library).order_by("sort_name")
        self.fields["game"].widget.options_resolver = partial(
            _game_options, library=library
        )
        runs = cast(forms.ModelChoiceField, self.fields["playthrough"])
        runs.queryset = library_runs(library)
        runs.choices = _run_choices(library, self._known_game())
        cast(
            forms.ModelChoiceField, self.fields["device"]
        ).queryset = Device.objects.for_library(library).order_by("name")
        self.fields["device"].widget.options_resolver = partial(
            _device_options, library=library
        )
        self._presentation = presentation
        for field_name, copy_target in _INSTANT_COPY_TARGETS.items():
            zone_field_name = _INSTANT_ZONE_FIELDS[field_name]
            zone_resolver = partial(self._resolved_field_zone, zone_field_name)
            self.fields[field_name].widget = DateTimeFieldWidget(
                presentation=presentation,
                label=str(self.fields[field_name].label or field_name),
                copy_target=copy_target,
                zone_field_name=zone_field_name,
                zone_resolver=zone_resolver,
            )
            instant_field = self.fields[field_name]
            assert isinstance(instant_field, AwareDateTimeField)
            instant_field.zone_resolver = zone_resolver
        self.fields["day"].widget = DatePickerWidget(
            presentation=presentation, label="Day"
        )
        is_new_record = instance is None
        # The end zone is only meaningful once an end exists: an open session
        # stamped at creation would carry that zone into a finish that happens
        # elsewhere, hours later. The start is always about to be committed
        # on a new record, so it captures unconditionally.
        end_supplied = bool(
            self.initial.get("ended_at")
            or (self.is_bound and self.data.get("ended_at"))
        )
        captures_by_field = {
            "started_at_zone": is_new_record,
            "ended_at_zone": is_new_record and end_supplied,
        }
        for field_name, zone_label in _INSTANT_ZONE_LABELS.items():
            self.fields[field_name].widget = TimeZoneRowWidget(
                label=zone_label,
                display_zone=presentation.timezone.key,
                capture_default=captures_by_field[field_name],
            )

    def _known_game(self) -> Game | None:
        """The game the picker lists runs of: the bound one, else the initial."""
        raw = self.data.get("game") if self.is_bound else self.initial.get("game")
        if isinstance(raw, Game):
            return raw
        if raw in (None, ""):
            return None
        return Game.objects.for_library(self.library).filter(pk=raw).first()

    def _resolved_field_zone(self, zone_field_name: str) -> ZoneInfo:
        """The zone this instant's digits are meant in: the paired zone
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
    playthrough = forms.ModelChoiceField(
        queryset=Playthrough.objects.none(),
        widget=PlaythroughSelectWidget(game_field="game", api_url=PLAYTHROUGH_API_URL),
        label="Playthrough",
    )
    # started_at/ended_at get DateTimeFieldWidget in __init__ (needs the
    # per-request presentation, unavailable to a class body).
    started_at = AwareDateTimeField(required=False, label="Start")
    started_at_zone = forms.TypedChoiceField(
        required=False, choices=_TIME_ZONE_FORM_CHOICES, empty_value=None
    )
    ended_at = AwareDateTimeField(required=False, label="End")
    ended_at_zone = forms.TypedChoiceField(
        required=False, choices=_TIME_ZONE_FORM_CHOICES, empty_value=None
    )
    day = forms.DateField(required=False)
    duration = forms.DurationField(
        required=False,
        widget=forms.TextInput(
            attrs={"x-mask": "99:99:99", "placeholder": "HH:MM:SS", "x-data": ""}
        ),
    )
    device = forms.ModelChoiceField(
        queryset=Device.objects.order_by("name"),
        required=False,
        widget=SearchSelectWidget(
            search_url="/api/devices/search", options_resolver=_device_options
        ),
    )
    note = forms.CharField(required=False, widget=forms.Textarea)
    emulated = forms.BooleanField(required=False)
    mark_as_played = forms.BooleanField(
        required=False,
        initial=True,
        label="Set game status to Played if Unplayed",
    )

    def clean(self):
        cleaned = super().clean()
        game = cleaned.get("game")
        run = cleaned.get("playthrough")
        if game is not None and run is not None and run.player_game.game_id != game.pk:
            self.add_error("playthrough", "That playthrough is another game's.")
        started_at = cleaned.get("started_at")
        ended_at = cleaned.get("ended_at")
        day = cleaned.get("day")
        duration = cleaned.get("duration")
        if started_at is None:
            if ended_at is not None:
                self.add_error("started_at", END_WITHOUT_START)
            elif day is None and duration is None:
                self.add_error("started_at", NEITHER_START_NOR_DAY)
            elif day is None:
                self.add_error("day", NEITHER_START_NOR_DAY)
            elif duration is None:
                self.add_error("duration", DAY_WITHOUT_DURATION)
        else:
            if day is not None:
                self.add_error("day", DAY_BESIDE_AN_INSTANT)
            if ended_at is None and duration is not None:
                self.add_error("duration", START_WITH_DURATION_ALONE)
            if ended_at is not None and ended_at < started_at:
                self.add_error("ended_at", END_BEFORE_START)
        if not self.errors:
            self.timing_draft = TimingDraft(
                started_at=started_at,
                started_at_zone=cleaned.get("started_at_zone") or None,
                ended_at=ended_at,
                ended_at_zone=cleaned.get("ended_at_zone") or None,
                day=day,
                duration=duration,
            )
        return cleaned

    def timing_statement(self, day_zone: str) -> TimingStatement:
        """The statement this submit derives to, in the library's calendar."""
        return self.timing_draft.statement(day_zone)


def _session_initial(session: PlayerSession) -> dict[str, Any]:
    """What the edit form seeds from the row, by its mode."""
    run = session.playthrough
    return {
        "game": run.player_game.game,
        "playthrough": run.pk,
        "started_at": session.started_at,
        "started_at_zone": session.started_at_zone,
        "ended_at": session.ended_at,
        "ended_at_zone": session.ended_at_zone,
        "day": session.stated_day,
        "duration": session.stated_duration,
        "device": session.device_id,
        "note": session.note,
        "emulated": session.emulated,
    }


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
        # ``removed_at`` is the same story, with a sharper edge.
        # Django skips a conditional constraint whose condition
        # names an excluded field. A form row is live, so it
        # contributes the NULL the condition expects.
        exclusions.discard("removed_at")
        return exclusions


class GameForm(
    _LibraryBoundConstraintValidationMixin, PrimitiveWidgetsMixin, forms.ModelForm
):
    def __init__(
        self,
        *args,
        library: UserLibrary,
        presentation: DateTimePresentation,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.library = library
        self.instance.library = library
        #: The column is not editable, thus no model field reaches
        #: the form and the initial is stated by hand.
        self.fields["original_release_date"] = TemporalFormField(
            presentation=presentation, label="Original release"
        )
        #: A field added after __init__ otherwise sinks to the bottom.
        self.order_fields(self.field_order)
        #: They left Meta.fields, so model_to_dict misses them.
        if self.instance.pk is not None:
            self.initial.setdefault(
                "original_release_date", self.instance.original_release_date
            )
            tracked = PlayerGame.objects.filter(
                library=library, game=self.instance
            ).first()
            if tracked is not None:
                self.initial.setdefault("status", tracked.status)
                self.initial.setdefault("mastered", tracked.mastered)

    #: Plain fields: this form writes no column.
    #: The initial is what tracking would create.
    status = forms.ChoiceField(
        choices=PlayerGameStatus.choices,
        required=True,
        initial=PlayerGameStatus.UNPLAYED,
    )
    mastered = forms.BooleanField(required=False)

    #: Declared fields otherwise sink below model fields.
    field_order = (
        "name",
        "sort_name",
        "original_release_date",
        "status",
        "mastered",
    )

    def save(self, commit=True):
        game = super().save(commit=False)
        if commit:
            game.save()
            self.save_m2m()
        return game

    class Meta:
        model = Game
        #: The Platform and the release year moved to the Release
        #: that states them; the two integer columns beside them are
        #: a mirror now, written by `games/catalog_compat.py`.
        fields = ("name", "sort_name")
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


class PlaythroughForm(PrimitiveWidgetsMixin, forms.Form):
    """One run, as a person states it.

    A plain Form: the submit states commands and writes no row, so
    there is nothing for ModelForm to save. The four declarations
    ModelForm derived are restated here against the same columns.
    """

    def __init__(
        self,
        *args,
        library: UserLibrary,
        presentation: DateTimePresentation,
        locked_game: Game | None = None,
        offered_game: Game | None = None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.library = library
        #: An edit states facts about one run,
        #: and no command moves a run between games.
        self.locked_game = locked_game
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
        #: The status decides the render. No game yet is
        #: the Add form before one is picked, which offers
        #: the box and asks again at clean time.
        if offered_game is not None and not played_is_offered(library, offered_game):
            del self.fields["also_mark_played"]

    game = SingleGameChoiceField(
        queryset=Game.objects.order_by("sort_name"),
        widget=SearchSelectWidget(
            search_url="/api/games/search",
            options_resolver=_game_options,
            autofocus=True,
        ),
    )

    #: started/ended get DatePickerWidget in __init__ (needs the
    #: per-request presentation, unavailable to a class body).
    started = forms.DateField(required=False)
    ended = forms.DateField(required=False)
    #: No cap: the 255 came from the legacy column, and
    #: Playthrough.note is a TextField.
    note = forms.CharField(required=False)

    #: Rendered where no stronger status is stated: an
    #: Unplayed game, one no library tracks yet, and the
    #: Add form before a game is picked.
    also_mark_played = forms.BooleanField(
        required=False,
        initial=True,
        label="Also mark this game Played",
    )
    also_mark_completed = forms.BooleanField(
        required=False,
        initial=True,
        label="Also mark this game Completed",
    )

    def clean_game(self) -> Game:
        game = self.cleaned_data["game"]
        if self.locked_game is not None and game.pk != self.locked_game.pk:
            raise forms.ValidationError(
                "A playthrough stays with its game. Remove this one and add "
                "it to the other game instead."
            )
        return game

    def clean(self) -> dict[str, Any]:
        """Drop a box this game offers no status.

        The Add form renders the Played box
        before a game is picked, so a posted
        one is decided here. A field the render
        gate took out cleans to False alone.
        """
        cleaned = super().clean() or {}
        cleaned.setdefault("also_mark_played", False)
        cleaned.setdefault("also_mark_completed", False)
        game = cleaned.get("game")
        if game is not None and not played_is_offered(self.library, game):
            cleaned["also_mark_played"] = False
        return cleaned


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
