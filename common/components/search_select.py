"""Search field + dropdown select component (pure Python, domain-agnostic).

Pairs a search box with a dropdown of options. Supports single/multi select;
in multi-select, chosen items render as removable ``Pill``s, each backed by a
hidden ``<input>`` so an existing ``ModelMultipleChoiceField`` keeps validating.

This module imports only from ``common.components`` — it has no Django-forms or
``games`` knowledge. Styling is inline Tailwind utilities; behavioural hooks are
``data-*`` attributes wired up by ``ts/search_select.ts`` (compiled to
``games/static/js/dist/search_select.js``).

**Field id / label association**: when ``SearchSelect`` is used as a Django form
widget, the field ``id`` (e.g. ``id_related_game``) is placed on the inner
search ``<input>`` (``[data-search-select-search]``), making it a real labelable
control. ``<label for="id_X">`` therefore focuses the search box, and
``document.querySelector('#id_X').disabled`` behaves as for a native input.

**Disabling**: set ``disabled`` directly on the field id (or on the inner
``[data-search-select-search]`` input). The wrapper greys itself via the
``has-[:disabled]:`` utilities in ``_CONTAINER_CLASS``. The inner input stays
transparent — the widget reads as one faded element, not a nested box. Callers
toggle only the control's ``disabled`` — never styles.

**ARIA combobox semantics** (issue #154): the search input is a
``role="combobox"`` with ``aria-expanded``/``aria-autocomplete``; the options
panel is a ``role="listbox"`` (``aria-multiselectable`` when multi); option and
modifier rows are ``role="option"`` with ``aria-selected``. The id-based wiring
(``aria-controls`` on the input, stable ``id``s on the panel and rows, and
``aria-activedescendant`` tracking the keyboard highlight) is assigned by the
JS at init — never server-side, because the nested filter builder clones whole
``<search-select>`` prototypes and server-rendered ids would be duplicated
across clones.

Option sourcing follows two axes. *Population*: options are either rendered
inline up front (``options=``, no ``search_url``) or fetched from ``search_url``.
*Completeness*: without a ``search_url`` the inline set is the whole dataset and
filtering is purely client-side; with a ``search_url`` the loaded rows are a
window, so the JS filters the loaded rows instantly on each keystroke while
issuing a debounced server request for the rest. ``prefetch`` (rows to load on
first open, ``0`` = none) seeds that window so the panel is populated before the
user types.
"""

from collections.abc import Callable, Iterable, Sequence
from typing import NamedTuple, TypedDict


from common.components.core import Attributes, HTMLAttribute, Node
from common.components.custom_elements import _SearchSelect
from common.components.primitives import (
    DISABLED_WITHIN_CLASS,
    Button,
    Div,
    FilterWidgetPath,
    Input,
    Pill,
    Span,
    Template,
    filter_widget_attributes,
)


class SearchSelectOption(TypedDict):
    value: str | int
    label: str
    # Becomes data-* attrs on the row / pill. Values are str only, matching the
    # TS SearchSelectOption's Record<string, string> — producers stringify ids.
    data: dict[str, str]


# A lightweight (value, label) pair used wherever only those two fields are
# needed — e.g. filter pill lists and modifier pseudo-options. The richer
# SearchSelectOption adds a ``data`` dict for extra row attributes.
LabeledOption = tuple[str, str]


class OptionGroup(NamedTuple):
    """A labelled run of options for a grouped single-select panel.

    Passed as ``SearchSelect(option_groups=[...])`` (mutually exclusive with
    ``options=``); the widget renders a non-selectable header row before each
    group's option rows. Used by the filter builder's add-criterion field picker
    (#191), which groups fields by criterion kind.
    """

    label: str
    options: list[SearchSelectOption]


