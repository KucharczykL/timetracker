"""Stash-style filter bars, built from FilterSelect widgets."""

from typing import NamedTuple

from django.db import models

from common.components.core import BaseComponent, Element, Node, Safe
from common.components.custom_elements import _FilterBarElement, _RangeSlider
from common.components.date_range_picker import DateRangePicker
from common.components.primitives import Checkbox, Div, Input, Label, Radio, Span
from common.components.search_select import (
    DEFAULT_PREFETCH,
    FilterSelect,
    LabeledOption,
)


class FilterChoice(NamedTuple):
    """Parsed include/exclude/modifier state of a filter field from filter JSON.

    ``selected`` and ``excluded`` are lists of ``(value, label)`` pairs.  For
    model-backed fields the label is embedded in the filter JSON (Stash-style);
    for enum fields the label is resolved from the fixed option list.
    """

    selected: list[LabeledOption]
    excluded: list[LabeledOption]
    modifier: str


class RangeValues(NamedTuple):
    """A (min, max) string pair parsed from a range filter criterion."""

    min: str
    max: str


_FILTER_LABEL_CLASS = "text-xs font-medium text-body uppercase tracking-wide"


_FILTER_CHECKBOX_CLASS = (
    "rounded border-default-medium bg-neutral-secondary-medium "
    "text-brand focus:ring-brand"
)


_FILTER_RADIO_CLASS = (
    "rounded-full border-default-medium bg-neutral-secondary-medium "
    "text-brand focus:ring-brand"
)


_FILTER_GRID_CLASS = "grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-4"


def _filter_parse(filter_json: str) -> dict:
    if not filter_json:
        return {}
    try:
        import json

        loaded = json.loads(filter_json)
        return loaded if isinstance(loaded, dict) else {}
    except (ValueError, TypeError):
        return {}


def _extract_labeled(items: list[dict]) -> list[LabeledOption]:
    """Convert a list of ``{id, label}`` dicts to ``(value, label)`` pairs."""
    return [(str(item["id"]), str(item["label"])) for item in items]


def _filter_get_choice(existing: dict, field: str) -> FilterChoice:
    raw = existing.get(field, {})
    if not isinstance(raw, dict):
        return FilterChoice([], [], "")
    return FilterChoice(
        selected=_extract_labeled(raw.get("value") or []),
        excluded=_extract_labeled(raw.get("excludes") or []),
        modifier=raw.get("modifier") or "",
    )


def _parse_range(existing: dict, key: str) -> RangeValues:
    """Extract (min, max) from a range filter criterion, defaulting to ("", "")."""
    field = existing.get(key, {})
    if not isinstance(field, dict):
        return RangeValues("", "")
    return RangeValues(str(field.get("value", "")), str(field.get("value2", "")))


def _parse_bool(existing: dict, key: str) -> bool:
    """Extract a boolean value from a filter criterion."""
    field = existing.get(key, {})
    if not isinstance(field, dict):
        return False
    return bool(field.get("value", False))


def _parse_bool_nullable(existing: dict, key: str) -> bool | None:
    """Extract a nullable boolean value from a filter criterion."""
    if key not in existing:
        return None
    field = existing[key]
    if not isinstance(field, dict):
        return None
    val = field.get("value")
    if val is None:
        return None
    if isinstance(val, str):
        if val.lower() in ("true", "1", "yes"):
            return True
        if val.lower() in ("false", "0", "no"):
            return False
    return bool(val)


# ── FilterSelect adapters ────────────────────────────────────────────────────
# Each list filter is a FilterSelect. Enum fields pre-render their small, fixed
# option set; model-backed fields fetch from a search endpoint on demand, with
# labels embedded in the filter JSON so pills render without a DB round-trip.

# Presence modifiers drive the pinned (Any)/(None) pseudo-options. They are
# mutually exclusive with value pills (selecting one clears the value set).
# Must match JS PRESENCE_MODIFIERS in search_select.js.
_PRESENCE_MODIFIERS = frozenset({"NOT_NULL", "IS_NULL"})

# M2M-only modifiers surfaced as additional pseudo-options in the dropdown.
# "any" (INCLUDES) is the implicit default when neither a presence nor an
# M2M modifier is set — no dedicated row needed.  "none" (EXCLUDES) is
# redundant with individual exclude (✗) pills.  Only INCLUDES_ALL and
# INCLUDES_ONLY can't be expressed through pills alone, so they are the
# only M2M modifiers with explicit UI.
_M2M_MODIFIERS: list[LabeledOption] = [
    ("INCLUDES_ALL", "(All)"),
    ("INCLUDES_ONLY", "(Only)"),
]


def _modifier_options(
    nullable: bool, m2m_modifiers: list[LabeledOption] | None = None
) -> list[LabeledOption]:
    """Pinned pseudo-options rendered at the top of the dropdown.

    Always includes ``(Any)`` (NOT_NULL); adds ``(None)`` (IS_NULL) when
    ``nullable`` is True.  When ``m2m_modifiers`` is given (M2M fields only),
    appends those rows (e.g. ``(All)`` / ``(Only)``)."""
    options: list[LabeledOption] = [("NOT_NULL", "(Any)")]
    if nullable:
        options.append(("IS_NULL", "(None)"))
    if m2m_modifiers:
        options.extend(m2m_modifiers)
    return options


def _split_modifier(modifier: str, has_m2m: bool = False) -> str:
    """Return the modifier value to surface as the modifier pill.

    Presence modifiers (NOT_NULL / IS_NULL) are always surfaced.  Non-presence
    modifiers (INCLUDES / INCLUDES_ALL / INCLUDES_ONLY) only need a pill on M2M
    fields — otherwise the modifier is just the implicit default.
    """
    if modifier in _PRESENCE_MODIFIERS or not has_m2m:
        return modifier
    if modifier:
        return modifier
    return ""


