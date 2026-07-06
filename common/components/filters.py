"""Stash-style filter bars, built from FilterSelect widgets."""

import json
from typing import Literal, NamedTuple

from django.db import models

from common.components.core import BaseComponent, Node, Safe
from common.components.custom_elements import (
    _FieldComparisonSet,
    _FilterBarElement,
    list_url_for,
)
from common.components.date_range_picker import DateRangePanel, DateRangePicker
from common.components.search_select import LoadPresetDropdown
from common.components.primitives import (
    A,
    Button,
    Checkbox,
    Div,
    FilterWidgetKind,
    FilterWidgetPath,
    Form,
    Input,
    Label,
    Option,
    Optgroup,
    Radio,
    RelationChild,
    Select,
    Span,
    ControlButton,
    Template,
    filter_widget_attributes,
)
from common.criteria import (
    SPACE_GROUPS,
    AttrName,
    ComparableColumn,
    ComparisonGranularity,
    FieldMeta,
    FieldMetaKind,
    OperatorFilter,
    comparable_columns,
    field_metadata,
)
from common.components.search_select import (
    DEFAULT_PREFETCH,
    FilterSelect,
    FilterSelectLayout,
    LabeledOption,
    OptionGroup,
    SearchSelect,
    SearchSelectOption,
)


def AdvancedFilterLink(*, url: str) -> Node:
    """An 'Advanced filter →' link into the nested builder page (#196).

    `url` is the fully-formed builder URL (already carrying ?filter= when the
    list currently has one). Rendered by each list view above its FilterBar."""
    return A(
        href=url,
        class_="inline-block mb-2 text-sm text-brand hover:underline",
    )["Advanced filter →"]


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
    except ValueError, TypeError:
        return {}


def parse_filter_dict(filter_json: str) -> dict:
    """Lenient ``?filter=`` JSON → dict parse (garbage → ``{}``) for bar prefill.

    The public face of ``_filter_parse``: list views call it once and hand the
    same dict to both the quick bar and the flat bar (``existing=``), instead of
    each bar re-parsing the identical string. All consumers treat the dict as
    read-only.
    """
    return _filter_parse(filter_json)


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
#
# Two producers write cross-entity sub-filters in DIFFERENT shapes (#137): the
# filter bar wraps each in its own ``AND`` element, while stats-links /
# ``filter_url`` emit them TOP-LEVEL (e.g. ``{"session_filter": {...}}``). Both
# are valid for ``to_q``, but the helpers below read only ``existing["AND"]``.
# ``_canonicalize_cross_entity`` folds the top-level shape into ``AND`` once (in
# ``_FilterBarBase.__init__``) so the helpers have a single canonical shape to
# read — the fix is concentrated in one place instead of every read helper.


def _canonicalize_cross_entity(existing: dict) -> dict:
    """Fold TOP-LEVEL cross-entity sub-filters into ``existing["AND"]`` (#137).

    Cross-entity relation sub-filters are the OperatorFilter ``*_filter`` fields
    (``session_filter``, ``purchase_filter``, ``game_filter``, …). When they
    arrive at the top level (stats-links / ``filter_url``) rather than wrapped in
    ``AND`` (the bar), the prefill helpers — which scan only ``existing["AND"]``
    — would miss them and render the matching widget blank, silently dropping the
    constraint on re-Apply. Each such top-level key is moved into its own ``AND``
    element (mirroring the bar's per-widget serialization), appended after any
    existing ``AND`` elements.

    Operator lists (``AND`` / ``OR`` / ``NOT``) and flat criterion keys are left
    untouched. Returns a shallow copy when anything moves; the raw ``filter_json``
    (re-serialized on Apply) is never touched, so ``to_q`` semantics are
    unchanged — only what prefill reads.
    """
    relation_keys = [
        key
        for key, value in existing.items()
        if key.endswith("_filter") and isinstance(value, dict)
    ]
    if not relation_keys:
        return existing
    canonical = {
        key: value for key, value in existing.items() if key not in relation_keys
    }
    and_elements = list(canonical.get("AND") or [])
    and_elements.extend({key: existing[key]} for key in relation_keys)
    canonical["AND"] = and_elements
    return canonical


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


def _bool_from_field(field: dict) -> bool | None:
    """Extract a nullable boolean from a criterion dict, defaulting to None.

    The blob-level counterpart of :func:`_parse_bool_nullable`, so ``field_widget``
    can prefill a bool control from a raw criterion blob the same way the other
    ``_*_from_field`` helpers serve their widgets.
    """
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


def _parse_bool_nullable(existing: dict, key: str) -> bool | None:
    """Extract a nullable boolean value from a filter criterion."""
    if key not in existing:
        return None
    return _bool_from_field(existing[key])


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
    layout: FilterSelectLayout = "field",
    search_aria_label: str = "",
) -> Node:
    """A FilterSelect over a small, fully pre-rendered option set (enum field).

    Enum fields are single-valued, so no M2M modifiers (all/only are
    meaningless); only the presence modifier is surfaced. ``path`` lets a
    cross-entity widget point at a nested sub-filter leaf (defaults to the
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
        layout=layout,
        search_aria_label=search_aria_label,
    )


def _model_filter(
    field_name: str,
    choice: FilterChoice,
    *,
    search_url,
    nullable,
    m2m_modifiers: list[LabeledOption] | None = None,
    path: FilterWidgetPath | None = None,
    layout: FilterSelectLayout = "field",
    search_aria_label: str = "",
) -> Node:
    """A FilterSelect backed by a search endpoint.

    Labels are embedded in the filter JSON (Stash-style), so pills render
    directly from ``choice`` with no DB round-trip. Pass ``m2m_modifiers`` for
    many-to-many fields to surface ``(All)`` / ``(Only)`` pseudo-options in the
    dropdown alongside the presence options. ``path`` lets a cross-entity widget
    point at a nested sub-filter leaf (defaults to the flat ``[field_name]``).
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
        layout=layout,
        search_aria_label=search_aria_label,
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
    return Div(class_="flex flex-col gap-1")[
        Label(label_attributes)[label],
        widget,
    ]


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
    # The relation-bool serializer branch builds and appends its own AND
    # element directly from ``data-relation-child``, so the generic
    # path-length cross-entity branch never applies here.
    return Div(
        filter_widget_attributes(
            path,
            kind,
            relation_child=relation_child,
        ),
        class_="flex flex-col gap-1",
    )[
        Span(class_=_FILTER_LABEL_CLASS)[label],
        Div(class_="flex items-center gap-4 h-9")[*_bool_radios(name, value)],
    ]


