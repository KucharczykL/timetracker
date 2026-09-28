import copy
import datetime
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from functools import partial
from typing import TYPE_CHECKING, Any, ClassVar, Final, Literal, NamedTuple, cast
from zoneinfo import ZoneInfo

from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.models import User
from django.db.models import QuerySet
from django.forms.models import ModelChoiceIterator
from django.http import QueryDict
from django.utils import timezone
from django.utils.choices import normalize_choices
from django.utils.datastructures import MultiValueDict

from common.components import (
    DEFAULT_PREFETCH,
    DISABLED_CONTROL_CLASS,
    CreateRow,
    DatePicker,
    DateTimeCopyTarget,
    DateTimePicker,
    Media,
    NoneLabel,
    PostCreate,
    PostedName,
    Safe,
    SearchSelect,
    SearchSelectOption,
    SelectTyped,
    TemporalCopySource,
    TemporalField,
    TimeZoneRow,
    UnsetField,
    render,
    searchselect_selected,
    unset_input_name,
)
from common.components.core import Node
from common.components.elements import Fieldset
from common.components.icon_picker import IconChoice, IconPicker
from common.components.primitives import (
    SHAPE_CLASSES,
    ButtonShape,
    Checkbox,
    Input,
    Label,
    MediaWidget,
    Radio,
    field_label_id,
)
from common.date_time_presentation import DateTimePresentation, zone_or_none
from common.platform_icons import PLATFORM_ICONS, UNSPECIFIED_ICON
from games.commands.historical_playtime import (
    HistoricalPlaytimeStatement,
    when_sentence,
)
from games.commands.playersession import (
    CorrectedTiming,
    DurationOnlyTiming,
    TimedTiming,
    TimingStatement,
)
from games.commands.session_reclassification import statement_from_session
from games.dev_login import prefill_credentials
from games.events.idempotency import IdempotencyKey
from games.models import (
    Device,
    Game,
    HistoricalPlaytime,
    HistoricalPlaytimeProvenance,
    Platform,
    PlayerGame,
    PlayerGameStatus,
    PlayerSession,
    Playthrough,
    Purchase,
    UserLibrary,
)
from games.reads.companion_status import played_is_offered
from games.reads.platform_groups import platform_groups
from games.reads.playthrough_numbering import display_name, numbered_for
from games.reads.playthrough_runs import library_runs, tracked_game
from games.writes.playersession import latest_ordinary_run
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

if TYPE_CHECKING:
    from django.utils.choices import _Choices


autofocus_input_widget = forms.TextInput(attrs={"autofocus": "autofocus"})

# Form controls self-style: these utility strings live on the elements (applied
# by PrimitiveWidgetsMixin), so there is no form styling in input.css and no
# selector reaching in to style them. The disabled appearance is the shared
# DISABLED_CONTROL_CLASS so every form element looks the same disabled.
_DISABLED_CONTROL = DISABLED_CONTROL_CLASS
# text-type-input owns the 16px flat size — 16px everywhere stops iOS
# Safari auto-zooming focused inputs (#427) and needs no responsive pair.
# text-heading is the colour; placeholder:text-body the placeholder colour.
_INPUT_LOOK = (
    "bg-neutral-secondary-medium border border-default-medium text-heading "
    "text-type-input focus:ring-brand focus:border-brand block w-full "
    f"px-3 min-h-control shadow-xs placeholder:text-body {_DISABLED_CONTROL}"
)
# No horizontal padding here: @tailwindcss/forms (base strategy) styles every
# bare <select> with appearance:none, a chevron pinned to the right edge, AND the
# right padding (~2.5rem/40px) that clears it. A px-*/pr-* utility can't win over
# that plugin rule for the right side, and px-* *does* override it symmetrically —
# pulling the right padding down so option text slides under the chevron (the old
# px-3 did exactly this on narrow selects, e.g. the field-comparison operator
# select). So set the shared control height and let the plugin own the horizontal.
_SELECT_LOOK = (
    "w-full min-h-control bg-neutral-secondary-medium border border-default-medium "
    "text-heading text-type-input focus:ring-brand focus:border-brand "
    f"shadow-xs placeholder:text-body {_DISABLED_CONTROL}"
)
# A textarea is multiline: it keeps its own vertical padding and is excluded
# from the min-h-control single-height scale.
_TEXTAREA_LOOK = (
    "bg-neutral-secondary-medium border border-default-medium text-heading "
    "text-type-input focus:ring-brand focus:border-brand block w-full "
    "px-3 py-2.5 "  # control-ok: multiline textarea keeps its own vertical padding
    f"shadow-xs placeholder:text-body {_DISABLED_CONTROL}"
)


def native_control_class(widget: forms.Widget, shape: ButtonShape = "full") -> str:
    """A native control's classes, rounding ``shape``'s corners."""
    if isinstance(widget, forms.Select):
        look = _SELECT_LOOK
    elif isinstance(widget, forms.Textarea):
        look = _TEXTAREA_LOOK
    else:
        look = _INPUT_LOOK
    return f"{look} {SHAPE_CLASSES[shape]}".strip()