def _enum_filter(field_name: str, options, choice: FilterChoice, *, nullable) -> Node:
    """A FilterSelect over a small, fully pre-rendered option set (enum field).

    Enum fields are single-valued, so no M2M modifiers (all/only are
    meaningless); only the presence modifier is surfaced.
    """
    options_str = [(str(value), label) for value, label in options]
    included = [
        (value, _find_label(options_str, value)) for value, _label in choice.selected
    ]
    excluded = [
        (value, _find_label(options_str, value)) for value, _label in choice.excluded
    ]
    modifier = _split_modifier(choice.modifier)
    return FilterSelect(
        field_name=field_name,
        options=options_str,
        included=included,
        excluded=excluded,
        modifier=modifier,
        modifier_options=_modifier_options(nullable),
    )


def _model_filter(
    field_name: str,
    choice: FilterChoice,
    *,
    search_url,
    nullable,
    m2m_modifiers: list[LabeledOption] | None = None,
) -> Node:
    """A FilterSelect backed by a search endpoint.

    Labels are embedded in the filter JSON (Stash-style), so pills render
    directly from ``choice`` with no DB round-trip. Pass ``m2m_modifiers`` for
    many-to-many fields to surface ``(All)`` / ``(Only)`` pseudo-options in the
    dropdown alongside the presence options.
    """
    modifier = _split_modifier(choice.modifier, has_m2m=bool(m2m_modifiers))
    return FilterSelect(
        field_name=field_name,
        included=[(value, label or value) for value, label in choice.selected],
        excluded=[(value, label or value) for value, label in choice.excluded],
        modifier=modifier,
        modifier_options=_modifier_options(nullable, m2m_modifiers),
        search_url=search_url,
        prefetch=DEFAULT_PREFETCH,
    )


def _filter_mins_to_hrs(val) -> str:
    if val is None or val == "" or val == 0:
        return ""
    try:
        mins = int(val)
    except (TypeError, ValueError):
        return ""
    if mins == 0:
        return ""
    hrs = mins / 60
    return str(int(hrs)) if hrs == int(hrs) else f"{hrs:.1f}"


def _widget_id(widget) -> str:
    """Best-effort id of a widget node, for the field label's ``for`` target.

    Widgets are nodes carrying ``.attributes``, so the id is now reachable
    directly (the old free ``Component`` string couldn't expose it).
    """
    for name, value in getattr(widget, "attributes", []):
        if name == "id":
            return str(value)
    return ""


def _filter_field(label: str, widget) -> Node:
    """A labelled filter field: ``<div><label>…</label>{widget}</div>``.

    The label's ``for`` points at the widget's own id when it has one;
    composite widgets without a single root id simply omit ``for``.
    """
    label_attributes = [("class", _FILTER_LABEL_CLASS)]
    widget_id = _widget_id(widget)
    if widget_id:
        label_attributes.append(("for", widget_id))
    return Div(
        attributes=[("class", "flex flex-col gap-1")],
        children=[
            Label(attributes=label_attributes, children=[label]),
            widget,
        ],
    )


def _filter_checkbox(name: str, label: str, checked: bool) -> Node:
    """Thin adapter mapping legacy checkbox filters to the generalized Checkbox primitive."""
    return Checkbox(name=name, label=label, checked=checked)


def _filter_boolean_radio(name: str, label: str, value: bool | None) -> Node:
    """Renders a filter-specific boolean radio button group with 'True' and 'False' options."""
    return Div(
        attributes=[("class", "flex flex-col gap-1")],
        children=[
            Span(
                attributes=[("class", _FILTER_LABEL_CLASS)],
                children=[label],
            ),
            Div(
                attributes=[("class", "flex items-center gap-4 h-9")],
                children=[
                    Radio(name=name, label="True", checked=value is True, value="true"),
                    Radio(
                        name=name, label="False", checked=value is False, value="false"
                    ),
                ],
            ),
        ],
    )


# SVG icons for the mode toggle (shared across all RangeSliders)
_RANGE_ICON_SVG = (
    '<svg width="16" height="10" viewBox="0 0 16 10">'
    '<line x1="3" y1="5" x2="13" y2="5" stroke="currentColor" stroke-width="1.5"/>'
    '<circle cx="3" cy="5" r="3" fill="currentColor"/>'
    '<circle cx="13" cy="5" r="3" fill="currentColor"/>'
    "</svg>"
)

_POINT_ICON_SVG = (
    '<svg width="16" height="10" viewBox="0 0 16 10">'
    '<circle cx="8" cy="5" r="3" fill="currentColor"/>'
    "</svg>"
)

_RANGE_SLIDER_INPUT_CLASS = (
    "w-24 rounded-base border border-default-medium bg-neutral-secondary-medium "
    "text-sm text-heading p-1.5 focus:ring-brand focus:border-brand"
)


