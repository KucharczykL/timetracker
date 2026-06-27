"""Stash-style filter bars, built from FilterSelect widgets."""

from typing import NamedTuple

from common.components.core import BaseComponent, Element, Node, Safe
from common.components.custom_elements import _FilterBarElement
from common.components.date_range_picker import DateRangePicker
from common.components.primitives import (
    Div,
    FilterWidgetKind,
    FilterWidgetPath,
    Input,
    Label,
    Radio,
    RelationChild,
    Span,
    filter_widget_attributes,
)
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


class NumberValues(NamedTuple):
    """(value, value2, modifier) parsed from a numeric filter criterion."""

    value: str
    value2: str
    modifier: str


class StringValues(NamedTuple):
    """(value, modifier) parsed from a string filter criterion."""

    value: str
    modifier: str


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


def _extract_labeled(items: list) -> list[LabeledOption]:
    """Convert filter values to ``(value, label)`` pairs.

    UI-built filters carry ``{id, label}`` dicts; programmatically-built ones
    (e.g. stats_links) carry bare ids/choices. A bare value uses itself as its
    own label so the bar renders any valid filter instead of crashing."""
    pairs: list[LabeledOption] = []
    for item in items:
        if isinstance(item, dict):
            pairs.append((str(item["id"]), str(item["label"])))
        else:
            pairs.append((str(item), str(item)))
    return pairs


def _choice_from_raw(raw: dict) -> FilterChoice:
    """Parse a set criterion dict (value/excludes/modifier) into a FilterChoice."""
    if not isinstance(raw, dict):
        return FilterChoice([], [], "")
    return FilterChoice(
        selected=_extract_labeled(raw.get("value") or []),
        excluded=_extract_labeled(raw.get("excludes") or []),
        modifier=raw.get("modifier") or "",
    )


def _filter_get_choice(existing: dict, field: str) -> FilterChoice:
    return _choice_from_raw(existing.get(field, {}))


def _range_from_field(field: dict) -> RangeValues:
    """Extract (min, max) from a range criterion dict, defaulting to ("", "")."""
    if not isinstance(field, dict):
        return RangeValues("", "")
    value = str(field.get("value", ""))
    if field.get("modifier") == "LESS_THAN":
        return RangeValues("", value)
    return RangeValues(value, str(field.get("value2", "")))


def _parse_range(existing: dict, key: str) -> RangeValues:
    """Extract (min, max) from a range filter criterion, defaulting to ("", "").

    A one-sided range stores its single bound in ``value`` regardless of side
    (GREATER_THAN → min, LESS_THAN → max), so the modifier decides which slot it
    fills; only BETWEEN carries both ``value`` (min) and ``value2`` (max).
    """
    return _range_from_field(existing.get(key, {}))


def _number_from_field(field: dict) -> NumberValues:
    """Extract (value, value2, modifier) from a numeric criterion dict."""
    if not isinstance(field, dict):
        return NumberValues("", "", "EQUALS")
    return NumberValues(
        str(field.get("value", "")),
        str(field.get("value2", "")),
        str(field.get("modifier") or "EQUALS"),
    )


def _parse_number(existing: dict, key: str) -> NumberValues:
    """Extract (value, value2, modifier) from a numeric filter criterion.

    Backward compatible with old RangeSlider JSON: a stored GREATER_THAN /
    LESS_THAN / BETWEEN criterion maps straight onto value/value2/modifier.
    """
    return _number_from_field(existing.get(key, {}))


def _string_from_field(field: dict) -> StringValues:
    """Extract (value, modifier) from a string criterion dict."""
    if not isinstance(field, dict):
        return StringValues("", "EQUALS")
    return StringValues(
        str(field.get("value", "")), str(field.get("modifier") or "EQUALS")
    )


# ── Cross-entity (nested AND) prefill (#123 Phase 2d) ────────────────────────
# Repointed cross-entity widgets serialize into ``existing["AND"]`` as their own
# sub-filter element (independent EXISTS), so prefill scans that list rather than
# reading a flat top-level key. Each helper is matched to a widget by the same
# ``data-path`` the widget serializes to — a single source of truth.