INPUT_CLASS = native_control_class(forms.TextInput())
SELECT_CLASS = native_control_class(forms.Select())
TEXTAREA_CLASS = native_control_class(forms.Textarea())


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
                _SearchSelectAdapter,
                DatePickerWidget,
                DateTimeFieldWidget,
                TimeZoneRowWidget,
                TemporalWidget,
                _ChoiceListWidget,
                IconPickerWidget,
                HoursMinutesWidget,
                # Shapes its own control.
                UnsetWidget,
            ),
        ):
            continue
        existing = widget.attrs.get("class", "")
        widget.attrs["class"] = f"{existing} {native_control_class(widget)}".strip()


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


def device_options(values, *, library: UserLibrary) -> list[SearchSelectOption]:
    return [
        {"value": d.id, "label": d.name, "data": {}}
        for d in Device.objects.for_library(library).filter(pk__in=values)
    ]


def run_options(values, *, library: UserLibrary) -> list[SearchSelectOption]:
    """Resolve run ids to options, each by its display name.

    A blank name is numbered rather than stored, so the rows are
    read through the numbering. The number counts over a tracked
    game's runs, thus the games the wanted keys name are read
    first and every run of those games is numbered: a queryset
    narrowed inside one game numbers its row 1.

    The keys are compared as text. A posted value is a string and a
    column holds a UUID, and the other resolvers only avoid that
    because `pk__in` coerces for them.
    """
    wanted = {str(getattr(value, "pk", value)) for value in values}
    if not wanted:
        return []
    tracked_games = (
        library_runs(library)
        .filter(pk__in=[key for key in wanted])
        .values_list("player_game_id", flat=True)
    )
    return [
        {"value": run.id, "label": display_name(run), "data": {}}
        for run in numbered_for(library, list(tracked_games))
        if str(run.pk) in wanted
    ]


def _platform_options(values, *, library: UserLibrary) -> list[SearchSelectOption]:
    return [
        {"value": p.id, "label": p.name, "data": {}}
        for p in Platform.objects.visible_to(library).filter(pk__in=values)
    ]


#: Where a picker searches a library's devices.
DEVICE_SEARCH_URL = "/api/devices/search"

#: Where a picker makes the row a person typed.
DEVICE_CREATE_URL = "/api/devices/"
PLATFORM_CREATE_URL = "/api/platforms/"
PLAYTHROUGH_CREATE_URL = "/api/playthrough/"


class _SearchSelectAdapter(forms.Widget):
    """Django half every form `SearchSelect` shares."""

    component_media: ClassVar[Media] = Media(
        js=("dist/elements/search-select.js", "dist/elements/drop-down.js")
    )

    def __init__(
        self,
        *,
        placeholder: str,
        autofocus: bool,
        clearable: bool,
        attrs=None,
    ):
        super().__init__(attrs)
        self.placeholder = placeholder
        self.autofocus = autofocus
        self.clearable = clearable

    def _render(self, name, attrs, *, shape: ButtonShape, **component) -> str:
        input_id = (attrs or {}).get("id", "")
        # Widgets return safe strings, not nodes.
        return render(
            SearchSelect(
                name=name,
                id=input_id,
                placeholder=self.placeholder,
                autofocus=self.autofocus,
                clearable=self.clearable,
                clear_description_id=field_label_id(input_id) if input_id else None,
                # Panel opens through the shared attachMenu engine.
                host_dropdown=True,
                shape=shape,
                **component,
            )
        )

    def value_from_datadict(self, data, files, name):
        return data.get(name)

    def offers_none(self, name: PostedName) -> bool:
        """Whether ``render`` pins a none row."""
        return False

    def render(self, name, value, attrs=None, renderer=None, *, shape="full"):
        raise NotImplementedError


class SearchSelectWidget(_SearchSelectAdapter):
    """A `SearchSelect()` searching a server endpoint."""

    def __init__(
        self,
        *,
        search_url,
        options_resolver,
        create: CreateRow | None = None,
        params=None,
        commit_sole_option=False,
        multi_select=False,
        items_visible=5,
        items_scroll=10,
        prefetch=DEFAULT_PREFETCH,
        always_visible=False,
        placeholder="Search…",
        autofocus=False,
        clearable: bool = True,
        none_label: NoneLabel | None = None,
        attrs=None,
    ):
        super().__init__(
            placeholder=placeholder,
            autofocus=autofocus,
            clearable=clearable,
            attrs=attrs,
        )
        self.none_label = none_label
        self.search_url = search_url
        self.options_resolver = options_resolver
        self.create = create
        self.params = params
        self.commit_sole_option = commit_sole_option
        self.multi_select = multi_select
        self.items_visible = items_visible
        self.items_scroll = items_scroll
        self.prefetch = prefetch
        self.always_visible = always_visible

    @staticmethod
    def _values(value) -> list:
        if value is None:
            return []
        if isinstance(value, (list, tuple)):
            return [v for v in value if v not in (None, "")]
        return [value] if value not in (None, "") else []

    def offers_none(self, name: PostedName) -> bool:
        return bool(self.none_label)

    def render(self, name, value, attrs=None, renderer=None, *, shape="full"):
        if self.none_label and self.is_required:
            raise ValueError(f"{name}: a required field holds no none")
        return self._render(
            name,
            attrs,
            selected=searchselect_selected(self._values(value), self.options_resolver),
            options=None,
            search_url=self.search_url,
            create=self.create,
            params=self.params,
            commit_sole_option=self.commit_sole_option,
            multi_select=self.multi_select,
            items_visible=self.items_visible,
            items_scroll=self.items_scroll,
            prefetch=self.prefetch,
            always_visible=self.always_visible,
            none_label=self.none_label,
            shape=shape,
        )