def RangeSlider(
    *,
    label: str,
    input_name_prefix: str,
    min_value: str = "",
    max_value: str = "",
    range_min: int,
    range_max: int,
    step: str = "1",
    min_placeholder: str = "",
    max_placeholder: str = "",
) -> Node:
    """A labelled range slider with number inputs and range/point mode toggle.

    Renders a label row (label, two number inputs, toggle button) and a slider
    row (track with one or two custom draggable handles). Defaults to range mode
    (two handles). If min_value and max_value are both set and equal, starts in
    point mode (single handle). The toggle switches between modes.
    """
    min_input_id = f"{input_name_prefix}-min"
    max_input_id = f"{input_name_prefix}-max"
    point_mode = bool(min_value and max_value and min_value == max_value)
    initial_mode = "point" if point_mode else "range"

    return _RangeSlider(
        min=range_min,
        max=range_max,
        step=int(step),
        mode=initial_mode,
        class_="mb-4 block",
    )[
        # ── Label row ──
        Div(
            attributes=[("class", "flex items-center gap-2 mb-1")],
            children=[
                # The field label is rendered by the _filter_field wrapper.
                # This composite widget has no single labelable root, so the
                # label carries no `for` (the two inputs are named below).
                Input(
                    attributes=[
                        ("type", "number"),
                        ("name", min_input_id),
                        ("id", min_input_id),
                        ("value", min_value),
                        ("placeholder", min_placeholder),
                        (
                            "class",
                            f"{_RANGE_SLIDER_INPUT_CLASS}"
                            + (" hidden" if point_mode else ""),
                        ),
                    ],
                ),
                Span(
                    attributes=[
                        (
                            "class",
                            "range-dash text-body text-sm"
                            + (" hidden" if point_mode else ""),
                        ),
                    ],
                    children=["–"],
                ),
                Input(
                    attributes=[
                        ("type", "number"),
                        ("name", max_input_id),
                        ("id", max_input_id),
                        ("value", max_value),
                        ("placeholder", max_placeholder),
                        ("class", _RANGE_SLIDER_INPUT_CLASS),
                    ],
                ),
                Element(
                    "button",
                    attributes=[
                        ("type", "button"),
                        (
                            "class",
                            "range-mode-toggle p-1 text-body hover:text-heading "
                            "rounded cursor-pointer shrink-0",
                        ),
                        (
                            "title",
                            "Toggle between range and single value",
                        ),
                        (
                            "aria-label",
                            "Toggle between range and single value",
                        ),
                    ],
                    children=[
                        Span(
                            attributes=[
                                (
                                    "class",
                                    "range-mode-icon-range"
                                    + (" hidden" if point_mode else ""),
                                ),
                            ],
                            children=[Safe(_RANGE_ICON_SVG)],
                        ),
                        Span(
                            attributes=[
                                (
                                    "class",
                                    "range-mode-icon-point"
                                    + ("" if point_mode else " hidden"),
                                ),
                            ],
                            children=[Safe(_POINT_ICON_SVG)],
                        ),
                    ],
                ),
            ],
        ),
        # ── Track row ──
        Div(
            attributes=[
                ("class", "relative h-10 w-5/6 select-none mt-1"),
                ("data-range-track", ""),
            ],
            children=[
                Div(
                    attributes=[
                        (
                            "class",
                            "absolute top-1/2 -translate-y-1/2 w-full h-2 "
                            "rounded-full bg-neutral-quaternary",
                        ),
                    ],
                ),
                Div(
                    attributes=[
                        (
                            "class",
                            "range-track-fill absolute top-1/2 -translate-y-1/2 "
                            "h-2 bg-brand rounded-full",
                        ),
                        ("style", "left:0;width:100%"),
                    ],
                ),
                # Min handle (hidden in point mode via JS)
                Div(
                    attributes=[
                        (
                            "class",
                            "range-handle range-handle-min absolute top-1/2 "
                            "-translate-y-1/2 w-5 h-5 bg-brand rounded-full "
                            "border-2 border-white shadow cursor-pointer "
                            "hover:scale-110 transition-transform",
                        ),
                        ("data-target", min_input_id),
                        (
                            "style",
                            "left:0" + (";display:none" if point_mode else ""),
                        ),
                    ],
                ),
                # Max handle
                Div(
                    attributes=[
                        (
                            "class",
                            "range-handle range-handle-max absolute top-1/2 "
                            "-translate-y-1/2 w-5 h-5 bg-brand rounded-full "
                            "border-2 border-white shadow cursor-pointer "
                            "hover:scale-110 transition-transform",
                        ),
                        ("data-target", max_input_id),
                        ("style", "left:100%"),
                    ],
                ),
            ],
        ),
    ]


_DATE_RANGE_INPUT_CLASS = (
    "w-full rounded-base border border-default-medium bg-neutral-secondary-medium "
    "text-sm text-heading p-1.5 focus:ring-brand focus:border-brand"
)


def DateRangeFilter(
    *,
    label: str,
    input_name_prefix: str,
    min_value: str = "",
    max_value: str = "",
    min_placeholder: str = "From",
    max_placeholder: str = "To",
) -> Node:
    """A pair of ``<input type="date">`` elements representing a date range.

    Mirrors ``RangeSlider`` in shape (two inputs named ``{prefix}-min`` and
    ``{prefix}-max``) but without a slider track — the browser's native date
    picker is the UI. Serialized client-side into a ``DateCriterion`` with
    ``BETWEEN`` / ``GREATER_THAN`` / ``LESS_THAN`` depending on which bound(s)
    the user filled.
    """
    min_input_id = f"{input_name_prefix}-min"
    max_input_id = f"{input_name_prefix}-max"
    return Div(
        attributes=[("class", "date-range-block mb-4")],
        children=[
            Div(
                attributes=[("class", "flex items-center gap-2")],
                children=[
                    Input(
                        attributes=[
                            ("type", "date"),
                            ("name", min_input_id),
                            ("id", min_input_id),
                            ("value", min_value),
                            ("placeholder", min_placeholder),
                            ("aria-label", f"{label} from"),
                            ("class", _DATE_RANGE_INPUT_CLASS),
                        ],
                    ),
                    Span(
                        attributes=[("class", "text-body text-sm")],
                        children=["–"],
                    ),
                    Input(
                        attributes=[
                            ("type", "date"),
                            ("name", max_input_id),
                            ("id", max_input_id),
                            ("value", max_value),
                            ("placeholder", max_placeholder),
                            ("aria-label", f"{label} to"),
                            ("class", _DATE_RANGE_INPUT_CLASS),
                        ],
                    ),
                ],
            ),
        ],
    )


_FILTER_FORM_ID = "filter-bar-form"


_FILTER_INPUT_ID = "filter-json-input"


def _filter_collapse_button() -> Node:
    return Element(
        "button",
        attributes=[
            ("type", "button"),
            # Slider handles are positioned in percentages, so initializing
            # them while the body is hidden is safe — no re-init on reveal.
            # Click is wired by filter-bar.ts (no inline handler).
            ("data-filter-bar-toggle", ""),
            (
                "class",
                "flex items-center gap-2 text-sm font-medium text-body "
                "hover:text-heading mb-2",
            ),
        ],
        children=[
            Safe(
                '<svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M10.5 6h9.75M10.5 6a1.5 1.5 0 1 1-3 0m3 0a1.5 1.5 0 1 0-3 0M3.75 6H7.5m3 12h9.75m-9.75 0a1.5 1.5 0 0 1-3 0m3 0a1.5 1.5 0 0 0-3 0m-3.75 0H7.5m9-6h3.75m-3.75 0a1.5 1.5 0 0 1-3 0m3 0a1.5 1.5 0 0 0-3 0m-9.75 0h9.75" /></svg>'
            ),
            "Filters",
        ],
    )


