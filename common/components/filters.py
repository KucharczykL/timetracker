"""Filter widget layer: criterion-blob parse helpers, the per-kind value
widgets, and ``field_widget`` — the single dispatcher the quick filter bar
and the nested builder render every leaf field through."""

import json
from typing import Literal, NamedTuple


from common.components.core import Node
from common.components.date_range_picker import DateRangePanel, DateRangePicker
from common.components.primitives import (
    MICRO_LABEL_CLASS,
    Button,
    Div,
    FilterWidgetPath,
    Input,
    Option,
    Radio,
    Select,
    Template,
    filter_widget_attributes,
)
from common.criteria import (
    AttrName,
    ComparableColumn,
    ComparisonGranularity,
    FieldMeta,
    FieldMetaKind,
    OperatorFilter,
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


_FILTER_LABEL_CLASS = f"{MICRO_LABEL_CLASS} text-body"


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

    The public face of ``_filter_parse``: list views parse once and hand the
    dict to the quick bar (``existing=``). Consumers treat it as read-only.
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


def _range_from_field(field: dict) -> RangeValues:
    """Extract (min, max) from a range criterion dict, defaulting to ("", "")."""
    if not isinstance(field, dict):
        return RangeValues("", "")
    value = str(field.get("value", ""))
    if field.get("modifier") == "LESS_THAN":
        return RangeValues("", value)
    return RangeValues(value, str(field.get("value2", "")))


def _number_from_field(field: dict) -> NumberValues:
    """Extract (value, value2, modifier) from a numeric criterion dict."""
    if not isinstance(field, dict):
        return NumberValues("", "", "EQUALS")
    return NumberValues(
        str(field.get("value", "")),
        str(field.get("value2", "")),
        str(field.get("modifier") or "EQUALS"),
    )


def _string_from_field(field: dict) -> StringValues:
    """Extract (value, modifier) from a string criterion dict."""
    if not isinstance(field, dict):
        return StringValues("", "EQUALS")
    return StringValues(
        str(field.get("value", "")), str(field.get("modifier") or "EQUALS")
    )


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
# existing builders — no new markup. The quick bar and the nested-builder
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
    # Every leaf kind is panel-hostable: set gets the FilterSelect
    # panel personality, date the static-calendar DateRangePanel, and
    # number/string/bool embed their stacked widgets unchanged — the
    # select-above-inputs layout is the natural shape in a vertical dialog.
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


# ── Field-to-field comparison widget ──────────────────────────────────────────
# One "left <op> right" row comparing two columns of the builder's model — the
# comparison leaf rendered inside a builder group node (the enclosing group owns
# the AND/OR connective).  The dependent option lists (operator + right column
# react to the left column's group) and the row serialization live client-side
# in ts/elements/field-comparison-set.ts.


class FieldComparisonRow(NamedTuple):
    left: str  # left column name, e.g. "timestamp_end"
    right: str  # right column name, e.g. "timestamp_start"
    modifier: str  # a Modifier value, e.g. "LESS_THAN"
    granularity: ComparisonGranularity
    quantifier: str = (
        "ANY"  # RelationMatch value; used only when an operand is multi-valued (#282)
    )


# The quantifier <select> options for a multi-valued comparison (#282), mirroring
# the RelationMatch labels used by the relation-node picker.
_QUANTIFIER_OPTIONS: tuple[LabeledOption, ...] = (
    ("ANY", "any"),
    ("ALL", "all"),
    ("NONE", "none"),
)


def _pack_operator(modifier: str, granularity: str) -> str:
    """The operator ``<select>`` value: bare modifier in the raw comparison space,
    else ``modifier:granularity`` — mirrored by ``unpackOperator`` in
    ts/elements/field-comparison-set.ts."""
    return modifier if granularity == "raw" else f"{modifier}:{granularity}"


def _fc_option(column: ComparableColumn) -> SearchSelectOption:
    """A comparison operand as a SearchSelect option, carrying its comparison
    group and multi-valued flag as ``data-*`` the widget reads to gate operators
    and the quantifier (#282)."""
    return SearchSelectOption(
        value=column["value"],
        label=column["label"],
        data={
            "group": column["group"],
            "multivalued": "true" if column["multivalued"] else "false",
        },
    )


def _fc_option_groups(columns: list[ComparableColumn]) -> list[OptionGroup]:
    """Comparison operands grouped by ``source`` for a grouped SearchSelect panel.
    ``comparable_columns`` already orders own → FK → multi-valued blocks, so the
    groups render in that order without a re-sort."""
    grouped: dict[str, list[SearchSelectOption]] = {}
    for column in columns:
        grouped.setdefault(column["source"], []).append(_fc_option(column))
    return [
        OptionGroup(label=source, options=options)
        for source, options in grouped.items()
    ]


def _fc_operand(
    marker: str,
    *,
    name: str,
    columns: list[ComparableColumn],
    selected_value: str,
    dynamic: bool = False,
) -> Node:
    """A searchable operand combobox (SearchSelect) for one side of a comparison.

    The operand lists are now large enough (own + FK + multi-valued blocks) that a
    plain ``<select>`` is unusable, so each side is a single-select SearchSelect
    (#282 review). ``marker`` (``data-fc-left`` / ``data-fc-right``) tags the
    wrapper the widget queries by. The left side ships the full grouped option
    set; the right side ships none — ts/elements/field-comparison-set.ts
    repopulates it (via ``setOptions``) with the type/space-compatible columns for
    the chosen left column + operator. ``selected_value`` seeds a committed pick
    on the server hydration path (blank template row passes "")."""
    selected: list[SearchSelectOption] | None = None
    if selected_value:
        column = next((c for c in columns if c["value"] == selected_value), None)
        if column is not None:
            selected = [_fc_option(column)]
    return Div([(marker, "")])[
        SearchSelect(
            name=name,
            option_groups=_fc_option_groups(columns) if columns else None,
            selected=selected,
            multi_select=False,
            host_dropdown=True,
            placeholder="column…",
            dynamic_options=dynamic,
        )
    ]


def _field_comparison_row(
    columns: list[ComparableColumn],
    row: FieldComparisonRow | None,
    select_class: str,
) -> Node:
    """One ``left <op> right ✕`` row. ``row=None`` is the blank template row.

    Left and right operands are searchable SearchSelect comboboxes; the operator
    and quantifier stay plain ``<select>``s (short lists). The operator/quantifier
    saved values are stashed in ``data-selected`` — ts/elements/field-comparison-set.ts
    builds the operator options from the left column's group, repopulates the
    right combobox, and restores selections. This is the reusable single-row
    unit."""
    left_value = row.left if row else ""
    operator_value = _pack_operator(row.modifier, row.granularity) if row else ""
    right_value = row.right if row else ""
    quantifier_value = row.quantifier if row else ""
    return Div(
        data_fc_row="",
        class_=("grid grid-cols-1 gap-2 items-center md:grid-cols-[1fr_auto_1fr_auto]"),
    )[
        # Left carries the full grouped option set; right is repopulated client-side.
        _fc_operand(
            "data-fc-left", name="fc-left", columns=columns, selected_value=left_value
        ),
        # Operator + quantifier share one cell so the row keeps its 4-column
        # alignment; the quantifier is hidden until an operand is multi-valued
        # (#282), toggled by ts/elements/field-comparison-set.ts.
        Div(class_="flex gap-2 items-center")[
            Select(data_fc_op="", data_selected=operator_value, class_=select_class),
            Select(
                data_fc_quantifier="",
                data_selected=quantifier_value,
                aria_label="Quantifier",
                class_=f"hidden {select_class}",
            )[
                # Selection is restored client-side from ``data-selected`` (like the
                # operator select), so the options render unmarked.
                *(Option(value=value)[label] for value, label in _QUANTIFIER_OPTIONS)
            ],
        ],
        _fc_operand(
            "data-fc-right",
            name="fc-right",
            columns=[],
            selected_value=right_value,
            dynamic=True,
        ),
        Button(
            type="button",
            data_fc_remove="",
            aria_label="Remove comparison",
            class_="p-2 text-body hover:text-red-500 cursor-pointer",
        )["✕"],
    ]


def comparison_row_template(
    columns: list[ComparableColumn], *, model: str = ""
) -> Node:
    """A blank field-comparison ``<template>`` for the nested builder (#246).

    The nested builder (``<filter-group>``) clones this into each comparison
    leaf's value cell (``_field_comparison_row``); the enclosing group owns the
    connective. The row's own ``✕`` remove button is dropped client-side — the
    group's controls own removal. ``model`` tags the template ``data-model`` so
    the multi-model builder buckets it by model."""
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
_CHIP_BASE_CLASS = "rounded-full border px-2.5 py-0.5 text-type-micro font-semibold hover:cursor-pointer"

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
    "rounded border border-gray-300 bg-white py-1 text-type-input dark:border-gray-600 "
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
    group with ≥2 columns (a comparison needs two columns of the SAME group).
    Gates whether the builder emits a comparison-row template for a model —
    mirrored client-side by ts/elements/filter-group.ts, so the ``+ comparison``
    affordance appears under identical conditions."""
    group_counts: dict[str, int] = {}
    for column in columns:
        group_counts[column["group"]] = group_counts.get(column["group"], 0) + 1
    return any(count >= 2 for count in group_counts.values())


def _find_label(options: list[LabeledOption], value: str) -> str:
    for v, label in options:
        if str(v) == str(value):
            return label
    return value


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

    # A compact modifier dropdown: one control reads well both as a quick-bar
    # facet and nested in the filter builder's tree.
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
            # text-type-input + px-3 min-h-control match every input (canonical height).
            "w-full rounded-base border border-default-medium px-3 min-h-control text-type-input "
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


# text-type-input + px-3 min-h-control match every input (canonical height).
_NUMBER_FILTER_INPUT_CLASS = (
    "w-full rounded-base border border-default-medium px-3 min-h-control text-type-input "
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
            # Host in <drop-down behavior="inline-combobox"> like every other
            # combobox (issue #348). Cloned per leaf row by <filter-group>'s
            # buildFieldCell, exactly as the set value widgets are — attachMenu
            # owns open/close/positioning (fixed + flip, escaping the row's
            # overflow/stacking context).
            host_dropdown=True,
        )
    ]