# The pills and the search box share one flex-wrap row (with padding) so the
# widget reads as a single clickable field; the pills wrapper uses `contents`
# so its pills/hidden inputs flow as direct participants of that row, inline
# with the search input. The options panel is absolute, so it sits outside the
# flex flow.
# Border + focus styling mirror a native input (INPUT_CLASS): border-default-medium
# normally, brand border + ring on focus. The search input is the focusable
# element, so the focus state is expressed on the wrapper with focus-within: (and
# the inner input suppresses its own ring — see _SEARCH_CLASS).
# The widget owns its disabled appearance: when any control inside it is
# :disabled (e.g. add_purchase.ts disabling the search input), the wrapper fades
# via :has() — the same opacity-50 a disabled native input uses (see
# _DISABLED_CONTROL in games/forms.py), so the two look identical. Callers only
# toggle the control's `disabled`, never styles.
# px-3 py-2.5 text-sm match a native input (INPUT_CLASS); the wrapper supplies
# the field padding, and the inner search box zeroes its own (p-0) so the two
# don't stack into a too-tall field.
_CONTAINER_CLASS = (
    "relative flex flex-wrap items-center gap-1 px-3 py-2.5 rounded-base text-sm "
    "bg-neutral-secondary-medium border border-default-medium "
    "focus-within:border-brand focus-within:ring-1 focus-within:ring-brand "
    f"{DISABLED_WITHIN_CLASS}"
)
_PILLS_CLASS = "contents"
# disabled:cursor-not-allowed matches the wrapper's cursor so hovering across
# the whole widget stays consistent (the wrapper handles the faded look via
# has-[:disabled]:opacity-50).
_SEARCH_CLASS = (
    "flex-1 min-w-[8rem] border-0 p-0 bg-transparent text-sm text-heading "
    "focus:ring-0 focus:outline-hidden placeholder:text-body "
    "disabled:cursor-not-allowed"
)
# top-full anchors the panel to the container's bottom edge: as an absolutely
# positioned child of the flex field, its static position would otherwise be
# centered by items-center and overlap the search box.
_OPTIONS_CLASS = (
    "absolute z-10 top-full left-0 right-0 mt-1 overflow-y-auto "
    "border border-default-medium rounded-base bg-neutral-secondary-medium shadow-lg"
)
_OPTION_ROW_CLASS = (
    "px-3 py-2 text-sm text-heading cursor-pointer "
    "hover:bg-brand-soft data-[search-select-highlighted]:bg-brand-soft"
)
_NO_RESULTS_CLASS = "px-3 py-2 text-sm italic text-body hidden"
# A non-selectable group header in a grouped panel. role="presentation" keeps it
# out of the combobox's option semantics; carrying no data-search-select-option
# excludes it from keyboard nav, client-side filtering, and selection. The JS
# hides a header whose whole run of following option rows is filtered out.
_GROUP_HEADER_CLASS = (
    "px-3 pt-2 pb-1 text-xs font-semibold uppercase tracking-wide text-body"
)

# Approximate rendered height of one option row (px-3 py-2 text-sm) in rem,
# used to derive the panel's max-height from items_visible.
_ROW_HEIGHT_REM = 2.25

# Default number of rows to fetch on first focus when a search_url is set.
# Shared by filter and form widgets so the dropdown is populated for keyboard
# navigation as soon as the user opens it.
DEFAULT_PREFETCH = 20

# ── FilterSelect styling ───────────────────────────────────────────────────
# Inline class strings (ported verbatim from the retired SelectableFilter CSS)
# so the filter combobox is fully self-styled — nothing in input.css. JS-added
# rows/pills are cloned from server-rendered <template>s, so these strings live
# only here — never duplicated in ts/search_select.ts. The keyboard-highlighted
# state is expressed via Tailwind `data-[search-select-highlighted]` and
# `group-data-[search-select-highlighted]` variants on the row/label/button
# classes below; the JS only toggles the data attribute on the row.
_FILTER_INCLUDE_PILL_CLASS = (
    "inline-flex items-center gap-1 px-2 py-0.5 text-sm rounded "
    "bg-brand-soft text-heading"
)
_FILTER_EXCLUDE_PILL_CLASS = (
    "inline-flex items-center gap-1 px-2 py-0.5 text-sm rounded "
    "bg-red-500/15 text-red-600 line-through decoration-red-400"
)
_FILTER_MODIFIER_PILL_CLASS = (
    "inline-flex items-center px-2 py-0.5 text-sm rounded "
    "bg-amber-500/15 text-amber-600 cursor-pointer"
)
_FILTER_PILL_REMOVE_CLASS = "ml-1 text-body hover:text-heading font-bold cursor-pointer"
_FILTER_OPTION_ROW_CLASS = (
    "group flex items-center justify-between px-2 py-1 rounded text-sm "
    "hover:bg-neutral-secondary-strong cursor-pointer "
    "data-[search-select-highlighted]:bg-brand "
    "data-[search-select-highlighted]:outline data-[search-select-highlighted]:outline-1 "
    "data-[search-select-highlighted]:outline-brand-strong"
)
_FILTER_OPTION_LABEL_CLASS = (
    "truncate text-body group-data-[search-select-highlighted]:text-white"
)
_FILTER_OPTION_BUTTONS_CLASS = "flex gap-1 ml-2 shrink-0"
# text-body keeps the +/− readable on dark backgrounds; hover:border-brand-strong
# keeps the edge visible against the brand hover fill. When the row is the
# keyboard-highlighted one its bg is brand, so the button text/border switch
# to white and the hover fill shifts to brand-strong for contrast.
_FILTER_ACTION_BUTTON_CLASS = (
    "w-5 h-5 flex items-center justify-center text-xs font-bold rounded text-body "
    "border border-brand "
    "hover:bg-brand hover:text-white hover:border-brand-strong "
    "group-data-[search-select-highlighted]:text-white "
    "group-data-[search-select-highlighted]:border-white "
    "group-data-[search-select-highlighted]:hover:bg-brand-strong "
    "group-data-[search-select-highlighted]:hover:border-white"
)
_FILTER_MODIFIER_ROW_CLASS = (
    "px-2 py-1 text-sm text-body hover:bg-neutral-secondary-strong cursor-pointer"
)