def _filter_action_row() -> Node:
    return Div(
        attributes=[("class", "flex gap-3 items-center")],
        children=[
            Element(
                "button",
                attributes=[
                    ("type", "submit"),
                    (
                        "class",
                        "px-4 py-2 text-sm font-medium text-white bg-brand "
                        "rounded-lg hover:bg-brand-strong focus:ring-4 "
                        "focus:ring-brand-medium",
                    ),
                ],
                children=["Apply"],
            ),
            Element(
                "button",
                attributes=[
                    ("type", "button"),
                    ("data-filter-bar-clear", ""),
                    (
                        "class",
                        "px-4 py-2 text-sm font-medium text-gray-900 bg-white "
                        "border border-gray-200 rounded-lg hover:bg-gray-100 "
                        "dark:bg-gray-800 dark:border-gray-600 dark:text-gray-400 "
                        "dark:hover:bg-gray-700 dark:hover:text-white",
                    ),
                ],
                children=["Clear"],
            ),
            Span(
                attributes=[
                    ("class", "flex gap-2 items-center"),
                    ("id", "save-preset-area"),
                ],
                children=[
                    Input(
                        attributes=[
                            ("type", "text"),
                            ("id", "preset-name-input"),
                            ("data-filter-bar-preset-name", ""),
                            ("placeholder", "Preset name..."),
                            (
                                "class",
                                "hidden px-3 py-2 text-sm rounded-lg border "
                                "border-default-medium bg-neutral-secondary-medium "
                                "text-heading focus:ring-brand focus:border-brand",
                            ),
                        ],
                    ),
                    Element(
                        "button",
                        attributes=[
                            ("type", "button"),
                            ("id", "save-preset-btn"),
                            ("data-filter-bar-save", ""),
                            (
                                "class",
                                "px-4 py-2 text-sm font-medium text-gray-900 "
                                "bg-white border border-gray-200 rounded-lg "
                                "hover:bg-gray-100 dark:bg-gray-800 "
                                "dark:border-gray-600 dark:text-gray-400 "
                                "dark:hover:bg-gray-700 dark:hover:text-white",
                            ),
                        ],
                        children=["Save Preset"],
                    ),
                    Element(
                        "button",
                        attributes=[
                            ("type", "button"),
                            ("id", "confirm-save-preset-btn"),
                            ("data-filter-bar-confirm-save", ""),
                            (
                                "class",
                                "hidden px-4 py-2 text-sm font-medium text-white "
                                "bg-green-700 rounded-lg hover:bg-green-800 "
                                "focus:ring-4 focus:ring-green-300",
                            ),
                        ],
                        children=["Save"],
                    ),
                ],
            ),
            Div(
                attributes=[
                    ("id", "preset-dropdown"),
                    ("class", "relative"),
                ],
                children=[
                    Span(
                        attributes=[("class", "text-sm text-body")],
                        children=["Loading presets..."],
                    ),
                ],
            ),
        ],
    )


class _FilterBarBase(BaseComponent):
    """Shared collapsible filter-bar chrome.

    Subclasses implement ``build_fields()`` returning the per-entity body
    (grids, sliders, checkboxes); this base wraps it in the collapse toggle,
    the form, the hidden filter-json input and the Apply/Clear/preset action
    row. ``filter-bar.js`` (declared via ``_FilterBarElement``) wires the
    chrome; widget media bubbles up from the contained widgets via the node
    tree, so the view never threads ``scripts=`` by hand.
    """

    def __init__(
        self,
        filter_json: str = "",
        preset_list_url: str = "",
        preset_save_url: str = "",
    ) -> None:
        self.filter_json = filter_json
        self.preset_list_url = preset_list_url
        self.preset_save_url = preset_save_url
        self.existing = _filter_parse(filter_json)

    def build_fields(self) -> list:
        """Return the per-entity filter body. Implemented by each subclass."""
        raise NotImplementedError

    def render(self) -> Node:
        return _FilterBarElement(
            preset_list_url=self.preset_list_url,
            preset_save_url=self.preset_save_url,
        )[
            Div(
                attributes=[("id", "filter-bar"), ("class", "mb-6")],
                children=[
                    _filter_collapse_button(),
                    Div(
                        attributes=[
                            ("id", "filter-bar-body"),
                            (
                                "class",
                                "hidden border border-default-medium rounded-base p-4 "
                                "bg-neutral-secondary-medium/50",
                            ),
                        ],
                        children=[
                            Element(
                                "form",
                                attributes=[
                                    ("id", _FILTER_FORM_ID),
                                ],
                                children=[
                                    Input(
                                        attributes=[
                                            ("type", "hidden"),
                                            ("id", _FILTER_INPUT_ID),
                                            ("name", "filter"),
                                            # NB: attribute values are escaped, so the
                                            # raw JSON passes through (no double-escape).
                                            ("value", self.filter_json),
                                        ],
                                    ),
                                    *self.build_fields(),
                                    _filter_action_row(),
                                ],
                            ),
                        ],
                    ),
                ],
            )
        ]


class FilterBar(_FilterBarBase):
    """Collapsible filter bar for the Game list."""

    def __init__(
        self,
        filter_json: str = "",
        status_options: list[LabeledOption] | None = None,
        preset_list_url: str = "",
        preset_save_url: str = "",
    ) -> None:
        super().__init__(filter_json, preset_list_url, preset_save_url)
        self.status_options = status_options

    def build_fields(self) -> list:
        return _game_fields(self.existing, self.status_options)