def _deep_get(value: dict, keys: FilterWidgetPath) -> object:
    """Walk ``keys`` through nested dicts, returning None if any step is absent."""
    current: object = value
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current


def _cross_entity_criterion(existing: dict, path: FilterWidgetPath) -> dict:
    """Find the leaf criterion a composed widget at ``path`` serialized into AND.

    Scans ``existing["AND"]`` for the element whose nested chain ``path[:-1]``
    contains ``path[-1]`` as a dict (the leaf criterion), returning that dict (or
    ``{}`` when no element matches). Example: ``["session_filter", "device"]``
    finds ``{"session_filter": {"device": {...}}}`` and returns the inner dict.
    """
    for element in existing.get("AND", []) or []:
        if not isinstance(element, dict):
            continue
        parent = _deep_get(element, path[:-1])
        if isinstance(parent, dict) and isinstance(parent.get(path[-1]), dict):
            return parent[path[-1]]
    return {}


def _cross_entity_bool(
    existing: dict, relation_field: str, child_key: str
) -> bool | None:
    """Read a relation-bool widget's tri-state from the AND list.

    Returns True when an AND element's ``[relation_field][child_key]`` exists and
    its relation is matched ANY (no ``match`` / not NONE), False when that element
    sets ``match: "NONE"``, and None when no such element is present.
    """
    for element in existing.get("AND", []) or []:
        if not isinstance(element, dict):
            continue
        relation = element.get(relation_field)
        if isinstance(relation, dict) and child_key in relation:
            return relation.get("match") != "NONE"
    return None


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


def _enum_filter(
    field_name: str,
    options,
    choice: FilterChoice,
    *,
    nullable,
    path: FilterWidgetPath | None = None,
    compose: bool = False,
) -> Node:
    """A FilterSelect over a small, fully pre-rendered option set (enum field).

    Enum fields are single-valued, so no M2M modifiers (all/only are
    meaningless); only the presence modifier is surfaced. ``path``/``compose``
    let a cross-entity widget point at a nested sub-filter leaf (defaults to the
    flat ``[field_name]``).
    """
    options_str = [(str(value), label) for value, label in options]
    included = [
        (value, _find_label(options_str, value)) for value, _label in choice.selected
    ]
    excluded = [
        (value, _find_label(options_str, value)) for value, _label in choice.excluded
    ]
    modifier = choice.modifier
    return FilterSelect(
        field_name=field_name,
        options=options_str,
        included=included,
        excluded=excluded,
        modifier=modifier,
        modifier_options=_modifier_options(nullable),
        path=path if path is not None else [field_name],
        compose=compose,
    )


def _model_filter(
    field_name: str,
    choice: FilterChoice,
    *,
    search_url,
    nullable,
    m2m_modifiers: list[LabeledOption] | None = None,
    path: FilterWidgetPath | None = None,
    compose: bool = False,
) -> Node:
    """A FilterSelect backed by a search endpoint.

    Labels are embedded in the filter JSON (Stash-style), so pills render
    directly from ``choice`` with no DB round-trip. Pass ``m2m_modifiers`` for
    many-to-many fields to surface ``(All)`` / ``(Only)`` pseudo-options in the
    dropdown alongside the presence options. ``path``/``compose`` let a
    cross-entity widget point at a nested sub-filter leaf (defaults to the flat
    ``[field_name]``).
    """
    modifier = choice.modifier
    return FilterSelect(
        field_name=field_name,
        included=[(value, label or value) for value, label in choice.selected],
        excluded=[(value, label or value) for value, label in choice.excluded],
        modifier=modifier,
        modifier_options=_modifier_options(nullable, m2m_modifiers),
        search_url=search_url,
        prefetch=DEFAULT_PREFETCH,
        path=path if path is not None else [field_name],
        compose=compose,
    )


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