def _normalize_option(option) -> SearchSelectOption:
    """Coerce a dict option or a ``(value, label)`` tuple into the TypedDict."""
    if isinstance(option, dict):
        return {
            "value": option["value"],
            "label": option["label"],
            "data": option.get("data") or {},
        }
    value, label = option
    return {"value": value, "label": label, "data": {}}


def _data_attributes(data: dict[str, str]) -> list[HTMLAttribute]:
    return [(f"data-{key}", value) for key, value in data.items()]


def _hidden_input(name: str, value) -> Node:
    return Input(type="hidden", name=name, value=str(value))


def _label_slot(text: str, *, extra_class: str = "") -> Node:
    """A ``<span data-search-select-label>`` holding a row/pill's visible label. JS fills this
    one node when cloning the shape from a ``<template>``, so labels are the only
    thing the JS sets — all classes and structure stay server-side."""
    return Span(data_search_select_label="", class_=extra_class or None)[text]


# A placeholder option for rendering template prototypes (JS overwrites it).
_BLANK_OPTION: SearchSelectOption = {"value": "", "label": "", "data": {}}


def _option_row(option: SearchSelectOption) -> Node:
    return Div(
        _data_attributes(option["data"]),
        data_search_select_option="",
        data_value=str(option["value"]),
        data_label=option["label"],
        role="option",
        aria_selected="false",
        class_=_OPTION_ROW_CLASS,
    )[_label_slot(option["label"])]


def _group_header(label: str) -> Node:
    return Div(
        data_search_select_group_header="",
        role="presentation",
        class_=_GROUP_HEADER_CLASS,
    )[label]


def _grouped_option_rows(groups: list[OptionGroup]) -> list[Node]:
    """Flatten groups into header + option-row nodes for the options panel."""
    rows: list[Node] = []
    for group in groups:
        rows.append(_group_header(group.label))
        rows.extend(_option_row(_normalize_option(option)) for option in group.options)
    return rows


def _combobox_children(
    *,
    pills: Node,
    search_attributes: Attributes,
    options_children: list[Node],
    always_visible: bool,
    items_visible: int,
    multi_select: bool = False,
    templates: list[Node] | None = None,
) -> list[Node]:
    """Build and return the shared combobox interior nodes.

    Returns the three content regions (pills, search box, options panel) plus
    any templates — ready to be placed as children of the caller's container
    element. The shell knows nothing about how individual rows or pills look.

    The shell owns the ARIA combobox pattern (issue #154): the search input is
    the combobox, the options panel the listbox. ``aria-controls`` /
    ``aria-activedescendant`` and the ids they reference are wired by the JS at
    init (see module docstring); the JS also keeps ``aria-expanded`` in sync
    with the panel's visibility.
    """
    aria_attributes: list[HTMLAttribute] = [
        ("role", "combobox"),
        ("aria-expanded", "true" if always_visible else "false"),
        ("aria-autocomplete", "list"),
    ]
    search = Input([*search_attributes, *aria_attributes])

    # role="presentation" keeps the message node from being exposed as a
    # (non-option) child of the listbox.
    no_results = Div(
        data_search_select_no_results="",
        role="presentation",
        class_=_NO_RESULTS_CLASS,
    )["No results"]
    options_class = _OPTIONS_CLASS if always_visible else _OPTIONS_CLASS + " hidden"
    options_panel = Div(
        data_search_select_options="",
        role="listbox",
        aria_multiselectable="true" if multi_select else None,
        # Keep the scroller out of the sequential tab order. Chrome makes any
        # overflowing scroll container keyboard-focusable by default, which
        # would steal focus from the search input on Tab (issue #119).
        tabindex="-1",
        style=f"max-height: {items_visible * _ROW_HEIGHT_REM:.2f}rem",
        class_=options_class,
    )[*options_children, no_results]

    return [pills, search, options_panel, *(templates or [])]