def _game_fields(
    existing: dict, status_options: list[LabeledOption] | None = None
) -> list:
    from games.models import Game, Purchase

    if status_options is None:
        status_options = [(s.value, s.label) for s in Game.Status]

    status_choice = _filter_get_choice(existing, "status")
    platform_choice = _filter_get_choice(existing, "platform")
    platform_group_choice = _filter_get_choice(existing, "platform_group")
    device_choice = _filter_get_choice(existing, "device")
    purchase_type_choice = _filter_get_choice(existing, "purchase_type")
    purchase_ownership_choice = _filter_get_choice(existing, "purchase_ownership_type")
    playevent_note_value = existing.get("playevent_note", {}).get("value", "")
    playevent_note_modifier = existing.get("playevent_note", {}).get(
        "modifier", "EQUALS"
    )

    year_min, year_max = _parse_range(existing, "year_released")
    original_year_min, original_year_max = _parse_range(
        existing, "original_year_released"
    )
    mastered_value = _parse_bool_nullable(existing, "mastered")
    playtime = existing.get("playtime_hours", {})
    if isinstance(playtime, dict):
        playtime_min = playtime.get("value", "")
        playtime_max = playtime.get("value2", "")
    else:
        playtime_min = ""
        playtime_max = ""

    session_count_min, session_count_max = _parse_range(existing, "session_count")
    session_avg_min, session_avg_max = _parse_range(existing, "session_average")
    purchase_count_min, purchase_count_max = _parse_range(existing, "purchase_count")
    playevent_count_min, playevent_count_max = _parse_range(existing, "playevent_count")
    manual_pt_min, manual_pt_max = _parse_range(existing, "manual_playtime_hours")
    calc_pt_min, calc_pt_max = _parse_range(existing, "calculated_playtime_hours")
    price_total_min, price_total_max = _parse_range(existing, "purchase_price_total")
    price_any_min, price_any_max = _parse_range(existing, "purchase_price_any")
    purchase_refunded_value = _parse_bool_nullable(existing, "purchase_refunded")
    purchase_infinite_value = _parse_bool_nullable(existing, "purchase_infinite")
    session_emulated_value = _parse_bool_nullable(existing, "session_emulated")

    try:
        year_aggregate = Game.objects.aggregate(
            year_min=models.Min("year_released"), year_max=models.Max("year_released")
        )
    except Exception:
        year_aggregate = {}
    try:
        original_year_aggregate = Game.objects.aggregate(
            year_min=models.Min("original_year_released"),
            year_max=models.Max("original_year_released"),
        )
    except Exception:
        original_year_aggregate = {}
    try:
        playtime_aggregate = Game.objects.aggregate(playtime_max=models.Max("playtime"))
    except Exception:
        playtime_aggregate = {}
    try:
        price_aggregate = Purchase.objects.aggregate(
            price_min=models.Min("converted_price"),
            price_max=models.Max("converted_price"),
        )
    except Exception:
        price_aggregate = {}
    year_range_min = max(int(year_aggregate.get("year_min") or 1970), 1970)
    year_range_max = min(int(year_aggregate.get("year_max") or 2030), 2030)
    original_year_range_min = max(
        int(original_year_aggregate.get("year_min") or 1970), 1970
    )
    original_year_range_max = min(
        int(original_year_aggregate.get("year_max") or 2030), 2030
    )
    playtime_range_max = (
        int((playtime_aggregate.get("playtime_max") or 0).total_seconds() / 3600)
        if playtime_aggregate.get("playtime_max")
        else 200
    )
    price_range_min = int(price_aggregate.get("price_min") or 0)
    price_range_max = max(int(price_aggregate.get("price_max") or 100), 1)

    fields = [
        Div(
            attributes=[("class", _FILTER_GRID_CLASS)],
            children=[
                _filter_field(
                    "Status",
                    _enum_filter(
                        "status",
                        status_options,
                        status_choice,
                        nullable=not Game._meta.get_field("status").has_default(),
                    ),
                ),
                _filter_field(
                    "Platform",
                    _model_filter(
                        "platform",
                        platform_choice,
                        search_url="/api/platforms/search",
                        nullable=Game._meta.get_field("platform").null,
                    ),
                ),
                _filter_field(
                    "Platform Group",
                    _model_filter(
                        "platform_group",
                        platform_group_choice,
                        search_url="/api/platforms/groups",
                        nullable=False,
                    ),
                ),
                _filter_field(
                    "Device",
                    _model_filter(
                        "device",
                        device_choice,
                        search_url="/api/devices/search",
                        nullable=False,
                    ),
                ),
                _filter_field(
                    "Purchase Type",
                    _enum_filter(
                        "purchase_type",
                        Purchase.TYPES,
                        purchase_type_choice,
                        nullable=False,
                    ),
                ),
                _filter_field(
                    "Purchase Ownership",
                    _enum_filter(
                        "purchase_ownership_type",
                        Purchase.OWNERSHIP_TYPES,
                        purchase_ownership_choice,
                        nullable=False,
                    ),
                ),
                _filter_field(
                    "Playevent Note",
                    StringFilter(
                        input_name_prefix="filter-playevent_note",
                        value=playevent_note_value,
                        modifier=playevent_note_modifier,
                        placeholder="e.g. Completed, Started",
                    ),
                ),
                _filter_field(
                    "Year",
                    RangeSlider(
                        label="Year",
                        input_name_prefix="filter-year",
                        min_value=year_min,
                        max_value=year_max,
                        range_min=year_range_min,
                        range_max=year_range_max,
                        min_placeholder="e.g. 2020",
                        max_placeholder="e.g. 2024",
                    ),
                ),
                _filter_field(
                    "Original Year",
                    RangeSlider(
                        label="Original Year",
                        input_name_prefix="filter-original-year",
                        min_value=original_year_min,
                        max_value=original_year_max,
                        range_min=original_year_range_min,
                        range_max=original_year_range_max,
                        min_placeholder="e.g. 1985",
                        max_placeholder="e.g. 2010",
                    ),
                ),
                _filter_field(
                    "Total playtime",
                    RangeSlider(
                        label="Total playtime",
                        input_name_prefix="filter-playtime-hours",
                        min_value=playtime_min,
                        max_value=playtime_max,
                        range_min=0,
                        range_max=playtime_range_max,
                        step="1",
                        min_placeholder="e.g. 1",
                        max_placeholder="e.g. 100",
                    ),
                ),
                _filter_field(
                    "Manual Playtime (hrs)",
                    RangeSlider(
                        label="Manual Playtime (hrs)",
                        input_name_prefix="filter-manual-playtime-hours",
                        min_value=manual_pt_min,
                        max_value=manual_pt_max,
                        range_min=0,
                        range_max=max(playtime_range_max, 4),
                        step="1",
                        min_placeholder="e.g. 1",
                        max_placeholder="e.g. 10",
                    ),
                ),
                _filter_field(
                    "Calculated Playtime (hrs)",
                    RangeSlider(
                        label="Calculated Playtime (hrs)",
                        input_name_prefix="filter-calculated-playtime-hours",
                        min_value=calc_pt_min,
                        max_value=calc_pt_max,
                        range_min=0,
                        range_max=max(playtime_range_max, 4),
                        step="1",
                        min_placeholder="e.g. 1",
                        max_placeholder="e.g. 10",
                    ),
                ),
                _filter_field(
                    "Session Count",
                    RangeSlider(
                        label="Session Count",
                        input_name_prefix="filter-session-count",
                        min_value=session_count_min,
                        max_value=session_count_max,
                        range_min=0,
                        range_max=100,
                        step="1",
                        min_placeholder="e.g. 1",
                        max_placeholder="e.g. 50",
                    ),
                ),
                _filter_field(
                    "Average Session Duration (mins)",
                    RangeSlider(
                        label="Average Session Duration (mins)",
                        input_name_prefix="filter-session-average",
                        min_value=session_avg_min,
                        max_value=session_avg_max,
                        range_min=0,
                        range_max=240,
                        step="1",
                        min_placeholder="e.g. 10",
                        max_placeholder="e.g. 120",
                    ),
                ),
                _filter_field(
                    "Number of Purchases",
                    RangeSlider(
                        label="Number of Purchases",
                        input_name_prefix="filter-purchase-count",
                        min_value=purchase_count_min,
                        max_value=purchase_count_max,
                        range_min=0,
                        range_max=20,
                        step="1",
                        min_placeholder="e.g. 1",
                        max_placeholder="e.g. 5",
                    ),
                ),
                _filter_field(
                    "Number of Play Events",
                    RangeSlider(
                        label="Number of Play Events",
                        input_name_prefix="filter-playevent-count",
                        min_value=playevent_count_min,
                        max_value=playevent_count_max,
                        range_min=0,
                        range_max=20,
                        step="1",
                        min_placeholder="e.g. 1",
                        max_placeholder="e.g. 5",
                    ),
                ),
                _filter_field(
                    "Total Purchase Price",
                    RangeSlider(
                        label="Total Purchase Price",
                        input_name_prefix="filter-purchase-price-total",
                        min_value=price_total_min,
                        max_value=price_total_max,
                        range_min=price_range_min,
                        range_max=price_range_max,
                        min_placeholder="0",
                        max_placeholder=str(price_range_max),
                    ),
                ),
                _filter_field(
                    "Any Purchase Price",
                    RangeSlider(
                        label="Any Purchase Price",
                        input_name_prefix="filter-purchase-price-any",
                        min_value=price_any_min,
                        max_value=price_any_max,
                        range_min=price_range_min,
                        range_max=price_range_max,
                        min_placeholder="0",
                        max_placeholder=str(price_range_max),
                    ),
                ),
            ],
        ),
        Div(
            attributes=[("class", "flex items-end gap-6 mb-4 flex-wrap")],
            children=[
                _filter_boolean_radio("filter-mastered", "Mastered", mastered_value),
                _filter_boolean_radio(
                    "filter-purchase-refunded", "Refunded", purchase_refunded_value
                ),
                _filter_boolean_radio(
                    "filter-purchase-infinite", "Infinite", purchase_infinite_value
                ),
                _filter_boolean_radio(
                    "filter-session-emulated", "Emulated", session_emulated_value
                ),
            ],
        ),
    ]
    return fields