def _bool_radios(name: str, value: bool | None) -> list[Node]:
    """The True/False radio pair shared by the bar's bool widget and the leaf
    ``_bool_control``."""
    return [
        Radio(name=name, label="True", checked=value is True, value="true"),
        Radio(name=name, label="False", checked=value is False, value="false"),
    ]


def _bool_control(name: str, value: bool | None, *, path: FilterWidgetPath) -> Node:
    """Label-free bool value widget for ``field_widget`` (issue #242).

    Carries ``data-kind="bool"`` + ``data-path`` so the leaf serializer picks it up,
    holding only the True/False radios — the field label is the caller's concern
    (the #192 leaf row's field cell). The bars keep using ``_filter_boolean_radio``
    (self-labeled, in its own flex row), so their output is unchanged.
    """
    return Div(
        filter_widget_attributes(path, "bool"),
        class_="flex items-center gap-4 h-9",
    )[*_bool_radios(name, value)]


# ── field_widget: the single per-field value-widget builder (issue #242) ──────
# One dispatcher that returns a field's value control, keyed off the field's
# ``FieldMeta`` (kind / nullable / choices / search_url / is_m2m). It reuses the
# existing builders — no new markup. Both the flat bars and the #192 nested-builder
# leaf row clone the same widget from here, so a field is described once.


def _field_meta(filter_cls: type[OperatorFilter], field_name: AttrName) -> FieldMeta:
    for meta in field_metadata(filter_cls):
        if meta["name"] == field_name:
            return meta
    raise KeyError(f"{filter_cls.__name__} has no filterable field {field_name!r}")


def field_widget(
    filter_cls: type[OperatorFilter],
    field_name: AttrName,
    *,
    value: dict | None = None,
    path: FilterWidgetPath | None = None,
    name_prefix: str | None = None,
    field_name_override: str | None = None,
    label: str | None = None,
    placeholder: str = "",
    placeholder2: str = "",
    step: str = "1",
    layout: FilterSelectLayout = "field",
) -> Node:
    """Build a filter field's value control, dispatching by its ``FieldMeta`` kind.

    ``value`` is the field's raw criterion blob (the per-field JSON dict, e.g.
    ``existing[field_name]``); ``None`` → a blank widget (what #192 clones).
    ``path`` defaults to ``[field_name]`` (cross-entity callers pass the nested
    chain). ``name_prefix`` is the input id/name base for the **string/number/date/
    bool** branches (defaults to ``f"filter-{field_name}"``); the **set** branch
    ignores it and takes its DOM name from ``field_name_override or field_name``.
    It's kept caller-supplied because the bars' historic prefixes are arbitrary and
    #192 needs per-row-unique ids. ``field_name_override`` is the ``FilterSelect``
    identifier when it differs from the attr name (the two cross-entity enums whose
    DOM name is ``purchase_type`` / ``purchase_ownership_type``). ``label`` /
    ``placeholder`` / ``placeholder2`` / ``step`` are presentation hints the bars
    forward to match their existing literals; leaf callers omit them.

    Output matches the bars' old inline widgets except ``nullable`` is re-derived
    from the field's column (``FieldMeta``), not forwarded — so a field whose bar
    previously hard-coded a different ``nullable`` than its DB column changes its
    presence (``IS_NULL``) modifier. The one such field is the Game bar's
    cross-entity Device, now correctly nullable (matches the Session bar + the
    ``Session.device`` column).

    ``layout="panel"`` renders the set-kind ``FilterSelect`` in its panel
    personality (hosted inside a ``ComboboxDropdown``) and names its search
    input after the facet label. Only set fields have a panel form; any other
    kind raises — a silent ignore here would hide a wiring bug, since this is
    the shared dispatcher the bars and the nested builder both call.
    """
    meta = _field_meta(filter_cls, field_name)
    kind = meta["kind"]
    if kind == "relation":
        raise ValueError(
            f"{filter_cls.__name__}.{field_name} is a relation, not a leaf value field"
        )
    # Panel-hostable kinds: set gets the FilterSelect panel personality, date
    # the static-calendar DateRangePanel, and number embeds NumberFilter
    # unchanged — its stacked select-above-inputs layout (too tall inline,
    # #314) is exactly the natural shape inside a vertical dialog. string/bool
    # have no panel form yet and still raise.
    if layout == "panel" and kind not in ("set", "date", "number"):
        raise ValueError(
            f"field_widget: layout='panel' requires a set, date or number "
            f"field, but {filter_cls.__name__}.{field_name} is kind {kind!r}"
        )
    widget_path = path if path is not None else [field_name]
    prefix = name_prefix if name_prefix is not None else f"filter-{field_name}"
    blob = value if isinstance(value, dict) else {}

    if kind == "string":
        text = _string_from_field(blob)
        return StringFilter(
            prefix,
            value=text.value,
            modifier=text.modifier,
            placeholder=placeholder,
            path=widget_path,
        )
    if kind == "number":
        number = _number_from_field(blob)
        return NumberFilter(
            prefix,
            value=number.value,
            value2=number.value2,
            modifier=number.modifier,
            placeholder=placeholder,
            placeholder2=placeholder2,
            step=step,
            path=widget_path,
        )
    if kind == "date":
        bounds = _range_from_field(blob)
        date_builder = DateRangePanel if layout == "panel" else DateRangePicker
        return date_builder(
            label=label if label is not None else meta["label"],
            input_name_prefix=prefix,
            min_value=bounds.min,
            max_value=bounds.max,
            path=widget_path,
        )
    if kind == "bool":
        return _bool_control(prefix, _bool_from_field(blob), path=widget_path)
    if kind == "set":
        choice = _choice_from_raw(blob)
        select_name = field_name_override or field_name
        # In the panel personality the visible facet label lives on the
        # dropdown trigger, so the search input carries the accessible name.
        search_aria_label = (
            (label if label is not None else meta["label"]) if layout == "panel" else ""
        )
        if meta["search_url"]:
            return _model_filter(
                select_name,
                choice,
                search_url=meta["search_url"],
                nullable=meta["nullable"],
                m2m_modifiers=_M2M_MODIFIERS if meta["is_m2m"] else None,
                path=widget_path,
                layout=layout,
                search_aria_label=search_aria_label,
            )
        options = [
            (choice_meta["value"], choice_meta["label"])
            for choice_meta in meta["choices"]
        ]
        return _enum_filter(
            select_name,
            options,
            choice,
            nullable=meta["nullable"],
            path=widget_path,
            layout=layout,
            search_aria_label=search_aria_label,
        )
    raise ValueError(
        f"field_widget: unhandled kind {kind!r} for {filter_cls.__name__}.{field_name}"
    )