DEFAULT_CHOICE_PLACEHOLDER = "Choose…"

type ChoiceValue = str  # a posted option value
type ChoiceLabel = str  # e.g. "Playthrough 2"
type LabeledChoice = tuple[ChoiceValue, ChoiceLabel]


class IconPickerWidget(forms.Widget):
    """A `ChoiceField`'s icons as a dropdown grid.

    A choice whose value is empty keeps; it shows `keep_label`.
    """

    component_media: ClassVar[Media] = Media(js=("dist/elements/drop-down.js",))

    def __init__(self, *, label: str = "Icon", attrs=None):
        super().__init__(attrs)
        self.label = label
        self.keep_label = "Keep"
        #: Written by the field.
        self.choices: list[tuple[str, str]] = []

    def render(self, name, value, attrs=None, renderer=None):
        attrs = {**self.attrs, **(attrs or {})}
        choices = [
            IconChoice(str(slug), self.keep_label if not slug else str(label))
            for slug, label in self.choices
        ]
        return str(
            IconPicker(
                name=name,
                label=self.label,
                choices=choices,
                value="" if value is None else str(value),
                id=f"{attrs.get('id') or name}-picker",
            )
        )


class TextSearchSelectWidget(_SearchSelectAdapter):
    """Suggestions, and any typed text."""

    def __init__(
        self,
        *,
        suggestions: Sequence[str] = (),
        placeholder: str = "Search or type…",
        attrs=None,
    ):
        super().__init__(
            placeholder=placeholder, autofocus=False, clearable=True, attrs=attrs
        )
        self.suggestions = tuple(suggestions)

    def value_omitted_from_data(self, data, files, name) -> bool:
        """A cleared box posts nothing, and states empty."""
        return False

    def render(self, name, value, attrs=None, renderer=None, *, shape="full"):
        options = [
            SearchSelectOption(value=text, label=text, data={})
            for text in self.suggestions
        ]
        held = [SearchSelectOption(value=value, label=value, data={})] if value else []
        #: A CharField's max_length arrives as maxlength.
        stated = {**self.attrs, **(attrs or {})}.get("maxlength")
        return self._render(
            name,
            attrs,
            selected=held,
            options=options,
            create=SelectTyped(),
            max_length=None if stated is None else int(stated),
            shape=shape,
        )


def offer_platform_groups(
    field: forms.Field, library: UserLibrary
) -> TextSearchSelectWidget:
    """The field's group picker, offering the library's groups."""
    widget = field.widget
    if isinstance(widget, UnsetWidget):
        widget = widget.widget
    if not isinstance(widget, TextSearchSelectWidget):
        raise TypeError(f"{type(widget).__name__} offers no platform groups")
    widget.suggestions = tuple(platform_groups(library))
    return widget


class ChoiceSearchSelectWidget(_SearchSelectAdapter):
    """A `SearchSelect()` over a field's fixed choices."""

    #: `None` until a `ChoiceField` writes choices.
    choices: _Choices | None = None

    def __init__(
        self,
        *,
        placeholder: str | None = None,
        clearable: bool = True,
        autofocus: bool = False,
        attrs=None,
    ):
        super().__init__(
            placeholder=DEFAULT_CHOICE_PLACEHOLDER
            if placeholder is None
            else placeholder,
            autofocus=autofocus,
            clearable=clearable,
            attrs=attrs,
        )

    def __deepcopy__(self, memo):
        copied = super().__deepcopy__(memo)
        copied.choices = copy.copy(self.choices)
        return copied

    def _fixed_choices(self, name: str) -> list[LabeledChoice]:
        if self.choices is None:
            raise ValueError(
                f"{name}: no choices; build the field with this widget "
                "or call host_choices"
            )
        # Before iterating: iteration runs the queryset.
        if isinstance(self.choices, ModelChoiceIterator):
            raise TypeError(f"{name}: model choices take SearchSelectWidget")
        entries = list(self.choices)
        groups = [key for key, label in entries if isinstance(label, (list, tuple))]
        if groups:
            raise ValueError(f"{name}: grouped choices {groups} are not supported")
        return [(_choice_key(key), str(label)) for key, label in entries]

    def offers_none(self, name: PostedName) -> bool:
        has_empty = any(key == "" for key, _ in self._fixed_choices(name))
        return has_empty and not self.is_required

    def render(self, name, value, attrs=None, renderer=None, *, shape="full"):
        if isinstance(value, (list, tuple)):
            raise TypeError(f"{name}: one value only; multi-select is unsupported")
        choices = self._fixed_choices(name)
        empty = [label for key, label in choices if key == ""]
        options = [
            SearchSelectOption(value=key, label=label, data={})
            for key, label in choices
            if key != ""
        ]
        held = _choice_key(value)
        return self._render(
            name,
            attrs,
            selected=[option for option in options if option["value"] == held],
            options=options,
            none_label=empty[0] if empty and not self.is_required else None,
            shape=shape,
        )


def _choice_key(value: object) -> ChoiceValue:
    """`None` is the empty choice's key."""
    return "" if value is None else str(value)