def _filter_boolean_radio(
    name: str,
    label: str,
    value: bool | None,
    *,
    path: FilterWidgetPath,
    relation_child: RelationChild | None = None,
) -> Node:
    """Renders a filter-specific boolean radio button group with 'True' and 'False' options.

    When ``relation_child`` is given the widget becomes a cross-entity
    relation-bool (``data-kind="relation-bool"``): ``path`` is the relation chain
    (no leaf), the radio toggles ANY (True) vs NONE (False) over the fixed child
    criterion, and the serializer appends it as its own AND element. See
    ``filter_widget_attributes``.
    """
    kind: FilterWidgetKind = "relation-bool" if relation_child is not None else "bool"
    return Div(
        attributes=[
            ("class", "flex flex-col gap-1"),
            # No ``compose=True``: the relation-bool serializer branch builds and
            # appends its own AND element directly, returning before it ever reads
            # ``data-compose`` — so emitting it would be inert and misleading.
            *filter_widget_attributes(
                path,
                kind,
                relation_child=relation_child,
            ),
        ],
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


_DATE_RANGE_INPUT_CLASS = (
    "w-full rounded-base border border-default-medium bg-neutral-secondary-medium "
    "text-sm text-heading p-1.5 focus:ring-brand focus:border-brand"
)


def DateRangeFilter(
    *,
    label: str,
    input_name_prefix: str,
    path: FilterWidgetPath,
    min_value: str = "",
    max_value: str = "",
    min_placeholder: str = "From",
    max_placeholder: str = "To",
) -> Node:
    """A pair of ``<input type="date">`` elements representing a date range.

    Two inputs named ``{prefix}-min`` and ``{prefix}-max`` — the browser's
    native date picker is the UI. Serialized client-side into a ``DateCriterion``
    with ``BETWEEN`` / ``GREATER_THAN`` / ``LESS_THAN`` depending on which
    bound(s) the user filled.
    """
    min_input_id = f"{input_name_prefix}-min"
    max_input_id = f"{input_name_prefix}-max"
    return Div(
        attributes=[
            ("class", "date-range-block mb-4"),
            *filter_widget_attributes(path, "date"),
        ],
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
                            ("data-range-min", ""),
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
                            ("data-range-max", ""),
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
    # Cross-entity widgets serialize into existing["AND"] as independent EXISTS
    # sub-filters (#123 Phase 2d), so prefill reads them back from that list,
    # matched by the same data-path each widget serializes to.
    device_choice = _choice_from_raw(
        _cross_entity_criterion(existing, ["session_filter", "device"])
    )
    purchase_type_choice = _choice_from_raw(
        _cross_entity_criterion(existing, ["purchase_filter", "type"])
    )
    purchase_ownership_choice = _choice_from_raw(
        _cross_entity_criterion(existing, ["purchase_filter", "ownership_type"])
    )
    playevent_note_value, playevent_note_modifier = _string_from_field(
        _cross_entity_criterion(existing, ["playevent_filter", "note"])
    )

    year = _parse_number(existing, "year_released")
    original_year = _parse_number(existing, "original_year_released")
    mastered_value = _parse_bool_nullable(existing, "mastered")
    playtime = _parse_number(existing, "playtime_hours")
    session_count = _parse_number(existing, "session_count")
    session_avg = _parse_number(existing, "session_average")
    purchase_count = _parse_number(existing, "purchase_count")
    playevent_count = _parse_number(existing, "playevent_count")
    finished_min, finished_max = _range_from_field(
        _cross_entity_criterion(existing, ["playevent_filter", "ended"])
    )
    manual_pt = _parse_number(existing, "manual_playtime_hours")
    calc_pt = _parse_number(existing, "calculated_playtime_hours")
    price_total = _parse_number(existing, "purchase_price_total")
    price_any = _number_from_field(
        _cross_entity_criterion(existing, ["purchase_filter", "converted_price"])
    )
    purchase_refunded_value = _cross_entity_bool(
        existing, "purchase_filter", "is_refunded"
    )
    purchase_infinite_value = _cross_entity_bool(
        existing, "purchase_filter", "infinite"
    )
    session_emulated_value = _cross_entity_bool(existing, "session_filter", "emulated")

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
                        path=["session_filter", "device"],
                        compose=True,
                    ),
                ),
                _filter_field(
                    "Purchase Type",
                    _enum_filter(
                        # Element name stays flat (a DOM identifier); the nested
                        # leaf comes from data-path, decoupled from the name.
                        "purchase_type",
                        Purchase.TYPES,
                        purchase_type_choice,
                        nullable=False,
                        path=["purchase_filter", "type"],
                        compose=True,
                    ),
                ),
                _filter_field(
                    "Purchase Ownership",
                    _enum_filter(
                        "purchase_ownership_type",
                        Purchase.OWNERSHIP_TYPES,
                        purchase_ownership_choice,
                        nullable=False,
                        path=["purchase_filter", "ownership_type"],
                        compose=True,
                    ),
                ),
                _filter_field(
                    "Playevent Note",
                    StringFilter(
                        input_name_prefix="filter-playevent_note",
                        value=playevent_note_value,
                        modifier=playevent_note_modifier,
                        placeholder="e.g. Completed, Started",
                        path=["playevent_filter", "note"],
                        compose=True,
                    ),
                ),
                _filter_field(
                    "Year",
                    NumberFilter(
                        input_name_prefix="filter-year",
                        value=year.value,
                        value2=year.value2,
                        modifier=year.modifier,
                        placeholder="e.g. 2020",
                        placeholder2="e.g. 2024",
                        path=["year_released"],
                    ),
                ),
                _filter_field(
                    "Original Year",
                    NumberFilter(
                        input_name_prefix="filter-original-year",
                        value=original_year.value,
                        value2=original_year.value2,
                        modifier=original_year.modifier,
                        placeholder="e.g. 1985",
                        placeholder2="e.g. 2010",
                        path=["original_year_released"],
                    ),
                ),
                _filter_field(
                    "Total playtime",
                    NumberFilter(
                        input_name_prefix="filter-playtime-hours",
                        value=playtime.value,
                        value2=playtime.value2,
                        modifier=playtime.modifier,
                        placeholder="e.g. 1",
                        placeholder2="e.g. 100",
                        path=["playtime_hours"],
                    ),
                ),
                _filter_field(
                    "Manual Playtime (hrs)",
                    NumberFilter(
                        input_name_prefix="filter-manual-playtime-hours",
                        value=manual_pt.value,
                        value2=manual_pt.value2,
                        modifier=manual_pt.modifier,
                        placeholder="e.g. 1",
                        placeholder2="e.g. 10",
                        path=["manual_playtime_hours"],
                    ),
                ),
                _filter_field(
                    "Calculated Playtime (hrs)",
                    NumberFilter(
                        input_name_prefix="filter-calculated-playtime-hours",
                        value=calc_pt.value,
                        value2=calc_pt.value2,
                        modifier=calc_pt.modifier,
                        placeholder="e.g. 1",
                        placeholder2="e.g. 10",
                        path=["calculated_playtime_hours"],
                    ),
                ),
                _filter_field(
                    "Session Count",
                    NumberFilter(
                        input_name_prefix="filter-session-count",
                        value=session_count.value,
                        value2=session_count.value2,
                        modifier=session_count.modifier,
                        placeholder="e.g. 1",
                        placeholder2="e.g. 50",
                        path=["session_count"],
                    ),
                ),
                _filter_field(
                    "Average Session Duration (mins)",
                    NumberFilter(
                        input_name_prefix="filter-session-average",
                        value=session_avg.value,
                        value2=session_avg.value2,
                        modifier=session_avg.modifier,
                        placeholder="e.g. 10",
                        placeholder2="e.g. 120",
                        path=["session_average"],
                    ),
                ),
                _filter_field(
                    "Number of Purchases",
                    NumberFilter(
                        input_name_prefix="filter-purchase-count",
                        value=purchase_count.value,
                        value2=purchase_count.value2,
                        modifier=purchase_count.modifier,
                        placeholder="e.g. 1",
                        placeholder2="e.g. 5",
                        path=["purchase_count"],
                    ),
                ),
                _filter_field(
                    "Number of Play Events",
                    NumberFilter(
                        input_name_prefix="filter-playevent-count",
                        value=playevent_count.value,
                        value2=playevent_count.value2,
                        modifier=playevent_count.modifier,
                        placeholder="e.g. 1",
                        placeholder2="e.g. 5",
                        path=["playevent_count"],
                    ),
                ),
                _filter_field(
                    "Finished",
                    DateRangePicker(
                        label="Finished",
                        input_name_prefix="filter-finished",
                        min_value=finished_min,
                        max_value=finished_max,
                        path=["playevent_filter", "ended"],
                        compose=True,
                    ),
                ),
                _filter_field(
                    "Total Purchase Price",
                    NumberFilter(
                        input_name_prefix="filter-purchase-price-total",
                        value=price_total.value,
                        value2=price_total.value2,
                        modifier=price_total.modifier,
                        placeholder="0",
                        placeholder2="e.g. 100",
                        step="0.01",
                        path=["purchase_price_total"],
                    ),
                ),
                _filter_field(
                    "Any Purchase Price",
                    NumberFilter(
                        input_name_prefix="filter-purchase-price-any",
                        value=price_any.value,
                        value2=price_any.value2,
                        modifier=price_any.modifier,
                        placeholder="0",
                        placeholder2="e.g. 100",
                        step="0.01",
                        path=["purchase_filter", "converted_price"],
                        compose=True,
                    ),
                ),
            ],
        ),
        Div(
            attributes=[("class", "flex items-end gap-6 mb-4 flex-wrap")],
            children=[
                _filter_boolean_radio(
                    "filter-mastered", "Mastered", mastered_value, path=["mastered"]
                ),
                _filter_boolean_radio(
                    "filter-purchase-refunded",
                    "Refunded",
                    purchase_refunded_value,
                    path=["purchase_filter"],
                    relation_child={
                        "is_refunded": {"value": True, "modifier": "EQUALS"}
                    },
                ),
                _filter_boolean_radio(
                    "filter-purchase-infinite",
                    "Infinite",
                    purchase_infinite_value,
                    path=["purchase_filter"],
                    relation_child={"infinite": {"value": True, "modifier": "EQUALS"}},
                ),
                _filter_boolean_radio(
                    "filter-session-emulated",
                    "Emulated",
                    session_emulated_value,
                    path=["session_filter"],
                    relation_child={"emulated": {"value": True, "modifier": "EQUALS"}},
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

    dur_tot = _parse_number(existing, "duration_total_hours")
    dur_man = _parse_number(existing, "duration_manual_hours")
    dur_calc = _parse_number(existing, "duration_calculated_hours")
    emulated_value = _parse_bool_nullable(existing, "emulated")
    is_active_value = _parse_bool_nullable(existing, "is_active")

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
                        path=["note"],
                    ),
                ),
            ],
        ),
        _filter_field(
            "Total Duration (hrs)",
            NumberFilter(
                input_name_prefix="filter-duration-total-hours",
                value=dur_tot.value,
                value2=dur_tot.value2,
                modifier=dur_tot.modifier,
                placeholder="e.g. 1",
                placeholder2="e.g. 10",
                path=["duration_total_hours"],
            ),
        ),
        _filter_field(
            "Manual Duration (hrs)",
            NumberFilter(
                input_name_prefix="filter-duration-manual-hours",
                value=dur_man.value,
                value2=dur_man.value2,
                modifier=dur_man.modifier,
                placeholder="e.g. 1",
                placeholder2="e.g. 10",
                path=["duration_manual_hours"],
            ),
        ),
        _filter_field(
            "Calculated Duration (hrs)",
            NumberFilter(
                input_name_prefix="filter-duration-calculated-hours",
                value=dur_calc.value,
                value2=dur_calc.value2,
                modifier=dur_calc.modifier,
                placeholder="e.g. 1",
                placeholder2="e.g. 10",
                path=["duration_calculated_hours"],
            ),
        ),
        Div(
            attributes=[("class", "flex gap-6 mb-4")],
            children=[
                _filter_boolean_radio(
                    "filter-emulated", "Emulated", emulated_value, path=["emulated"]
                ),
                _filter_boolean_radio(
                    "filter-active", "Active", is_active_value, path=["is_active"]
                ),
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
    price = _parse_number(existing, "price")
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
    # Cross-entity: purchase of a game finished in range (#123 Phase 2d). Reads
    # from the AND list, matched by the data-path the widget serializes to.
    finished_min, finished_max = _range_from_field(
        _cross_entity_criterion(existing, ["game_filter", "playevent_filter", "ended"])
    )
    num = _parse_number(existing, "num_purchases")

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
                                path=["price_currency"],
                            ),
                        ),
                        _filter_field(
                            "Converted Currency",
                            StringFilter(
                                input_name_prefix="filter-converted_currency",
                                value=converted_currency_value,
                                modifier=converted_currency_modifier,
                                placeholder="e.g. USD, EUR",
                                path=["converted_currency"],
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
                        path=["date_purchased"],
                    ),
                ),
                _filter_field(
                    "Refunded",
                    DateRangeFilter(
                        label="Refunded",
                        input_name_prefix="filter-date-refunded",
                        min_value=date_refunded_min,
                        max_value=date_refunded_max,
                        path=["date_refunded"],
                    ),
                ),
                _filter_field(
                    "Finished",
                    DateRangePicker(
                        label="Finished",
                        input_name_prefix="filter-finished",
                        min_value=finished_min,
                        max_value=finished_max,
                        path=["game_filter", "playevent_filter", "ended"],
                        compose=True,
                    ),
                ),
                _filter_field(
                    "Price",
                    NumberFilter(
                        input_name_prefix="filter-price",
                        value=price.value,
                        value2=price.value2,
                        modifier=price.modifier,
                        placeholder="0.00",
                        placeholder2="100.00",
                        step="0.01",
                        path=["price"],
                    ),
                ),
                _filter_field(
                    "Games in purchase",
                    NumberFilter(
                        input_name_prefix="filter-num-purchases",
                        value=num.value,
                        value2=num.value2,
                        modifier=num.modifier,
                        placeholder="e.g. 1",
                        placeholder2="e.g. 5",
                        path=["num_purchases"],
                    ),
                ),
                Div(
                    attributes=[("class", "flex flex-col items-start gap-4 mb-4")],
                    children=[
                        _filter_boolean_radio(
                            "filter-refunded",
                            "Refunded",
                            is_refunded_value,
                            path=["is_refunded"],
                        ),
                        _filter_boolean_radio(
                            "filter-infinite",
                            "Infinite",
                            infinite_value,
                            path=["infinite"],
                        ),
                        _filter_boolean_radio(
                            "filter-needs-price-update",
                            "Needs Price Update",
                            needs_price_update_value,
                            path=["needs_price_update"],
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
                        path=["name"],
                    ),
                ),
                _filter_field(
                    "Platform Group",
                    StringFilter(
                        input_name_prefix="filter-group",
                        value=group_value,
                        modifier=group_modifier,
                        placeholder="e.g. Nintendo",
                        path=["group"],
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
    days = _parse_number(existing, "days_to_finish")
    started_min, started_max = _parse_range(existing, "started")
    ended_min, ended_max = _parse_range(existing, "ended")

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
        _filter_field(
            "Started",
            DateRangePicker(
                label="Started",
                input_name_prefix="filter-started",
                min_value=started_min,
                max_value=started_max,
                path=["started"],
            ),
        ),
        _filter_field(
            "Finished",
            DateRangePicker(
                label="Finished",
                input_name_prefix="filter-ended",
                min_value=ended_min,
                max_value=ended_max,
                path=["ended"],
            ),
        ),
        _filter_field(
            "Days to Finish",
            NumberFilter(
                input_name_prefix="filter-days-to-finish",
                value=days.value,
                value2=days.value2,
                modifier=days.modifier,
                placeholder="e.g. 1",
                placeholder2="e.g. 30",
                path=["days_to_finish"],
            ),
        ),
    ]
    return fields


def StringFilter(
    input_name_prefix: str,
    value: str = "",
    modifier: str = "EQUALS",
    placeholder: str = "",
    *,
    path: FilterWidgetPath,
    compose: bool = False,
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
        attributes=[
            ("class", "flex flex-col gap-2 @container"),
            *filter_widget_attributes(path, "string", compose=compose),
        ],
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


# text-sm + px-3 py-2.5 match every other input (canonical size).
_NUMBER_FILTER_INPUT_CLASS = (
    "w-full rounded-base border border-default-medium px-3 py-2.5 text-sm "
    "bg-neutral-secondary-medium text-body focus:border-brand focus:ring-brand "
)


def NumberFilter(
    input_name_prefix: str,
    value: str = "",
    value2: str = "",
    modifier: str = "EQUALS",
    placeholder: str = "",
    placeholder2: str = "",
    step: str = "1",
    *,
    path: FilterWidgetPath,
    compose: bool = False,
) -> Node:
    """Renders a numeric filter with 8 modifier radio options and two inputs.

    Modeled 1:1 on :func:`StringFilter`. Both inputs are disabled for the
    presence modifiers (IS_NULL/NOT_NULL); the second input is shown only for
    the range modifiers (BETWEEN/NOT_BETWEEN). Initial state is server-rendered
    so the widget never flashes before its JS runs.
    """
    from common.criteria import Modifier

    if modifier not in [m.value for m in Modifier.for_numbers()]:
        modifier = "EQUALS"

    options = [
        ("EQUALS", "is"),
        ("NOT_EQUALS", "is not"),
        ("GREATER_THAN", "is greater than"),
        ("LESS_THAN", "is less than"),
        ("BETWEEN", "between"),
        ("NOT_BETWEEN", "not between"),
        ("IS_NULL", "is null"),
        ("NOT_NULL", "is not null"),
    ]

    radio_buttons = [
        Radio(
            name=f"{input_name_prefix}-modifier",
            label=lbl,
            checked=(modifier == mod_val),
            value=mod_val,
            attributes=[
                ("data-number-modifier-radio", ""),
            ],
        )
        for mod_val, lbl in options
    ]

    inputs_disabled = modifier in ("IS_NULL", "NOT_NULL")
    second_shown = modifier in ("BETWEEN", "NOT_BETWEEN")
    disabled_class = "opacity-50 cursor-not-allowed" if inputs_disabled else ""

    value_attrs = [
        ("name", input_name_prefix),
        ("value", value if not inputs_disabled else ""),
        ("placeholder", placeholder),
        ("step", step),
        ("class", _NUMBER_FILTER_INPUT_CLASS + disabled_class),
    ]
    if inputs_disabled:
        value_attrs.append(("disabled", "true"))

    value2_attrs = [
        ("name", f"{input_name_prefix}-value2"),
        ("value", value2 if not inputs_disabled else ""),
        ("placeholder", placeholder2),
        ("step", step),
        ("data-number-value2", ""),
        (
            "class",
            _NUMBER_FILTER_INPUT_CLASS
            + disabled_class
            + ("" if second_shown else " hidden"),
        ),
    ]
    if inputs_disabled:
        value2_attrs.append(("disabled", "true"))

    return Div(
        attributes=[
            ("class", "flex flex-col gap-2 @container"),
            *filter_widget_attributes(path, "number", compose=compose),
        ],
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
            Div(
                attributes=[("class", "flex items-center gap-2")],
                children=[
                    Input(type="number", attributes=value_attrs),
                    Input(type="number", attributes=value2_attrs),
                ],
            ),
        ],
    )