def field_widget_templates(
    filter_cls: type[OperatorFilter],
    *,
    model: str = "",
) -> dict[AttrName, Node]:
    """One blank value-widget ``<template>`` per non-relation leaf field, keyed by
    field name — what ``<filter-group>`` (#192) embeds and clones on field-pick. When
    ``model`` is given, each template is tagged ``data-model`` so the multi-model
    builder (#193) can bucket templates by the model whose child group they belong to."""
    return {
        meta["name"]: Template(_model_attr(model), data_field=meta["name"])[
            field_widget(filter_cls, meta["name"])
        ]
        for meta in field_metadata(filter_cls)
        if meta["kind"] != "relation"
    }


def _model_attr(model: str) -> dict[str, str]:
    """A dynamic ``data-model`` attribute (positional slot) for a template, or nothing
    when ``model`` is empty — so single-model flat callers render no ``data-model`` and
    their output is unchanged (#193)."""
    return {"data-model": model} if model else {}


_FILTER_FORM_ID = "filter-bar-form"


_FILTER_INPUT_ID = "filter-json-input"


def _filter_collapse_button() -> Node:
    # Slider handles are positioned in percentages, so initializing
    # them while the body is hidden is safe — no re-init on reveal.
    # Click is wired by filter-bar.ts (no inline handler).
    return Button(
        type="button",
        data_filter_bar_toggle="",
        class_=(
            "flex items-center gap-2 text-sm font-medium text-body "
            "hover:text-heading mb-2"
        ),
    )[
        Safe(
            '<svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M10.5 6h9.75M10.5 6a1.5 1.5 0 1 1-3 0m3 0a1.5 1.5 0 1 0-3 0M3.75 6H7.5m3 12h9.75m-9.75 0a1.5 1.5 0 0 1-3 0m3 0a1.5 1.5 0 0 0-3 0m-3.75 0H7.5m9-6h3.75m-3.75 0a1.5 1.5 0 0 1-3 0m3 0a1.5 1.5 0 0 0-3 0m-9.75 0h9.75" /></svg>'
        ),
        "Filters",
    ]


def _filter_action_row(*, preset_api_url: str, preset_mode: str) -> Node:
    return Div(class_="flex gap-3 items-center")[
        Button(
            type="submit",
            class_=(
                "px-4 py-2 text-sm font-medium text-white bg-brand "
                "rounded-lg hover:bg-brand-strong focus:ring-4 "
                "focus:ring-brand-medium"
            ),
        )["Apply"],
        Button(
            type="button",
            data_filter_bar_clear="",
            class_=(
                "px-4 py-2 text-sm font-medium text-gray-900 bg-white "
                "border border-gray-200 rounded-lg hover:bg-gray-100 "
                "dark:bg-gray-800 dark:border-gray-600 dark:text-gray-400 "
                "dark:hover:bg-gray-700 dark:hover:text-white"
            ),
        )["Clear"],
        Span(class_="flex gap-2 items-center", id_="save-preset-area")[
            Input(
                type="text",
                id_="preset-name-input",
                data_filter_bar_preset_name="",
                placeholder="Preset name...",
                class_=(
                    "hidden px-3 py-2 text-sm rounded-lg border "
                    "border-default-medium bg-neutral-secondary-medium "
                    "text-heading focus:ring-brand focus:border-brand"
                ),
            ),
            Button(
                type="button",
                id_="save-preset-btn",
                data_filter_bar_save="",
                class_=(
                    "px-4 py-2 text-sm font-medium text-gray-900 "
                    "bg-white border border-gray-200 rounded-lg "
                    "hover:bg-gray-100 dark:bg-gray-800 "
                    "dark:border-gray-600 dark:text-gray-400 "
                    "dark:hover:bg-gray-700 dark:hover:text-white"
                ),
            )["Save Preset"],
            Button(
                type="button",
                id_="confirm-save-preset-btn",
                data_filter_bar_confirm_save="",
                class_=(
                    "hidden px-4 py-2 text-sm font-medium text-white "
                    "bg-green-700 rounded-lg hover:bg-green-800 "
                    "focus:ring-4 focus:ring-green-300"
                ),
            )["Save"],
            Span(
                id_="preset-overwrite-warning",
                data_filter_bar_overwrite_warning="",
                class_="hidden text-sm text-red-500",
            )["A preset with this name exists — saving will overwrite it."],
        ],
        LoadPresetDropdown(
            api_url=preset_api_url, mode=preset_mode, id="bar-preset-picker"
        ),
    ]