def SearchSelect(
    *,
    name: str,
    selected: list[SearchSelectOption] | None = None,
    options: list[SearchSelectOption] | None = None,
    option_groups: list[OptionGroup] | None = None,
    search_url: str = "",
    multi_select: bool = False,
    always_visible: bool = False,
    items_visible: int = 5,
    items_scroll: int = 10,
    prefetch: int = 0,
    placeholder: str = "Search…",
    id: str = "",
    sync_url: bool = False,
    autofocus: bool = False,
) -> Node:
    """Render the search-select widget. See module docstring for the contract.

    Pass ``option_groups`` instead of ``options`` to render a grouped panel
    (non-selectable header rows before each group's options); the two are mutually
    exclusive and grouping is only meaningful for the inline (no ``search_url``)
    complete-set case.
    """
    if options and option_groups:
        raise ValueError("SearchSelect takes options or option_groups, not both")
    selected = [_normalize_option(option) for option in (selected or [])]
    options = [_normalize_option(option) for option in (options or [])]

    # ── Pills + their hidden inputs (the submitted channel) ──
    # Multi-select renders a removable Pill per value; single-select renders no
    # pill — the committed label shows inside the search box instead, with a
    # lone hidden input carrying the value. Both keep the hidden input(s) inside
    # `[data-search-select-pills]` so the JS reads/writes values uniformly.
    pills_children: list[Node] = []
    search_value = ""
    if multi_select:
        for option in selected:
            pills_children.append(
                Pill(
                    _data_attributes(option["data"]),
                    label=option["label"],
                    value=str(option["value"]),
                    removable=True,
                    label_slot=True,
                )
            )
            pills_children.append(_hidden_input(name, option["value"]))
    elif selected:
        option = selected[0]
        pills_children.append(_hidden_input(name, option["value"]))
        search_value = option["label"]

    pills = Div(data_search_select_pills="", class_=_PILLS_CLASS)[*pills_children]

    # ── Search box (NO name — the query is never submitted) ──
    search_attrs: list[HTMLAttribute] = [
        ("data-search-select-search", ""),
        ("placeholder", placeholder),
        ("autocomplete", "off"),
        ("class", _SEARCH_CLASS),
    ]
    if id:
        search_attrs.append(("id", id))
    if autofocus:
        search_attrs.append(("autofocus", ""))
    if search_value:
        search_attrs.append(("value", search_value))

    # ── Options panel (pre-rendered only when there is no search_url) ──
    if search_url:
        option_rows: list[Node] = []
    elif option_groups:
        option_rows = _grouped_option_rows(option_groups)
    else:
        option_rows = [_option_row(option) for option in options]

    # ── Templates the JS clones: a row when results are fetched, a pill when
    #    multi-select adds chosen items. ──
    templates: list[Node] = []
    if search_url:
        templates.append(
            Template(data_search_select_template="row")[_option_row(_BLANK_OPTION)]
        )
    if multi_select:
        templates.append(
            Template(data_search_select_template="pill")[
                Pill(label="", value="", removable=True, label_slot=True)
            ]
        )

    children = _combobox_children(
        pills=pills,
        search_attributes=search_attrs,
        options_children=option_rows,
        always_visible=always_visible,
        items_visible=items_visible,
        multi_select=multi_select,
        templates=templates,
    )
    return _SearchSelect(
        name=name,
        search_url=search_url,
        multi="true" if multi_select else "false",
        filter_mode="false",
        free_text="false",
        always_visible="true" if always_visible else "false",
        prefetch=prefetch,
        sync_url="true" if sync_url else "false",
        class_=_CONTAINER_CLASS,
    )[*children]