def _find_label(options: list[LabeledOption], value: str) -> str:
    for v, label in options:
        if str(v) == str(value):
            return label
    return value


class SessionFilterBar(_FilterBarBase):
    """Collapsible filter bar for the Session list."""

    def build_fields(self) -> list:
        return _session_fields(self.existing)


def _session_fields(existing: dict) -> list:
    from games.models import Game, Session

    game_choice = _filter_get_choice(existing, "game")
    device_choice = _filter_get_choice(existing, "device")
    note_value = existing.get("note", {}).get("value", "")
    note_modifier = existing.get("note", {}).get("modifier", "EQUALS")

    dur_tot_min, dur_tot_max = _parse_range(existing, "duration_total_hours")
    dur_man_min, dur_man_max = _parse_range(existing, "duration_manual_hours")
    dur_calc_min, dur_calc_max = _parse_range(existing, "duration_calculated_hours")
    emulated_value = _parse_bool_nullable(existing, "emulated")
    is_active_value = _parse_bool_nullable(existing, "is_active")
    try:
        duration_aggregate = Session.objects.aggregate(
            duration_max=models.Max("duration_total")
        )
        duration_range_max = max(
            int((duration_aggregate.get("duration_max") or 0).total_seconds() / 3600)
            if duration_aggregate.get("duration_max")
            else 200,
            1,
        )
    except Exception:
        duration_range_max = 200

    fields = [
        Div(
            attributes=[("class", _FILTER_GRID_CLASS)],
            children=[
                _filter_field(
                    "Game",
                    _model_filter(
                        "game",
                        game_choice,
                        search_url="/api/games/search",
                        nullable=not Game._meta.get_field("name").has_default(),
                    ),
                ),
                _filter_field(
                    "Device",
                    _model_filter(
                        "device",
                        device_choice,
                        search_url="/api/devices/search",
                        nullable=Session._meta.get_field("device").null,
                    ),
                ),
                _filter_field(
                    "Session Note",
                    StringFilter(
                        input_name_prefix="filter-note",
                        value=note_value,
                        modifier=note_modifier,
                        placeholder="e.g. Boss fight, speedrun",
                    ),
                ),
            ],
        ),
        RangeSlider(
            label="Total Duration (hrs)",
            input_name_prefix="filter-duration-total-hours",
            min_value=dur_tot_min,
            max_value=dur_tot_max,
            range_min=0,
            range_max=duration_range_max,
            step="1",
            min_placeholder="e.g. 1",
            max_placeholder="e.g. 10",
        ),
        RangeSlider(
            label="Manual Duration (hrs)",
            input_name_prefix="filter-duration-manual-hours",
            min_value=dur_man_min,
            max_value=dur_man_max,
            range_min=0,
            range_max=duration_range_max,
            step="1",
            min_placeholder="e.g. 1",
            max_placeholder="e.g. 10",
        ),
        RangeSlider(
            label="Calculated Duration (hrs)",
            input_name_prefix="filter-duration-calculated-hours",
            min_value=dur_calc_min,
            max_value=dur_calc_max,
            range_min=0,
            range_max=duration_range_max,
            step="1",
            min_placeholder="e.g. 1",
            max_placeholder="e.g. 10",
        ),
        Div(
            attributes=[("class", "flex gap-6 mb-4")],
            children=[
                _filter_boolean_radio("filter-emulated", "Emulated", emulated_value),
                _filter_boolean_radio("filter-active", "Active", is_active_value),
            ],
        ),
    ]
    return fields