# ── Field-to-field comparison widget (#167) ──────────────────────────────────
# A set of "left <op> right" rows comparing two columns of the bar's own model,
# combined by a single AND/OR mode toggle.  The dependent option lists (operator
# + right column react to the left column's group) and the row serialization live
# client-side in ts/elements/field-comparison-set.ts and filter-bar.ts.
#
# TODO(nested-builder, #168): the AND/OR mode toggle and the single-mode shapes
# are a stepping stone the nested boolean builder subsumes; the single-row markup
# (_field_comparison_row) is the permanent part it reuses inside a group node.


class FieldComparisonRow(NamedTuple):
    left: str  # left column name, e.g. "timestamp_end"
    right: str  # right column name, e.g. "timestamp_start"
    modifier: str  # a Modifier value, e.g. "LESS_THAN"
    granularity: ComparisonGranularity


def _fc_row_from_dict(raw: dict) -> FieldComparisonRow:
    # Unknown granularities coerce to "raw" (this parses a widget round-trip,
    # not untrusted filter JSON — that path raises in FieldComparisonCriterion
    # .from_json). Validated against SPACE_GROUPS, not a literal list, so a new
    # space is recognized here the moment it is added to the table.
    return FieldComparisonRow(
        left=str(raw.get("left", "")),
        right=str(raw.get("right", "")),
        modifier=str(raw.get("modifier") or "EQUALS"),
        granularity=(
            raw["granularity"] if raw.get("granularity") in SPACE_GROUPS else "raw"
        ),
    )


def _field_comparison_rows(existing: dict) -> tuple[list[FieldComparisonRow], str]:
    """Read saved comparison rows + mode from a parsed filter.

    Recognises the two shapes the widget emits (see filter-bar.ts): a top-level
    ``field_comparisons`` list (AND mode), or a single ``{"OR": [...]}`` element
    in the ``AND`` list whose entries each hold one ``field_comparisons`` (OR
    mode). AND wins if both are somehow present (a hand-edited degenerate case).
    Returns ``([], "AND")`` when neither is found.
    """
    raw_and = existing.get("field_comparisons")
    if isinstance(raw_and, list) and raw_and:
        rows = [_fc_row_from_dict(item) for item in raw_and if isinstance(item, dict)]
        if rows:
            return rows, "AND"
    for element in existing.get("AND", []) or []:
        if not isinstance(element, dict) or not isinstance(element.get("OR"), list):
            continue
        or_rows: list[FieldComparisonRow] = []
        for node in element["OR"]:
            if not isinstance(node, dict):
                continue
            inner = node.get("field_comparisons")
            if isinstance(inner, list) and inner and isinstance(inner[0], dict):
                or_rows.append(_fc_row_from_dict(inner[0]))
        if or_rows:
            return or_rows, "OR"
    return [], "AND"


def _pack_operator(modifier: str, granularity: str) -> str:
    """The operator ``<select>`` value: bare modifier in the raw comparison space,
    else ``modifier:granularity`` — mirrored by ``unpackOperator`` in
    ts/elements/field-comparison-set.ts."""
    return modifier if granularity == "raw" else f"{modifier}:{granularity}"


def _fc_column_options(columns: list[ComparableColumn], selected: str) -> list[Node]:
    """Left-column options, one ``<optgroup>`` per source.

    Every source (own model or FK) gets an ``<optgroup label=source>``
    wrapping its member options.  ``comparable_columns`` returns own columns
    first (with ``source`` set to the model's verbose name), so the order
    (own → related blocks) is stable without a secondary sort here.
    Empty groups are omitted."""
    options: list[Node] = [Option(value="")["column…"]]
    grouped: dict[str, list[ComparableColumn]] = {}
    for column in columns:
        grouped.setdefault(column["source"], []).append(column)
    for source, members in grouped.items():
        member_options: list[Node] = []
        for column in members:
            attributes = [("value", column["value"]), ("data-group", column["group"])]
            if column["value"] == selected:
                attributes.append(("selected", ""))
            member_options.append(Option(attributes)[column["label"]])
        options.append(Optgroup(label=source)[member_options])
    return options


def _field_comparison_row(
    columns: list[ComparableColumn],
    row: FieldComparisonRow | None,
    select_class: str,
) -> Node:
    """One ``left <op> right ✕`` row. ``row=None`` is the blank template row.

    The left column carries the full option set; the operator and right-column
    selects are rendered empty with the saved value stashed in ``data-selected``
    — ts/elements/field-comparison-set.ts builds their options from the left
    column's group and restores the selection. This is the reusable single-row
    unit (see TODO(nested-builder) above)."""
    left_value = row.left if row else ""
    operator_value = _pack_operator(row.modifier, row.granularity) if row else ""
    right_value = row.right if row else ""
    return Div(
        data_fc_row="",
        class_=("grid grid-cols-1 gap-2 items-center md:grid-cols-[1fr_auto_1fr_auto]"),
    )[
        Select(data_fc_left="", class_=select_class)[
            *_fc_column_options(columns, left_value)
        ],
        Select(data_fc_op="", data_selected=operator_value, class_=select_class),
        Select(data_fc_right="", data_selected=right_value, class_=select_class),
        Button(
            type="button",
            data_fc_remove="",
            aria_label="Remove comparison",
            class_="p-2 text-body hover:text-red-500 cursor-pointer",
        )["✕"],
    ]


def _fc_mode_toggle(mode: str) -> Node:
    return Div(class_="flex items-center gap-3")[
        Span(class_=_FILTER_LABEL_CLASS)["Match"],
        Radio(
            name="field-comparison-mode",
            label="All",
            value="AND",
            checked=(mode != "OR"),
            data_fc_mode="",
        ),
        Radio(
            name="field-comparison-mode",
            label="Any",
            value="OR",
            checked=(mode == "OR"),
            data_fc_mode="",
        ),
    ]