def _filter_remove_button() -> Node:
    return Button(
        type="button",
        data_pill_remove="",
        class_=_FILTER_PILL_REMOVE_CLASS,
        aria_label="Remove",
    )["×"]


def _filter_value_pill(option: SearchSelectOption, kind: str) -> Node:
    """An include (✓) or exclude (✗) value pill. ``kind`` is "include"/"exclude"."""
    symbol = "✓" if kind == "include" else "✗"
    css = (
        _FILTER_INCLUDE_PILL_CLASS if kind == "include" else _FILTER_EXCLUDE_PILL_CLASS
    )
    return Span(
        _data_attributes(option["data"]),
        class_=css,
        data_pill="",
        data_value=str(option["value"]),
        data_label=option["label"],
        data_search_select_type=kind,
    )[f"{symbol} ", _label_slot(option["label"]), _filter_remove_button()]


def _filter_modifier_pill(modifier_value: str, label: str) -> Node:
    """The lone, sticky modifier pill (e.g. "(Any)"/"(None)")."""
    return Span(
        class_=_FILTER_MODIFIER_PILL_CLASS,
        data_pill="",
        data_search_select_modifier=modifier_value,
    )[_label_slot(label), _filter_remove_button()]


def _filter_action_button(action: str, symbol: str, title: str) -> Node:
    return Button(
        type="button",
        # Include (+) is reachable via row highlight + Enter; both +/− are
        # reachable by mouse. Keep every per-row button out of the
        # sequential tab order (issue #119).
        tabindex="-1",
        data_search_select_action=action,
        class_=_FILTER_ACTION_BUTTON_CLASS,
        title=title,
    )[symbol]


def _filter_option_row(value: str | int, label: str) -> Node:
    """A value row with include (+) and exclude (−) buttons."""
    return Div(
        data_search_select_option="",
        data_value=str(value),
        data_label=label,
        role="option",
        aria_selected="false",
        class_=_FILTER_OPTION_ROW_CLASS,
    )[
        _label_slot(label, extra_class=_FILTER_OPTION_LABEL_CLASS),
        Span(class_=_FILTER_OPTION_BUTTONS_CLASS)[
            _filter_action_button("include", "+", "Include"),
            _filter_action_button("exclude", "−", "Exclude"),
        ],
    ]


def _filter_modifier_row(modifier_value: str, label: str) -> Node:
    """A pinned pseudo-option row. It carries no ``data-search-select-option`` so the text
    filter never hides it — modifiers stay visible at the top of the panel.

    Carries ``role="option"`` so the listbox only exposes option/presentation
    children; it is mouse-only, so ``aria-activedescendant`` never points at it
    and its ``aria-selected`` stays false."""
    return Div(
        data_search_select_modifier_option=modifier_value,
        data_label=label,
        role="option",
        aria_selected="false",
        class_=_FILTER_MODIFIER_ROW_CLASS,
    )[label]