def host_choices(field: forms.ChoiceField, widget: ChoiceSearchSelectWidget) -> None:
    """Put `widget` on an already built field.

    Django writes `choices` onto the widget at build and on each
    `choices` assignment, but `required` only at build. A widget set
    later has no choices; a later `required` change is not seen.
    """
    if isinstance(field, (forms.ModelChoiceField, forms.MultipleChoiceField)):
        raise TypeError(f"{type(field).__name__} takes no fixed-choice picker")
    field.widget = widget
    widget.choices = normalize_choices(field.choices)
    widget.is_required = field.required


class SearchSelectMultiple(SearchSelectWidget):
    def value_from_datadict(self, data, files, name):
        if hasattr(data, "getlist"):
            return data.getlist(name)
        return data.get(name)


class Keep(Enum):
    """An empty ⊘ field: leave it."""

    KEEP = "keep"


KEEP: Final = Keep.KEEP

#: The wrapper's writable attributes.
_WRAPPER_OWNED = frozenset(
    {
        "widget",
        "none_label",
        "unset",
        "hosted",
        "attrs",
        "is_required",
        "is_localized",
        "choices",
    }
)

#: Input types a ⊘ can empty.
_EMPTYABLE_INPUT_TYPES = frozenset(
    {"text", "search", "email", "url", "tel", "password", "number"}
    | {"date", "time", "datetime-local", "month", "week"}
)

#: How a ⊘ reaches its field.
type UnsetJoin = Literal["picker", "native", "beside"]
#: What the ⊘ checkbox posts.
_UNSET_POSTED = "1"


class UnsetWidget(forms.Widget):
    """A widget joined to a ⊘ stating none."""

    @property
    def component_media(self) -> Media:
        own = Media(js=("dist/elements/unset-field.js",))
        inner = self.widget
        return own + inner.component_media if isinstance(inner, MediaWidget) else own

    def __init__(self, widget: forms.Widget, *, none_label: NoneLabel, attrs=None):
        super().__init__(attrs)
        if isinstance(widget, (SearchSelectMultiple, forms.SelectMultiple)) or getattr(
            widget, "multi_select", False
        ):
            raise TypeError("⊘ joins a single value, not a multi-select")
        if _join_of(widget) is None:
            raise TypeError(f"⊘ does not join {type(widget).__name__}")
        # These rewrite a disabled picker's value.
        if getattr(widget, "params", None) or getattr(
            widget, "commit_sole_option", False
        ):
            raise TypeError("⊘ does not join a picker other fields drive")
        self.widget = widget
        self.none_label = none_label
        #: The form refreshes both from its data.
        self.unset = False
        self.hosted = False

    def __setattr__(self, name: str, value: object) -> None:
        # Inner-widget settings would vanish here.
        if name not in _WRAPPER_OWNED:
            raise AttributeError(f"set {name!r} on the inner widget, `.widget`")
        super().__setattr__(name, value)

    def __deepcopy__(self, memo):
        copied = super().__deepcopy__(memo)
        copied.widget = copy.deepcopy(self.widget, memo)
        return copied

    # A ChoiceField writes its choices here.
    @property
    def choices(self):
        return getattr(self.widget, "choices", None)

    @choices.setter
    def choices(self, value) -> None:
        # Only these read them.
        if isinstance(self.widget, (forms.Select, ChoiceSearchSelectWidget)):
            self.widget.choices = value

    @property
    def needs_multipart_form(self) -> bool:  # type: ignore[override]
        return self.widget.needs_multipart_form

    def id_for_label(self, id_):
        return self.widget.id_for_label(id_)

    def use_required_attribute(self, initial) -> bool:
        return False

    def _require_host(self, name: PostedName) -> None:
        # Elsewhere keep and none clean alike.
        if not self.hosted:
            raise TypeError(f"{name}: ⊘ needs an UnsetFieldsForm")

    def unset_in(self, data, name: PostedName) -> bool:
        """Whether ``data`` states none for ``name``."""
        return data.get(unset_input_name(name)) == _UNSET_POSTED

    def value_from_datadict(self, data, files, name):
        self._require_host(name)
        if self.unset_in(data, name):
            return None
        return self.widget.value_from_datadict(data, files, name)

    def value_omitted_from_data(self, data, files, name) -> bool:
        return unset_input_name(name) not in data and (
            self.widget.value_omitted_from_data(data, files, name)
        )

    def render(self, name, value, attrs=None, renderer=None):
        self._require_host(name)
        inner = self.widget
        # Field attrs (maxlength) land here.
        merged = self.build_attrs(self.attrs, attrs)
        input_id = merged.get("id", "")

        join = _join_of(inner)

        def field(shape: ButtonShape) -> Node:
            if join == "beside":
                return Safe(inner.render(name, value, merged, renderer))
            if isinstance(inner, _SearchSelectAdapter):
                return Safe(inner.render(name, value, merged, renderer, shape=shape))
            shaped = native_control_class(inner, shape)
            own = inner.attrs.get("class", "")
            return Safe(
                inner.render(
                    name,
                    value,
                    {**merged, "class": f"{own} {shaped}".strip()},
                    renderer,
                )
            )

        return render(
            UnsetField(
                name=name,
                none_label=self.none_label,
                field=field,
                unset=self.unset,
                describedby=field_label_id(input_id) or None,
                layout="beside" if join == "beside" else "joined",
            )
        )