def FieldComparisonSet(
    *,
    columns: list[ComparableColumn],
    rows: list[FieldComparisonRow],
    mode: str,
) -> Node:
    """The field-comparison custom element: a mode toggle, the saved rows, a blank
    template row for client cloning, and an add button. ``columns`` is embedded as
    a JSON prop so the TS can build the dependent operator/right options."""
    import json

    from games.forms import SELECT_CLASS

    safe_mode = mode if mode in ("AND", "OR") else "AND"
    return _FieldComparisonSet(
        [
            *filter_widget_attributes(["field_comparisons"], "field-comparison"),
            ("class", "flex flex-col gap-3 mt-2"),
        ],
        columns=json.dumps(columns),
        mode=safe_mode,
    )[
        _fc_mode_toggle(safe_mode),
        Div(data_fc_rows="", class_="flex flex-col gap-2")[
            [_field_comparison_row(columns, row, SELECT_CLASS) for row in rows]
        ],
        Template(data_fc_row_template="")[
            _field_comparison_row(columns, None, SELECT_CLASS)
        ],
        ControlButton(color="gray", data_fc_add="", class_="self-start")[
            "+ Add comparison"
        ],
    ]


def comparison_row_template(
    columns: list[ComparableColumn], *, model: str = ""
) -> Node:
    """A blank field-comparison ``<template>`` for the nested builder (#246).

    The nested builder (``<filter-group>``) clones this into each comparison leaf's
    value cell, reusing the single-row widget — the *same* ``_field_comparison_row``
    markup ``FieldComparisonSet`` uses, minus the set container and its AND/OR mode
    toggle (the enclosing group owns the connective now). The row's own ``✕`` remove
    button is dropped client-side; the group's controls own removal. ``model`` tags the
    template ``data-model`` so the multi-model builder (#193) buckets it by model."""
    from games.forms import SELECT_CLASS

    return Template(data_fc_row_template="", **_model_attr(model))[
        _field_comparison_row(columns, None, SELECT_CLASS)
    ]


# Connective + NOT chips (component 2, issue #190), shipped to the nested builder
# as one ``<template data-chip-template="<state>">`` per visual state; the client
# clones the matching state and only wires behavior (#273). Pill shape
# (rounded-full) + saturated fill sets this cluster apart from the square, gray
# restructuring buttons so it never reads as "just another button". The connective
# is color-coded by value with a NON-semantic cool/warm pair — AND = teal, OR =
# orange — kept out of the action palette (blue/red/green/gray) so it reads as
# "logic type", not status. The NOT-on look uses an amber FILL + RING so a lit NOT
# chip stays distinct from an adjacent OR chip (fill-only) — they never read as
# one blob.
_CHIP_BASE_CLASS = (
    "rounded-full border px-2.5 py-0.5 text-xs font-semibold hover:cursor-pointer"
)

# A chip template's visual state, doubling as its data-chip-template tag; the
# client's ChipState mirrors it.
type ChipState = Literal["connective-and", "connective-or", "negate-off", "negate-on"]

_CHIP_STATE_CLASSES: dict[ChipState, str] = {
    "connective-and": (
        "border-teal-300 bg-teal-100 text-teal-800 "
        "dark:border-teal-500/60 dark:bg-teal-500/20 dark:text-teal-200"
    ),
    "connective-or": (
        "border-orange-300 bg-orange-100 text-orange-800 "
        "dark:border-orange-500/60 dark:bg-orange-500/20 dark:text-orange-200"
    ),
    "negate-off": (
        "border-gray-200 text-gray-500 hover:bg-gray-100 "
        "dark:border-gray-700 dark:text-gray-400 dark:hover:bg-gray-700"
    ),
    "negate-on": (
        "border-amber-400 bg-amber-100 text-amber-900 ring-1 ring-amber-400 "
        "dark:border-amber-500/70 dark:bg-amber-500/25 dark:text-amber-100 "
        "dark:ring-amber-500/70"
    ),
}

# No horizontal padding: @tailwindcss/forms styles bare <select> with
# appearance:none, a right-anchored chevron, and the right padding (~2.5rem) that
# clears it. A px-*/pr-* utility can't beat the plugin rule for the right side;
# px-* only overrides it symmetrically, shrinking it so the label ("any") ends up
# under the chevron. Set only vertical padding here.
_RELATION_SELECT_CLASS = (
    "rounded border border-gray-300 bg-white py-1 text-sm dark:border-gray-600 "
    "dark:bg-gray-800 disabled:opacity-50 disabled:cursor-not-allowed"
)


def chip_templates() -> list[Node]:
    """The nested builder's connective/NOT chip templates, one per state (#273).

    Each holds a blank chip ``<button>`` wearing that state's full class set; the
    client (``ts/elements/filter-group.ts``) clones the state it needs and sets
    only wiring attributes (label, action, path, title, aria-pressed) — chip
    styling is exclusively the server's concern. Model-agnostic, like the action
    button template."""
    return [
        Template(data_chip_template=state)[
            Button(type="button", class_=f"{_CHIP_BASE_CLASS} {state_class}")[""]
        ]
        for state, state_class in _CHIP_STATE_CLASSES.items()
    ]


def relation_select_template() -> Node:
    """The nested builder's quantifier/relation-field ``<select>`` template (#273).

    One blank styled ``<select>``; the client clones it for both the ANY/NONE/ALL
    quantifier picker and the relation-field picker, then appends its own
    ``<option>``s (they are data, not styling)."""
    return Template(data_relation_select_template="")[
        Select(class_=_RELATION_SELECT_CLASS)
    ]


def has_comparable_group(columns: list[ComparableColumn]) -> bool:
    """Whether ``columns`` admits at least one field comparison: some comparison
    group with ≥2 columns (a comparison needs two columns of the SAME group). The
    same gate ``_field_comparison_section`` uses to decide whether to show the flat
    bar's comparison field — reused so the builder's ``+ comparison`` affordance
    appears under identical conditions."""
    group_counts: dict[str, int] = {}
    for column in columns:
        group_counts[column["group"]] = group_counts.get(column["group"], 0) + 1
    return any(count >= 2 for count in group_counts.values())