class PurchaseFilterBar(_FilterBarBase):
    """Collapsible filter bar for the Purchase list."""

    def build_fields(self) -> list:
        return _purchase_fields(self.existing)


def _purchase_fields(existing: dict) -> list:
    from games.models import Purchase

    type_options = Purchase.TYPES
    ownership_options = Purchase.OWNERSHIP_TYPES
    game_choice = _filter_get_choice(existing, "games")
    platform_choice = _filter_get_choice(existing, "platform")
    type_choice = _filter_get_choice(existing, "type")
    ownership_choice = _filter_get_choice(existing, "ownership_type")
    price_min, price_max = _parse_range(existing, "price")
    is_refunded_value = _parse_bool_nullable(existing, "is_refunded")
    infinite_value = _parse_bool_nullable(existing, "infinite")
    needs_price_update_value = _parse_bool_nullable(existing, "needs_price_update")
    price_currency_value = existing.get("price_currency", {}).get("value", "")
    price_currency_modifier = existing.get("price_currency", {}).get(
        "modifier", "EQUALS"
    )
    converted_currency_value = existing.get("converted_currency", {}).get("value", "")
    converted_currency_modifier = existing.get("converted_currency", {}).get(
        "modifier", "EQUALS"
    )
    date_purchased_min, date_purchased_max = _parse_range(existing, "date_purchased")
    date_refunded_min, date_refunded_max = _parse_range(existing, "date_refunded")

    try:
        price_aggregate = Purchase.objects.aggregate(
            price_min=models.Min("price"), price_max=models.Max("price")
        )
        price_range_min = int(price_aggregate.get("price_min") or 0)
        price_range_max = max(int(price_aggregate.get("price_max") or 100), 1)
    except Exception:
        price_range_min, price_range_max = 0, 100

    num_min, num_max = _parse_range(existing, "num_purchases")
    try:
        num_aggregate = Purchase.objects.aggregate(
            num_min=models.Min("num_purchases"), num_max=models.Max("num_purchases")
        )
        num_range_min = max(int(num_aggregate.get("num_min") or 0), 0)
        num_range_max = max(int(num_aggregate.get("num_max") or 10), 1)
    except Exception:
        num_range_min, num_range_max = 0, 10

    fields = [
        Div(
            attributes=[("class", _FILTER_GRID_CLASS)],
            children=[
                _filter_field(
                    "Game",
                    _model_filter(
                        "games",
                        game_choice,
                        search_url="/api/games/search",
                        nullable=False,
                        # games is many-to-many on Purchase: (All) means
                        # INCLUDES_ALL ("purchase linked to every selected
                        # game"); (Only) means INCLUDES_ONLY.
                        m2m_modifiers=_M2M_MODIFIERS,
                    ),
                ),
                _filter_field(
                    "Platform",
                    _model_filter(
                        "platform",
                        platform_choice,
                        search_url="/api/platforms/search",
                        nullable=Purchase._meta.get_field("platform").null,
                    ),
                ),
                _filter_field(
                    "Type",
                    _enum_filter(
                        "type",
                        type_options,
                        type_choice,
                        nullable=not Purchase._meta.get_field("type").has_default(),
                    ),
                ),
                _filter_field(
                    "Ownership",
                    _enum_filter(
                        "ownership_type",
                        ownership_options,
                        ownership_choice,
                        nullable=not Purchase._meta.get_field(
                            "ownership_type"
                        ).has_default(),
                    ),
                ),
                Div(
                    attributes=[("class", _FILTER_GRID_CLASS)],
                    children=[
                        _filter_field(
                            "Original Currency",
                            StringFilter(
                                input_name_prefix="filter-price_currency",
                                value=price_currency_value,
                                modifier=price_currency_modifier,
                                placeholder="e.g. USD, EUR",
                            ),
                        ),
                        _filter_field(
                            "Converted Currency",
                            StringFilter(
                                input_name_prefix="filter-converted_currency",
                                value=converted_currency_value,
                                modifier=converted_currency_modifier,
                                placeholder="e.g. USD, EUR",
                            ),
                        ),
                    ],
                ),
                _filter_field(
                    "Purchased",
                    DateRangePicker(
                        label="Purchased",
                        input_name_prefix="filter-date-purchased",
                        min_value=date_purchased_min,
                        max_value=date_purchased_max,
                    ),
                ),
                _filter_field(
                    "Refunded",
                    DateRangeFilter(
                        label="Refunded",
                        input_name_prefix="filter-date-refunded",
                        min_value=date_refunded_min,
                        max_value=date_refunded_max,
                    ),
                ),
                _filter_field(
                    "Price",
                    RangeSlider(
                        label="Price",
                        input_name_prefix="filter-price",
                        min_value=price_min,
                        max_value=price_max,
                        range_min=price_range_min,
                        range_max=price_range_max,
                        min_placeholder="0.00",
                        max_placeholder="100.00",
                    ),
                ),
                _filter_field(
                    "Games in purchase",
                    RangeSlider(
                        label="Games in purchase",
                        input_name_prefix="filter-num-purchases",
                        min_value=num_min,
                        max_value=num_max,
                        range_min=num_range_min,
                        range_max=num_range_max,
                        step="1",
                        min_placeholder="e.g. 1",
                        max_placeholder="e.g. 5",
                    ),
                ),
                Div(
                    attributes=[("class", "flex flex-col items-start gap-4 mb-4")],
                    children=[
                        _filter_boolean_radio(
                            "filter-refunded", "Refunded", is_refunded_value
                        ),
                        _filter_boolean_radio(
                            "filter-infinite", "Infinite", infinite_value
                        ),
                        _filter_boolean_radio(
                            "filter-needs-price-update",
                            "Needs Price Update",
                            needs_price_update_value,
                        ),
                    ],
                ),
            ],
        ),
    ]
    return fields