def FilterSelect(
    *,
    field_name: str,
    options: Sequence[LabeledOption | SearchSelectOption] | None = None,
    included: Sequence[LabeledOption | SearchSelectOption] | None = None,
    excluded: Sequence[LabeledOption | SearchSelectOption] | None = None,
    modifier: str = "",
    modifier_options: list[LabeledOption] | None = None,
    search_url: str = "",
    prefetch: int = 0,
    items_visible: int = 6,
    items_scroll: int = 10,
    placeholder: str = "Search…",
    id: str = "",
    free_text: bool = False,
    path: FilterWidgetPath | None = None,
) -> Node:
    """Include/exclude filter combobox built on the shared ``_combobox_shell``.

    Like ``SearchSelect`` but each value row carries +/− buttons that add an
    *include* (✓) or *exclude* (✗) pill, plus an optional set of pinned
    ``modifier_options`` (e.g. ``[("NOT_NULL", "(Any)"), ("IS_NULL", "(None)")]``)
    rendered above the value rows. Presence modifiers (NOT_NULL / IS_NULL) are
    mutually exclusive with value pills. Non-presence modifiers (INCLUDES_ALL /
    INCLUDES_ONLY) coexist with value pills — they govern how the include set
    matches and are only surfaced for many-to-many fields. State is read from
    the DOM into the filter JSON by ``readSearchSelect`` (filter mode) — nothing
    is submitted by ``name``.

    ``included``/``excluded`` are resolved options (value + label) so pills show
    labels even when the value rows come from ``search_url``. ``options``
    pre-renders the value rows for the complete-set (no ``search_url``) case.

    ``free_text`` turns the widget into a typed-pill input: there is no backing
    option list, the JS builds an ephemeral option row from whatever the user
    types so the +/− buttons (and Enter) commit the typed string itself as an
    include / exclude pill.
    """
    normalized_options = [_normalize_option(option) for option in (options or [])]
    normalized_included = [_normalize_option(option) for option in (included or [])]
    normalized_excluded = [_normalize_option(option) for option in (excluded or [])]
    modifier_options = modifier_options or []

    active_modifier_label = ""
    for modifier_value, label in modifier_options:
        if modifier_value == modifier:
            active_modifier_label = label
            break

    # ── Pills: modifier pill (if active), then include/exclude value pills ──
    # Presence modifiers (NOT_NULL / IS_NULL) are mutually exclusive with value
    # pills — but the stored state guarantees they never coexist, so we render
    # both channels unconditionally.  Non-presence modifiers (INCLUDES_ALL /
    # INCLUDES_ONLY) coexist with value pills and render side by side.
    pills_children: list[Node] = []
    if active_modifier_label:
        pills_children.append(_filter_modifier_pill(modifier, active_modifier_label))
    for option in normalized_included:
        pills_children.append(_filter_value_pill(option, "include"))
    for option in normalized_excluded:
        pills_children.append(_filter_value_pill(option, "exclude"))

    pills = Div(data_search_select_pills="", class_=_PILLS_CLASS)[*pills_children]

    # ── Search box (NO name — the query is never submitted) ──
    search_attributes: list[HTMLAttribute] = [
        ("data-search-select-search", ""),
        ("placeholder", placeholder),
        ("autocomplete", "off"),
        ("class", _SEARCH_CLASS),
    ]

    # ── Options: pinned modifier rows, then value rows (pre-rendered only when
    #    there is no search_url; otherwise the JS fetches them) ──
    modifier_rows = [
        _filter_modifier_row(value, label) for value, label in modifier_options
    ]
    value_rows = (
        [
            _filter_option_row(option["value"], option["label"])
            for option in normalized_options
        ]
        if not search_url
        else []
    )

    # ── Templates the JS clones: include/exclude pills (added on click), the
    #    modifier pill (when modifiers exist), and a value row (when fetched). ──
    templates: list[Node] = [
        Template(data_search_select_template="pill-include")[
            _filter_value_pill(_BLANK_OPTION, "include")
        ],
        Template(data_search_select_template="pill-exclude")[
            _filter_value_pill(_BLANK_OPTION, "exclude")
        ],
    ]
    if modifier_options:
        templates.append(
            Template(data_search_select_template="pill-modifier")[
                _filter_modifier_pill("", "")
            ]
        )
    if search_url or free_text:
        templates.append(
            Template(data_search_select_template="row")[_filter_option_row("", "")]
        )

    children = _combobox_children(
        pills=pills,
        search_attributes=search_attributes,
        options_children=[*modifier_rows, *value_rows],
        always_visible=False,
        items_visible=items_visible,
        # FilterSelect is always multi (include/exclude pill sets).
        multi_select=True,
        templates=templates,
    )
    # The self-describe root attributes for the generic filter serializer. Only
    # filter-bar callers pass ``path``; synthetic/test callers leave it None and
    # get no extra attributes (kind is always "set" for a FilterSelect).
    widget_attributes = (
        filter_widget_attributes(path, "set") if path is not None else []
    )
    return _SearchSelect(
        widget_attributes,
        name=field_name,
        search_url=search_url,
        multi="true",
        filter_mode="true",
        free_text="true" if free_text else "false",
        always_visible="false",
        prefetch=prefetch,
        sync_url="false",
        class_=_CONTAINER_CLASS,
        id_=id or None,
        data_modifier=modifier or None,
    )[*children]


def searchselect_selected(
    values: list,
    resolver: Callable[[list], Iterable[SearchSelectOption]],
) -> list[SearchSelectOption]:
    """Resolve ``values`` into ``SearchSelectOption``s via ``resolver``.

    ``resolver(values)`` should resolve ONLY the given ids (a ``pk__in`` query)
    — never iterating all choices, so it stays cheap.
    """
    if not values:
        return []
    return [_normalize_option(option) for option in resolver(values)]