def _field_comparison_section(
    existing: dict, model: type[models.Model] | None
) -> Node | None:
    """The labelled field-comparison field for a bar, or None when unavailable.

    Omitted when the bar's filter has no comparison model, or when no comparison
    group has at least two columns (a comparison needs two columns of the SAME
    group, so otherwise no valid row could be built)."""
    if model is None:
        return None
    columns = comparable_columns(model)
    if not has_comparable_group(columns):
        return None
    rows, mode = _field_comparison_rows(existing)
    return _filter_field(
        "Field comparisons",
        FieldComparisonSet(columns=columns, rows=rows, mode=mode),
    )


def _filter_search_field(existing: dict) -> Node:
    """The free-text search field: a text input plus an EXCLUDES toggle.

    Shared chrome rendered once at the top of every bar (see
    ``_FilterBarBase.render``). ``filter-bar.ts`` reads ``filter-search`` /
    ``filter-search-exclude`` by name into the search criterion; this is the
    server-rendered source of those controls (it replaces what was formerly
    imperative TypeScript DOM construction). ``INPUT_CLASS`` is imported here, not at
    module top, because ``games.forms`` imports ``common.components`` — a module
    import would be circular.
    """
    from games.forms import INPUT_CLASS

    value, modifier = _string_from_field(existing.get("search", {}))
    widget = Div(class_="mb-4")[
        Input(
            type="text",
            name="filter-search",
            value=value,
            placeholder="Search…",
            class_=INPUT_CLASS,
        ),
        Checkbox(
            name="filter-search-exclude",
            label="Exclude matches",
            checked=(modifier == "EXCLUDES"),
        ),
    ]
    return _filter_field("Search", widget)


class _FilterBarBase(BaseComponent):
    """Shared collapsible filter-bar chrome.

    Subclasses implement ``build_fields()`` returning the per-entity body
    (grids, sliders, checkboxes); this base wraps it in the collapse toggle,
    the form, the hidden filter-json input and the Apply/Clear/preset action
    row. ``filter-bar.js`` (declared via ``_FilterBarElement``) wires the
    chrome; widget media bubbles up from the contained widgets via the node
    tree, so the view never threads ``scripts=`` by hand.
    """

    # The FilterPreset.mode this bar scopes preset load/save to. Declared per
    # subclass — the bar knows its entity, so the client no longer sniffs it
    # out of window.location.pathname (#297).
    preset_mode = "games"

    def __init__(
        self,
        filter_json: str = "",
        preset_api_url: str = "",
        apply_url: str = "",
        existing: dict | None = None,
    ) -> None:
        self.filter_json = filter_json
        self.preset_api_url = preset_api_url
        # Where Apply/Clear/preset-pick navigates. Empty (the default, used by
        # every real view) derives the bar's own list URL from preset_mode at
        # render time; the explicit override exists for non-canonical mounts
        # (the synthetic e2e harnesses pass their own request.path) (#304).
        self.apply_url = apply_url
        # ``existing`` lets the view share one parse_filter_dict result with
        # the quick bar (both only read it); otherwise parse here.
        # Canonicalize TOP-LEVEL cross-entity sub-filters (stats-links /
        # filter_url) into the bar's AND shape so prefill reads a single shape
        # and stats-link landings pre-fill their widgets (#137).
        self.existing = _canonicalize_cross_entity(
            existing if existing is not None else _filter_parse(filter_json)
        )

    def build_fields(self) -> list:
        """Return the per-entity filter body. Implemented by each subclass."""
        raise NotImplementedError

    def comparison_model(self) -> type[models.Model] | None:
        """The model whose columns the field-comparison widget compares.

        None (the default) hides the widget; concrete bars override it to return
        their entity model, mirroring ``OperatorFilter._comparison_model``."""
        return None

    def _body_fields(self) -> list:
        """The per-entity fields plus the optional field-comparison section."""
        fields = list(self.build_fields())
        section = _field_comparison_section(self.existing, self.comparison_model())
        if section is not None:
            fields.append(section)
        return fields

    def render(self) -> Node:
        return _FilterBarElement(
            apply_url=self.apply_url or list_url_for(self.preset_mode),
            preset_api_url=self.preset_api_url,
            preset_mode=self.preset_mode,
        )[
            Div(id_="filter-bar", class_="mb-6")[
                _filter_collapse_button(),
                Div(
                    id_="filter-bar-body",
                    class_=(
                        "hidden border border-default-medium rounded-base p-4 "
                        "bg-neutral-secondary-medium/50"
                    ),
                )[
                    Form(id_=_FILTER_FORM_ID)[
                        Input(
                            type="hidden",
                            id_=_FILTER_INPUT_ID,
                            name="filter",
                            # NB: attribute values are escaped, so the
                            # raw JSON passes through (no double-escape).
                            value=self.filter_json,
                        ),
                        _filter_search_field(self.existing),
                        *self._body_fields(),
                        _filter_action_row(
                            preset_api_url=self.preset_api_url,
                            preset_mode=self.preset_mode,
                        ),
                    ],
                ],
            ]
        ]


class FilterBar(_FilterBarBase):
    """Collapsible filter bar for the Game list."""

    preset_mode = "games"

    def build_fields(self) -> list:
        return _game_fields(self.existing)

    def comparison_model(self) -> type[models.Model]:
        from games.models import Game

        return Game