class DeviceFilterBar(_FilterBarBase):
    """Collapsible filter bar for the Device list."""

    def build_fields(self) -> list:
        return _device_fields(self.existing)


def _device_fields(existing: dict) -> list:
    from games.models import Device

    type_options = Device.DEVICE_TYPES
    type_choice = _filter_get_choice(existing, "type")

    fields = [
        Div(
            attributes=[("class", _FILTER_GRID_CLASS)],
            children=[
                _filter_field(
                    "Device Type",
                    _enum_filter(
                        "type",
                        type_options,
                        type_choice,
                        nullable=True,
                    ),
                ),
            ],
        ),
    ]
    return fields


class PlatformFilterBar(_FilterBarBase):
    """Collapsible filter bar for the Platform list."""

    def build_fields(self) -> list:
        return _platform_fields(self.existing)


def _platform_fields(existing: dict) -> list:
    name_value = existing.get("name", {}).get("value", "")
    name_modifier = existing.get("name", {}).get("modifier", "EQUALS")
    group_value = existing.get("group", {}).get("value", "")
    group_modifier = existing.get("group", {}).get("modifier", "EQUALS")

    fields = [
        Div(
            attributes=[("class", _FILTER_GRID_CLASS)],
            children=[
                _filter_field(
                    "Platform Name",
                    StringFilter(
                        input_name_prefix="filter-name",
                        value=name_value,
                        modifier=name_modifier,
                        placeholder="e.g. Nintendo Switch",
                    ),
                ),
                _filter_field(
                    "Platform Group",
                    StringFilter(
                        input_name_prefix="filter-group",
                        value=group_value,
                        modifier=group_modifier,
                        placeholder="e.g. Nintendo",
                    ),
                ),
            ],
        ),
    ]
    return fields


class PlayEventFilterBar(_FilterBarBase):
    """Collapsible filter bar for the PlayEvent list."""

    def build_fields(self) -> list:
        return _playevent_fields(self.existing)


def _playevent_fields(existing: dict) -> list:
    game_choice = _filter_get_choice(existing, "game")
    days_min, days_max = _parse_range(existing, "days_to_finish")

    fields = [
        Div(
            attributes=[("class", _FILTER_GRID_CLASS)],
            children=[
                _filter_field(
                    "Game",
                    _model_filter(
                        "game",
                        game_choice,
                        search_url="/api/games/search",
                        nullable=False,
                    ),
                ),
            ],
        ),
        RangeSlider(
            label="Days to Finish",
            input_name_prefix="filter-days-to-finish",
            min_value=days_min,
            max_value=days_max,
            range_min=0,
            range_max=365,
            step="1",
            min_placeholder="e.g. 1",
            max_placeholder="e.g. 30",
        ),
    ]
    return fields


def StringFilter(
    input_name_prefix: str,
    value: str = "",
    modifier: str = "EQUALS",
    placeholder: str = "",
) -> Node:
    """Renders a string filter with 8 modifier radio options and a text input."""
    from common.criteria import Modifier

    if modifier not in [m.value for m in Modifier.for_strings()]:
        modifier = "EQUALS"

    options = [
        ("EQUALS", "is"),
        ("NOT_EQUALS", "is not"),
        ("INCLUDES", "includes"),
        ("EXCLUDES", "excludes"),
        ("MATCHES_REGEX", "matches regex"),
        ("NOT_MATCHES_REGEX", "not matches regex"),
        ("IS_NULL", "is null"),
        ("NOT_NULL", "is not null"),
    ]

    # Grid of Radios using standard Radio primitives
    radio_buttons = [
        Radio(
            name=f"{input_name_prefix}-modifier",
            label=lbl,
            checked=(modifier == mod_val),
            value=mod_val,
            attributes=[
                ("data-string-modifier-radio", ""),
            ],
        )
        for mod_val, lbl in options
    ]

    input_disabled = modifier in ("IS_NULL", "NOT_NULL")

    input_attrs = [
        ("type", "text"),
        ("name", input_name_prefix),
        ("value", value if not input_disabled else ""),
        ("placeholder", placeholder),
        (
            "class",
            # text-sm + px-3 py-2.5 match every other input (canonical size).
            "w-full rounded-base border border-default-medium px-3 py-2.5 text-sm "
            "bg-neutral-secondary-medium text-body "
            "focus:border-brand focus:ring-brand "
            # No transition-* here: with transition-all the border-color animated
            # from near-white default → brand on focus, which read as a white
            # "blink". The other inputs snap to the focus state, so this does too.
            + ("opacity-50 cursor-not-allowed" if input_disabled else ""),
        ),
    ]
    if input_disabled:
        input_attrs.append(("disabled", "true"))

    return Div(
        attributes=[("class", "flex flex-col gap-2 @container")],
        children=[
            Div(
                attributes=[
                    (
                        "class",
                        "grid grid-cols-2 @md:grid-cols-4 gap-2 py-1",
                    )
                ],
                children=radio_buttons,
            ),
            Input(attributes=input_attrs),
        ],
    )