def _join_of(widget: forms.Widget) -> UnsetJoin | None:
    """None: a ⊘ cannot reach it."""
    if getattr(widget, "draws_own_box", False):
        return "beside"
    if isinstance(widget, _SearchSelectAdapter):
        return "picker"
    if isinstance(widget, forms.Textarea):
        return "native"
    if isinstance(widget, forms.Select):
        # Its empty is a state.
        if isinstance(widget, forms.NullBooleanSelect):
            return None
        return "native"
    if isinstance(widget, forms.widgets.Input):
        return "native" if widget.input_type in _EMPTYABLE_INPUT_TYPES else None
    return None


def _require_empty_cleans_empty(name: str, field: forms.Field) -> None:
    """Else keep and a value clean alike."""
    inner = cast(UnsetWidget, field.widget).widget
    # None: pressed. The empty post: kept.
    for empty_input in (
        None,
        inner.value_from_datadict(QueryDict(), MultiValueDict(), name),
    ):
        try:
            empty = field.clean(empty_input)
        except forms.ValidationError as refused:
            raise ValueError(
                f"{name}: an empty field is refused, so ⊘ cannot keep"
            ) from refused
        except Exception as broken:
            raise TypeError(
                f"{name}: clean({empty_input!r}) raised; ⊘ needs empty to clean empty"
            ) from broken
        if empty not in field.empty_values:
            raise ValueError(
                f"{name}: an empty field cleans to {empty!r}, so ⊘ cannot keep"
            )


def _param_fields(widget: forms.Widget) -> set[str]:
    """Sibling fields a picker's params read."""
    params = getattr(widget, "params", None) or {}
    return {
        source["field"]
        for source in params.values()
        if isinstance(source, dict) and "field" in source
    }


class UnsetFieldsForm(forms.Form):
    """Cleans ⊘ fields: value, empty (none), ``KEEP``."""

    def __getitem__(self, name: str) -> forms.BoundField:
        self._unset_widgets()
        return super().__getitem__(name)

    def _unset_widgets(self) -> list[tuple[str, UnsetWidget]]:
        """Checked, and synced with the data."""
        # Per call: fields may arrive late.
        found = []
        for name, field in self.fields.items():
            widget = field.widget
            if not isinstance(widget, UnsetWidget):
                continue
            if field.required:
                raise ValueError(f"{name}: an empty required field cannot keep")
            _require_empty_cleans_empty(name, field)
            inner = widget.widget
            inner.is_required = False
            inner.is_localized = widget.is_localized
            if isinstance(inner, _SearchSelectAdapter) and inner.offers_none(name):
                raise ValueError(f"{name}: ⊘ states none; the picker offers none too")
            widget.hosted = True
            widget.unset = self.is_bound and widget.unset_in(
                self.data, self.add_prefix(name)
            )
            found.append((name, widget))
        # Params may name the posted field.
        unset_names = {name for name, _ in found} | {
            self.add_prefix(name) for name, _ in found
        }
        for name, field in self.fields.items():
            # A pressed field hides its value.
            if driven := _param_fields(field.widget) & unset_names:
                raise ValueError(f"{name}: its params read ⊘ field {min(driven)!r}")
        return found

    def clean(self) -> dict[str, Any]:
        cleaned = super().clean() or {}
        for name, widget in self._unset_widgets():
            if name not in cleaned or widget.unset:
                continue
            if cleaned[name] in self.fields[name].empty_values:
                cleaned[name] = KEEP
        return cleaned


class DatePickerWidget(forms.Widget):
    """Thin Django adapter that renders a `DatePicker()` component in place
    of a native `<input type="date">` (issue #485), so the account's
    DATETIME_FORMAT preference controls the visible segment order. Submits
    and binds canonical ISO ``YYYY-MM-DD`` through the hidden input
    unchanged — Django's default `DateField` parsing is untouched."""

    #: A ⊘ stands beside it.
    draws_own_box: ClassVar[bool] = True
    component_media: ClassVar[Media] = Media(
        js=("dist/elements/date-picker.js", "dist/elements/drop-down.js")
    )

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

    #: A ⊘ stands beside it.
    draws_own_box: ClassVar[bool] = True
    component_media: ClassVar[Media] = Media(js=("dist/elements/temporal-field.js",))

    def __init__(
        self,
        *,
        presentation: DateTimePresentation,
        label: str,
        attrs=None,
        copy_source: TemporalCopySource | None = None,
    ) -> None:
        super().__init__(attrs)
        self.presentation = presentation
        self.label = label
        self.copy_source = copy_source

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
                copy_source=self.copy_source,
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
        self,
        *,
        presentation: DateTimePresentation,
        label: str = "Date",
        copy_source: TemporalCopySource | None = None,
        **kwargs,
    ) -> None:
        kwargs.setdefault(
            "widget",
            TemporalWidget(
                presentation=presentation, label=label, copy_source=copy_source
            ),
        )
        kwargs.setdefault("required", False)
        super().__init__(label=label, **kwargs)

    def to_python(self, value) -> TemporalValue | None:
        try:
            built = temporal_draft_from_data(self._data(value)).build()
        except TemporalValueParseError as error:
            raise forms.ValidationError(
                self.parse_error_message(error), code=error.code
            ) from error
        return None if built.is_unknown else built

    def parse_error_message(self, error: TemporalValueParseError) -> str:
        """What a person reads for a refused value."""
        return str(error)

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

    #: A ⊘ stands beside it.
    draws_own_box: ClassVar[bool] = True
    component_media: ClassVar[Media] = Media(
        js=("dist/elements/date-time-field.js", "dist/elements/drop-down.js")
    )

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

    component_media: ClassVar[Media] = Media(
        js=(
            "dist/elements/time-zone-row.js",
            "dist/elements/search-select.js",
            "dist/elements/drop-down.js",
        )
    )

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