def _game_fields(existing: dict) -> list:
    from games.filters import GameFilter, PurchaseFilter, SessionFilter

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
        Div(class_=_FILTER_GRID_CLASS)[
            _filter_field(
                "Status",
                field_widget(GameFilter, "status", value=existing.get("status")),
            ),
            _filter_field(
                "Platform",
                field_widget(GameFilter, "platform", value=existing.get("platform")),
            ),
            _filter_field(
                "Platform Group",
                field_widget(
                    GameFilter, "platform_group", value=existing.get("platform_group")
                ),
            ),
            _filter_field(
                "Device",
                # Cross-entity widgets serialize into existing["AND"] as independent
                # EXISTS sub-filters (#123 Phase 2d); prefill reads them back from
                # that list, matched by the same data-path the widget serializes to.
                field_widget(
                    SessionFilter,
                    "device",
                    value=_cross_entity_criterion(
                        existing, ["session_filter", "device"]
                    ),
                    path=["session_filter", "device"],
                ),
            ),
            _filter_field(
                "Purchase Type",
                # ``field_name_override`` keeps the flat DOM identifier
                # ("purchase_type") while ``path`` carries the nested leaf.
                field_widget(
                    PurchaseFilter,
                    "type",
                    value=_cross_entity_criterion(
                        existing, ["purchase_filter", "type"]
                    ),
                    path=["purchase_filter", "type"],
                    field_name_override="purchase_type",
                ),
            ),
            _filter_field(
                "Purchase Ownership",
                field_widget(
                    PurchaseFilter,
                    "ownership_type",
                    value=_cross_entity_criterion(
                        existing, ["purchase_filter", "ownership_type"]
                    ),
                    path=["purchase_filter", "ownership_type"],
                    field_name_override="purchase_ownership_type",
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
                ),
            ),
        ],
        Div(class_="flex items-end gap-6 mb-4 flex-wrap")[
            _filter_boolean_radio(
                "filter-mastered", "Mastered", mastered_value, path=["mastered"]
            ),
            _filter_boolean_radio(
                "filter-purchase-refunded",
                "Refunded",
                purchase_refunded_value,
                path=["purchase_filter"],
                relation_child={"is_refunded": {"value": True, "modifier": "EQUALS"}},
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
    ]
    return fields


def _find_label(options: list[LabeledOption], value: str) -> str:
    for v, label in options:
        if str(v) == str(value):
            return label
    return value


class SessionFilterBar(_FilterBarBase):
    """Collapsible filter bar for the Session list."""

    preset_mode = "sessions"

    def build_fields(self) -> list:
        return _session_fields(self.existing)

    def comparison_model(self) -> type[models.Model]:
        from games.models import Session

        return Session


def _session_fields(existing: dict) -> list:
    from games.filters import GameFilter, SessionFilter

    note_value = existing.get("note", {}).get("value", "")
    note_modifier = existing.get("note", {}).get("modifier", "EQUALS")

    dur_tot = _parse_number(existing, "duration_total_hours")
    dur_man = _parse_number(existing, "duration_manual_hours")
    dur_calc = _parse_number(existing, "duration_calculated_hours")
    emulated_value = _parse_bool_nullable(existing, "emulated")
    is_active_value = _parse_bool_nullable(existing, "is_active")

    fields = [
        Div(class_=_FILTER_GRID_CLASS)[
            _filter_field(
                "Game",
                field_widget(SessionFilter, "game", value=existing.get("game")),
            ),
            _filter_field(
                "Device",
                field_widget(SessionFilter, "device", value=existing.get("device")),
            ),
            _filter_field(
                "Platform",
                # Cross-entity: a session's platform lives on its game, so the
                # widget serializes into a game_filter EXISTS sub-filter. Prefill
                # reads it back from existing["AND"] by the same path.
                field_widget(
                    GameFilter,
                    "platform",
                    value=_cross_entity_criterion(
                        existing, ["game_filter", "platform"]
                    ),
                    path=["game_filter", "platform"],
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
        Div(class_="flex gap-6 mb-4")[
            _filter_boolean_radio(
                "filter-emulated", "Emulated", emulated_value, path=["emulated"]
            ),
            _filter_boolean_radio(
                "filter-active", "Active", is_active_value, path=["is_active"]
            ),
        ],
    ]
    return fields


class PurchaseFilterBar(_FilterBarBase):
    """Collapsible filter bar for the Purchase list."""

    preset_mode = "purchases"

    def build_fields(self) -> list:
        return _purchase_fields(self.existing)

    def comparison_model(self) -> type[models.Model]:
        from games.models import Purchase

        return Purchase


def _purchase_fields(existing: dict) -> list:
    from games.filters import PurchaseFilter

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
        Div(class_=_FILTER_GRID_CLASS)[
            _filter_field(
                "Game",
                # games is many-to-many on Purchase, so its FilterField declares
                # the search endpoint and field_widget surfaces (All)/(Only)
                # (INCLUDES_ALL / INCLUDES_ONLY) from the derived is_m2m flag.
                field_widget(PurchaseFilter, "games", value=existing.get("games")),
            ),
            _filter_field(
                "Platform",
                field_widget(
                    PurchaseFilter, "platform", value=existing.get("platform")
                ),
            ),
            _filter_field(
                "Type",
                field_widget(PurchaseFilter, "type", value=existing.get("type")),
            ),
            _filter_field(
                "Ownership",
                field_widget(
                    PurchaseFilter,
                    "ownership_type",
                    value=existing.get("ownership_type"),
                ),
            ),
            Div(class_=_FILTER_GRID_CLASS)[
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
                # Normalized to the canonical <date-range-picker> (was the bare
                # native DateRangeFilter) — same {prefix}-min/-max contract.
                DateRangePicker(
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
            Div(class_="flex flex-col items-start gap-4 mb-4")[
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
        ],
    ]
    return fields


class DeviceFilterBar(_FilterBarBase):
    """Collapsible filter bar for the Device list."""

    preset_mode = "devices"

    def build_fields(self) -> list:
        return _device_fields(self.existing)

    def comparison_model(self) -> type[models.Model]:
        from games.models import Device

        return Device


def _device_fields(existing: dict) -> list:
    from games.models import Device

    type_options = Device.DEVICE_TYPES
    type_choice = _filter_get_choice(existing, "type")

    fields = [
        Div(class_=_FILTER_GRID_CLASS)[
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
    ]
    return fields


class PlatformFilterBar(_FilterBarBase):
    """Collapsible filter bar for the Platform list."""

    preset_mode = "platforms"

    def build_fields(self) -> list:
        return _platform_fields(self.existing)

    def comparison_model(self) -> type[models.Model]:
        from games.models import Platform

        return Platform


def _platform_fields(existing: dict) -> list:
    name_value = existing.get("name", {}).get("value", "")
    name_modifier = existing.get("name", {}).get("modifier", "EQUALS")
    group_value = existing.get("group", {}).get("value", "")
    group_modifier = existing.get("group", {}).get("modifier", "EQUALS")

    fields = [
        Div(class_=_FILTER_GRID_CLASS)[
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
    ]
    return fields


class PlayEventFilterBar(_FilterBarBase):
    """Collapsible filter bar for the PlayEvent list."""

    preset_mode = "playevents"

    def build_fields(self) -> list:
        return _playevent_fields(self.existing)

    def comparison_model(self) -> type[models.Model]:
        from games.models import PlayEvent

        return PlayEvent


def _playevent_fields(existing: dict) -> list:
    game_choice = _filter_get_choice(existing, "game")
    days = _parse_number(existing, "days_to_finish")
    started_min, started_max = _parse_range(existing, "started")
    ended_min, ended_max = _parse_range(existing, "ended")

    fields = [
        Div(class_=_FILTER_GRID_CLASS)[
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
) -> Node:
    """Renders a string filter: a modifier ``<select>`` and a text input."""
    from common.criteria import Modifier
    from games.forms import SELECT_CLASS

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

    # A compact modifier dropdown (was an 8-radio grid): one control reads well both
    # in the flat bar and nested in the filter builder's tree.
    modifier_select = Select(
        [
            ("name", f"{input_name_prefix}-modifier"),
            ("data-string-modifier-select", ""),
            ("class", SELECT_CLASS),
        ]
    )[
        *[
            Option(value=mod_val, selected=(modifier == mod_val))[lbl]
            for mod_val, lbl in options
        ]
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
        filter_widget_attributes(path, "string"),
        class_="flex flex-col gap-2 @container",
    )[
        modifier_select,
        Input(input_attrs),
    ]


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
) -> Node:
    """Renders a numeric filter with 8 modifier radio options and two inputs.

    Modeled 1:1 on :func:`StringFilter`. Both inputs are disabled for the
    presence modifiers (IS_NULL/NOT_NULL); the second input is shown only for
    the range modifiers (BETWEEN/NOT_BETWEEN). Initial state is server-rendered
    so the widget never flashes before its JS runs.
    """
    from common.criteria import Modifier
    from games.forms import SELECT_CLASS

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

    modifier_select = Select(
        [
            ("name", f"{input_name_prefix}-modifier"),
            ("data-number-modifier-select", ""),
            ("class", SELECT_CLASS),
        ]
    )[
        *[
            Option(value=mod_val, selected=(modifier == mod_val))[lbl]
            for mod_val, lbl in options
        ]
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
        filter_widget_attributes(path, "number"),
        class_="flex flex-col gap-2 @container",
    )[
        modifier_select,
        Div(class_="flex items-center gap-2")[
            Input(value_attrs, type="number"),
            Input(value2_attrs, type="number"),
        ],
    ]


# ── Add-criterion field picker (issue #191, nested filter builder #168) ───────
# The searchable, grouped field combobox the nested filter builder's
# "+ condition" flow opens. It lists a model's leaf-criterion fields (relations
# are added via the separate relation picker, component 5/#193), grouped by
# criterion kind, and embeds each field's whole FieldMeta as JSON on its option
# so the client can reset the leaf's modifier/value on field change without a
# round-trip (see ts/elements/filter-tree). Built on the generic grouped
# SearchSelect; it carries a `data-field-picker` marker so a consumer scopes its
# `search-select:change` listener to this element.

# Human header per leaf kind. Ordered: the panel renders groups in this order.
# "field-comparison" is intentionally absent — those are list fields no single
# path resolves to, so field_metadata never emits a leaf of that kind.
KIND_GROUP_LABELS: dict[FieldMetaKind, str] = {
    "string": "Text",
    "number": "Number",
    "date": "Date",
    "bool": "Yes / No",
    "set": "Choice",
}


def _field_picker_option(meta: FieldMeta) -> SearchSelectOption:
    """One picker option carrying its field's whole FieldMeta as `data-meta`."""
    return {
        "value": meta["name"],
        "label": meta["label"],
        "data": {"meta": json.dumps(meta)},
    }


def _field_picker_groups(filter_cls: type[OperatorFilter]) -> list[OptionGroup]:
    """Group a filter's non-relation leaf fields by kind, in KIND_GROUP_LABELS
    order, preserving each field's declaration order within its group. Empty
    groups are dropped."""
    by_kind: dict[FieldMetaKind, list[SearchSelectOption]] = {
        kind: [] for kind in KIND_GROUP_LABELS
    }
    for meta in field_metadata(filter_cls):
        if meta["kind"] == "relation":
            continue
        bucket = by_kind.get(meta["kind"])
        if bucket is not None:
            bucket.append(_field_picker_option(meta))
    return [
        OptionGroup(label=KIND_GROUP_LABELS[kind], options=options)
        for kind, options in by_kind.items()
        if options
    ]


def FilterFieldPicker(
    filter_cls: type[OperatorFilter],
    *,
    id: str = "",
    placeholder: str = "Add condition…",
) -> Node:
    """A searchable, kind-grouped field combobox for ``filter_cls``'s leaf fields.

    Picking a field fires SearchSelect's ``search-select:change`` with the picked
    option's ``data-meta`` (the field's ``FieldMeta`` JSON); the consumer
    (#192 leaf row) resets the leaf via ``criterionForField`` in
    ``ts/elements/filter-tree``. Relation fields are excluded — they are added via
    the relation picker (#193). Inline (no ``search_url``): the field set is small
    and fully known at render, so filtering is client-side.

    Wrapped in a ``data-field-picker`` marker so a consumer scopes its
    ``search-select:change`` listener to this picker (the event bubbles from the
    inner ``<search-select>`` to the wrapper) — never a page-level listener that
    other comboboxes on the page would also trip.
    """
    return Div(data_field_picker="")[
        SearchSelect(
            name="field-picker",
            option_groups=_field_picker_groups(filter_cls),
            multi_select=False,
            placeholder=placeholder,
            id=id,
        )
    ]