#: What the picker reads: option-shaped rows of one game's runs.
PLAYTHROUGH_SEARCH_URL: Final = "/api/playthrough/search"

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


class PlaythroughSelectWidget(SearchSelectWidget):
    """The run picker: a combobox that makes the run a person named.

    A `SearchSelect` whose `params` name the game field, so the
    search narrows on the game the form holds and a creation names
    the same one, and a change to that field searches again.

    The field row is never hidden. A game holding one run is the
    very game this picker is for: nobody types a second run's name
    into a hidden control.
    """

    def __init__(self, *, game_field: str, clearable: bool = True, attrs=None):
        super().__init__(
            search_url=PLAYTHROUGH_SEARCH_URL,
            options_resolver=run_options,
            create=PostCreate(PLAYTHROUGH_CREATE_URL),
            params={"game_id": {"field": game_field}},
            #: Required field: a submit with no pick posts a run.
            commit_sole_option=True,
            prefetch=DEFAULT_PREFETCH,
            clearable=clearable,
            attrs=attrs,
        )


def _run_choices(library: UserLibrary, game: Game | None) -> list[LabeledChoice]:
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
        runs.widget.options_resolver = partial(run_options, library=library)
        cast(
            forms.ModelChoiceField, self.fields["device"]
        ).queryset = Device.objects.for_library(library).order_by("name")
        self.fields["device"].widget.options_resolver = partial(
            device_options, library=library
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
        widget=PlaythroughSelectWidget(game_field="game"),
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
            search_url=DEVICE_SEARCH_URL,
            options_resolver=device_options,
            create=PostCreate(DEVICE_CREATE_URL),
            none_label="No device",
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


_CHOICE_LIST_CLASS = "flex flex-col gap-2"
_NUMBER_CLASS = (
    "w-24 px-3 min-h-control rounded-base border border-default-medium "
    f"bg-neutral-secondary-medium text-heading {_DISABLED_CONTROL}"
)

type OptionBuilder = Callable[..., Node]


class _ChoiceListWidget(forms.widgets.ChoiceWidget):
    """One primitive per choice, in a group."""

    option: ClassVar[OptionBuilder]

    def id_for_label(self, id_, index=None):
        #: The group takes the label.
        return id_

    def render(self, name, value, attrs=None, renderer=None):
        final_attrs = self.build_attrs(self.attrs, attrs)
        group_id = str(final_attrs.get("id", ""))
        selected = set(self.format_value(value))
        options = [
            type(self).option(
                name=name,
                value=str(choice),
                label=str(label),
                checked=str(choice) in selected,
            )
            for choice, label in self.choices
        ]
        return render(
            Fieldset(
                id_=group_id or None,
                aria_labelledby=field_label_id(group_id) or None,
                class_=_CHOICE_LIST_CLASS,
            )[*options]
        )


class CheckboxListWidget(_ChoiceListWidget):
    """Checkboxes, any number checked."""

    option = staticmethod(Checkbox)
    allow_multiple_selected = True

    def value_omitted_from_data(self, data, files, name) -> bool:
        #: Nothing checked posts nothing.
        return False


class RadioListWidget(_ChoiceListWidget):
    """Radio buttons, one checked."""

    option = staticmethod(Radio)


type DurationSuffix = str  # e.g. "hours"


class DurationPart(NamedTuple):
    """One number input of a duration."""

    suffix: DurationSuffix
    label: str
    maximum: int


#: A cap stops timedelta overflowing.
DURATION_PARTS: Final = (
    DurationPart("hours", "Hours", 99_999),
    DurationPart("minutes", "Minutes", 59),
)


def whole_minutes(duration: datetime.timedelta) -> datetime.timedelta:
    """The duration without its seconds."""
    return datetime.timedelta(minutes=int(duration.total_seconds()) // 60)


class HoursMinutesWidget(forms.MultiWidget):
    """Two number inputs, each with its own label."""

    def __init__(self, attrs=None):
        super().__init__(
            {part.suffix: forms.NumberInput() for part in DURATION_PARTS}, attrs
        )

    def decompress(self, value):
        if not isinstance(value, datetime.timedelta):
            return [None, None]
        minutes = int(whole_minutes(value).total_seconds()) // 60
        return [minutes // 60, minutes % 60]

    def id_for_label(self, id_):
        return id_

    def render(self, name, value, attrs=None, renderer=None):
        final_attrs = self.build_attrs(self.attrs, attrs)
        group_id = str(final_attrs.get("id", ""))
        values = value if isinstance(value, list) else self.decompress(value)
        parts = [
            Label(class_="flex items-center gap-2 text-type-body text-heading")[
                Input(
                    type="number",
                    name=f"{name}_{part.suffix}",
                    id_=f"{group_id}_{part.suffix}" if group_id else None,
                    value="" if posted in (None, "") else str(posted),
                    min="0",
                    max=str(part.maximum),
                    class_=_NUMBER_CLASS,
                ),
                part.label,
            ]
            for part, posted in zip(DURATION_PARTS, values, strict=True)
        ]
        return render(
            Fieldset(
                id_=group_id or None,
                aria_labelledby=field_label_id(group_id) or None,
                class_="flex flex-wrap items-center gap-4",
            )[*parts]
        )


class HoursMinutesField(forms.MultiValueField):
    """Whole hours and minutes; blank is zero."""

    widget = HoursMinutesWidget

    def __init__(self, **kwargs):
        super().__init__(
            fields=tuple(
                forms.IntegerField(required=False, min_value=0, max_value=part.maximum)
                for part in DURATION_PARTS
            ),
            require_all_fields=False,
            required=False,
            **kwargs,
        )

    def compress(self, data_list) -> datetime.timedelta:
        hours, minutes = (data_list or [None, None])[:2]
        return datetime.timedelta(hours=hours or 0, minutes=minutes or 0)


class HistoricalWhenField(TemporalFormField):
    """A when, refused in the command's words."""

    def parse_error_message(self, error: TemporalValueParseError) -> str:
        return when_sentence(error)


#: Externally measured is an importer's.
_STATED_PROVENANCES = (
    HistoricalPlaytimeProvenance.ESTIMATED,
    HistoricalPlaytimeProvenance.MANUALLY_ENTERED,
)


class HistoricalPlaytimeForm(PrimitiveWidgetsMixin, forms.Form):
    """One record at one game.

    Narrows the offered provenances and devices; every other rule is
    the command's, so a refusal reads in its words.
    """

    playthroughs = forms.ModelMultipleChoiceField(
        queryset=Playthrough.objects.none(),
        widget=CheckboxListWidget,
        label="Playthroughs",
    )
    duration = HoursMinutesField(label="Duration")
    provenance = forms.ChoiceField(widget=RadioListWidget, label="Provenance")
    device = forms.ModelChoiceField(
        queryset=Device.objects.none(),
        required=False,
        widget=SearchSelectWidget(
            search_url=DEVICE_SEARCH_URL,
            options_resolver=device_options,
            create=PostCreate(DEVICE_CREATE_URL),
            none_label="No device",
        ),
    )
    emulated = forms.BooleanField(required=False)
    note = forms.CharField(required=False, widget=forms.Textarea)
    #: Rendered once per page; a repeated submit replays.
    submission = forms.UUIDField(widget=forms.HiddenInput)

    def __init__(
        self,
        *args,
        library: UserLibrary,
        game: Game,
        presentation: DateTimePresentation,
        record: HistoricalPlaytime | None = None,
        session: PlayerSession | None = None,
        provenance: HistoricalPlaytimeProvenance = (
            HistoricalPlaytimeProvenance.MANUALLY_ENTERED
        ),
        **kwargs,
    ):
        if record is not None and session is not None:
            raise TypeError(
                "A historical playtime form seeds from a record or from a "
                "session, never from both."
            )
        initial = dict(kwargs.pop("initial", None) or {})
        #: The seed overwrites a caller's initial.
        #: A caller passing `playthroughs` as an initial loses it to
        #: the game's latest run, quietly; a page opening on another
        #: run states `record=` or `session=` instead.
        initial.update(_record_initial(library, game, record, session, provenance))
        super().__init__(*args, initial=initial, **kwargs)
        self.record: HistoricalPlaytime | None = record
        self.session: PlayerSession | None = session
        if record is not None:
            #: A restatement repeats harmlessly.
            del self.fields["submission"]
        #: Needs the presentation, so built here.
        self.fields["when"] = HistoricalWhenField(
            presentation=presentation, label="When"
        )
        self.order_fields(["playthroughs", "duration", "when", "provenance", "device"])
        runs = cast(forms.ModelMultipleChoiceField, self.fields["playthroughs"])
        #: Library-wide; the command refuses the rest.
        runs.queryset = Playthrough.objects.filter(library=library)
        runs.choices = _run_choices(library, game)
        provenances = list(_STATED_PROVENANCES)
        if (
            record is not None
            and record.provenance == HistoricalPlaytimeProvenance.EXTERNALLY_MEASURED
        ):
            provenances.append(HistoricalPlaytimeProvenance.EXTERNALLY_MEASURED)
        cast(forms.ChoiceField, self.fields["provenance"]).choices = [
            (choice.value, choice.label) for choice in provenances
        ]
        devices = Device.objects.for_library(library)
        held = record if record is not None else session
        if held is not None and held.device_id is not None:
            #: A held device stays, removed or not.
            devices = devices | Device.objects.filter(
                library=library, pk=held.device_id
            )
        device_field = cast(forms.ModelChoiceField, self.fields["device"])
        device_field.queryset = devices.order_by("name")
        device_field.widget.options_resolver = partial(
            _held_device_options, devices=devices
        )

    def clean_note(self) -> str:
        return self.cleaned_data["note"].replace("\r\n", "\n")

    def _every_duration_part_posted(self) -> bool:
        return all(
            self.data.get(f"{self.add_prefix('duration')}_{part.suffix}", "") != ""
            for part in DURATION_PARTS
        )

    def submission_key(self, act: str = "record") -> IdempotencyKey:
        """The submit key; `act` names the command."""
        return f"historical-playtime-{act}-{self.cleaned_data['submission']}"

    def statement(self) -> HistoricalPlaytimeStatement:
        """What the valid form states."""
        cleaned = self.cleaned_data
        duration: datetime.timedelta = cleaned["duration"]
        held = None
        if self.record is not None:
            held = self.record.duration
        elif self.session is not None:
            held = self.session.effective_duration
        if (
            held is not None
            and self._every_duration_part_posted()
            and duration == whole_minutes(held)
        ):
            #: Inputs show whole minutes; keep stored seconds.
            duration = held
        when: TemporalValue | None = cleaned["when"]
        device: Device | None = cleaned["device"]
        return HistoricalPlaytimeStatement(
            duration=duration,
            when=None if when is None else when.canonical,
            provenance=HistoricalPlaytimeProvenance(cleaned["provenance"]),
            playthrough_ids=tuple(run.pk for run in cleaned["playthroughs"]),
            device_id=None if device is None else device.pk,
            emulated=cleaned["emulated"],
            note=cleaned["note"],
        )


def _parsed_ids(values) -> list[uuid.UUID]:
    """The values that are ids; the field reports the rest."""
    parsed = []
    for value in values:
        try:
            parsed.append(
                value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
            )
        except ValueError:
            continue
    return parsed


def _held_device_options(
    values, *, devices: QuerySet[Device]
) -> list[SearchSelectOption]:
    return [
        {"value": device.id, "label": device.name, "data": {}}
        for device in devices.filter(pk__in=_parsed_ids(values))
    ]


def _record_initial(
    library: UserLibrary,
    game: Game,
    record: HistoricalPlaytime | None,
    session: PlayerSession | None = None,
    provenance: HistoricalPlaytimeProvenance = (
        HistoricalPlaytimeProvenance.MANUALLY_ENTERED
    ),
) -> dict[str, Any]:
    """What Add, Edit and a reclassification seed."""
    if session is not None:
        stated = statement_from_session(session, provenance)
        return {
            "playthroughs": [str(run_id) for run_id in stated.playthrough_ids],
            "duration": stated.duration,
            "when": TemporalValue.parse(stated.when),
            "provenance": stated.provenance.value,
            "device": stated.device_id,
            "emulated": stated.emulated,
            "note": stated.note,
            "submission": uuid.uuid7(),
        }
    if record is None:
        run = latest_ordinary_run(library, game)
        return {
            "playthroughs": [] if run is None else [str(run.pk)],
            "provenance": HistoricalPlaytimeProvenance.ESTIMATED.value,
            "submission": uuid.uuid7(),
        }
    return {
        "playthroughs": [
            str(run_id)
            for run_id in record.runs.values_list("playthrough_id", flat=True)
        ],
        "duration": record.duration,
        "when": record.when,
        "provenance": record.provenance,
        "device": record.device_id,
        "emulated": record.emulated,
        "note": record.note,
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
        # A new row already carries a key, so adding is what tells the two
        # apart. The model default renders as a literal "0", and typing at
        # the autofocused caret would append to it.
        if self.instance._state.adding:
            self.initial["price"] = None
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
            search_url="/api/platforms/search",
            options_resolver=_platform_options,
            create=PostCreate(PLATFORM_CREATE_URL),
            none_label="Unspecified",
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
    icon = forms.ChoiceField(
        required=False, choices=(), widget=IconPickerWidget(label="Icon")
    )

    def __init__(self, *args, library: UserLibrary, **kwargs):
        super().__init__(*args, **kwargs)
        self.library = library
        self.instance.library = library
        offer_platform_groups(self.fields["group"], library)
        field = cast(forms.ChoiceField, self.fields["icon"])
        field.choices = list(PLATFORM_ICONS.items())
        field.initial = self.instance.icon or UNSPECIFIED_ICON

    def clean_icon(self) -> str:
        """No icon stated is Unspecified."""
        return self.cleaned_data["icon"] or UNSPECIFIED_ICON

    class Meta:
        model = Platform
        fields = (
            "name",
            "icon",
            "group",
        )
        widgets: ClassVar[dict[str, forms.Widget]] = {
            "name": autofocus_input_widget,
            "group": TextSearchSelectWidget(),
        }


class DeviceForm(PrimitiveWidgetsMixin, forms.Form):
    """One device, stated as commands."""

    name = forms.CharField(
        max_length=Device._meta.get_field("name").max_length,
        widget=autofocus_input_widget,
    )
    type = forms.ChoiceField(choices=Device.DEVICE_TYPES, initial=Device.UNKNOWN)
    #: One key per page; resubmits replay.
    submission = forms.UUIDField(widget=forms.HiddenInput, initial=uuid.uuid7)

    def __init__(
        self,
        *args,
        library: UserLibrary,
        device: Device | None = None,
        **kwargs,
    ):
        if device is not None:
            kwargs.setdefault("initial", {"name": device.name, "type": device.type})
        super().__init__(*args, **kwargs)
        self.library = library
        self.device = device
        if device is not None:
            #: A description repeats harmlessly.
            del self.fields["submission"]

    def submission_key(self) -> IdempotencyKey:
        """The creation's key."""
        return f"device-create-{self.cleaned_data['submission']}"


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
