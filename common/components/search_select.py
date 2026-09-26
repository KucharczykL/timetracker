"""Search field + dropdown select component (pure Python, domain-agnostic).

Pairs a search box with a dropdown of options. Supports single/multi select;
in multi-select, chosen items render as removable ``Pill``s, each backed by a
hidden ``<input>`` so an existing ``ModelMultipleChoiceField`` keeps validating.

This module imports only from ``common.components`` — it has no Django-forms or
``games`` knowledge. Styling is inline Tailwind utilities; behavioural hooks are
``data-*`` attributes wired up by ``ts/elements/search-select.ts`` (compiled to
``games/static/js/dist/elements/search-select.js``).

**Field id / label association**: when ``SearchSelect`` is used as a Django form
widget, the field ``id`` (e.g. ``id_related_game``) is placed on the inner
search ``<input>`` (``[data-search-select-search]``), making it a real labelable
control. ``<label for="id_X">`` therefore focuses the search box, and
``document.querySelector('#id_X').disabled`` behaves as for a native input.

**Disabling**: set ``disabled`` directly on the field id (or on the inner
``[data-search-select-search]`` input). The field box greys itself via
``DISABLED_WITHIN_CLASS`` in ``_BOX_CLASS``. Callers toggle only the control's
``disabled`` — never styles.

**ARIA combobox semantics** (issue #154): the search input is a
``role="combobox"`` with ``aria-expanded``/``aria-autocomplete``; the options
panel is a ``role="listbox"`` (``aria-multiselectable`` when multi); option and
modifier rows are ``role="option"`` with ``aria-selected``. What
``aria-selected`` means depends on the mode: in single-select the JS mirrors
the keyboard highlight into it (the APG list-autocomplete convention); in
multi/filter mode — where the listbox is ``aria-multiselectable`` and the
attribute conveys set membership — it is true for rows whose value has a pill
(or the active modifier row), the server pre-renders that state, and the
keyboard highlight is conveyed by ``aria-activedescendant`` alone. The
id-based wiring (``aria-controls`` on the input, stable ``id``s on the panel
and rows, and ``aria-activedescendant`` tracking the highlight) is assigned by
the JS at init — never server-side, because the nested filter builder clones
whole ``<search-select>`` prototypes and server-rendered ids would be
duplicated across clones.

Option sourcing follows two axes. *Population*: options are either rendered
inline up front (``options=``, no ``search_url``) or fetched from ``search_url``.
*Completeness*: without a ``search_url`` the inline set is the whole dataset and
filtering is purely client-side; with a ``search_url`` the loaded rows are a
window, so the JS filters the loaded rows instantly on each keystroke while
issuing a debounced server request for the rest. ``prefetch`` (rows to load on
first open, ``0`` = none) seeds that window so the panel is populated before the
user types.
"""

import json
from collections.abc import Callable, Iterable, Sequence
from enum import Enum
from typing import Literal, NamedTuple, TypedDict

from common.components.core import Attributes, Child, HTMLAttribute, Node
from common.components.custom_elements import (
    DROPDOWN_ITEM_SHAPE,
    Dropdown,
    DropdownPanel,
    _Dropdown,
    _SearchSelect,
)
from common.components.primitives import (
    DISABLED_WITHIN_CLASS,
    MICRO_LABEL_CLASS,
    Button,
    ControlButton,
    Div,
    FilterWidgetPath,
    Icon,
    Input,
    Pill,
    Span,
    Template,
    filter_widget_attributes,
)


class LiteralParam(TypedDict):
    """A value the server states at render time."""

    value: str


class FieldParam(TypedDict):
    """The name of a sibling form field, read when used."""

    field: str


#: One mapping, read by the search query and by the create POST.
#: A field source is a dependency: a change to it searches again.
type ParamSources = dict[str, LiteralParam | FieldParam]


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

# FilterSelect's two visual personalities: "field" is the bordered form-field
# look (the nested builder's leaf rows); "panel" is the GitHub-label-picker look for widgets
# hosted inside a ComboboxDropdown dialog (pills row above the field box,
# always-visible statically-flowing options).
type FilterSelectLayout = Literal["field", "panel"]


class OptionGroup(NamedTuple):
    """A labelled run of options for a grouped single-select panel.

    Passed as ``SearchSelect(option_groups=[...])`` (mutually exclusive with
    ``options=``); the widget renders a non-selectable header row before each
    group's option rows. Used by the filter builder's add-criterion field picker
    (#191), which groups fields by criterion kind.
    """

    label: str
    options: list[SearchSelectOption]


# One bordered field box, every personality.
_BOX_CLASS = (
    "flex flex-wrap items-center gap-1 px-3 py-1 min-h-control rounded-base "
    "text-type-body "
    "bg-neutral-secondary-medium border border-default-medium "
    "focus-within:border-brand focus-within:ring-1 focus-within:ring-brand "
    f"{DISABLED_WITHIN_CLASS}"
)
# Anchors the standalone panel and drop-down.
_CONTAINER_CLASS = "relative block"
_PILLS_CLASS = "contents"
# Under 16px text, iOS zooms on focus.
_SEARCH_CLASS = (
    "flex-1 min-w-[8rem] border-0 p-0 bg-transparent text-type-input text-heading "
    "focus:ring-0 focus:outline-hidden placeholder:text-body "
    "disabled:cursor-not-allowed"
)
# The #450 draft cue, at rest only.
_UNCOMMITTED_BOX_CLASS = "not-focus-within:[[data-uncommitted]_&]:border-dashed"
# The loose text reads like a placeholder — muted (the audited placeholder
# token) + italic.
_UNCOMMITTED_SEARCH_CLASS = (
    "[[data-uncommitted]:not(:focus-within)_&]:text-body "
    "[[data-uncommitted]:not(:focus-within)_&]:italic"
)
# The pencil glyph: hidden except when its container is uncommitted at rest.
# Icon() drops the snippet's baked color classes, so text-body must ride here
# (sizing stays Icon()'s default ICON_SIZE_CLASS).
_MARKER_ICON_CLASS = "hidden text-body [[data-uncommitted]:not(:focus-within)_&]:block"
# ml-auto ends the row; peer-disabled hides it.
_CLEAR_BUTTON_CLASS = (
    "ml-auto -mr-1 shrink-0 size-8 inline-flex items-center justify-center "
    "rounded text-body hover:text-heading hover:bg-neutral-tertiary-medium "
    "cursor-pointer peer-disabled:hidden"
)
#: The standalone panel hangs below the box.
_STANDALONE_PANEL_CLASS = "top-full left-0 right-0 mt-1"
#: The dialog is this listbox's panel.
_DIALOG_LISTBOX_CLASS = "mt-2 overflow-y-auto scroll-py-2"
#: Picker rows wear the menu item look.
#: Literal, so Tailwind sees it.
_ROW_CLASS = (
    f"{DROPDOWN_ITEM_SHAPE} text-type-body "
    "data-[search-select-highlighted]:bg-neutral-tertiary-medium "
    "data-[search-select-highlighted]:text-heading"
)
_ROW_WITH_ACTIONS_CLASS = f"{_ROW_CLASS} flex items-center justify-between"
_ROW_ACTIONS_CLASS = "flex gap-1 ml-2 shrink-0"
#: -my-1 keeps row height; radius scales down.
_ROW_ACTION_SHAPE = (
    "size-6 -my-1 inline-flex items-center justify-center rounded-sm "
    "text-type-micro font-bold text-body cursor-pointer"
)
_ROW_ACTION_CLASS = (
    f"{_ROW_ACTION_SHAPE} hover:text-heading hover:bg-neutral-quaternary-medium"
)
_ROW_REMOVE_ACTION_CLASS = (
    f"{_ROW_ACTION_SHAPE} hover:text-fg-danger-strong hover:bg-danger-soft"
)
_NO_RESULTS_CLASS = "px-4 py-2 text-type-body italic text-body hidden"
# A non-selectable group header in a grouped panel. role="presentation" keeps it
# out of the combobox's option semantics; carrying no data-search-select-option
# excludes it from keyboard nav, client-side filtering, and selection. The JS
# hides a header whose whole run of following option rows is filtered out.
_GROUP_HEADER_CLASS = f"px-4 pt-2 pb-1 {MICRO_LABEL_CLASS} text-body"

# Approximate rendered height of one option row (px-3 py-2 text-type-body) in rem,
# used to derive the panel's max-height from items_visible.
_ROW_HEIGHT_REM = 2.25

# Default number of rows to fetch on first focus when a search_url is set.
# Shared by filter and form widgets so the dropdown is populated for keyboard
# navigation as soon as the user opens it.
DEFAULT_PREFETCH = 20


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


def _option_role_attributes(selected: bool = False) -> list[HTMLAttribute]:
    """The ARIA attributes every listbox row carries (issue #154): value rows
    and modifier rows alike are ``role="option"`` with an ``aria-selected``
    state, so the listbox exposes only option/presentation children."""
    return [("role", "option"), ("aria-selected", "true" if selected else "false")]


def _hidden_input(name: str, value) -> Node:
    return Input(type="hidden", name=name, value=str(value))


def _label_slot(text: str, *, extra_class: str = "") -> Node:
    """A ``<span data-search-select-label>`` holding a row/pill's visible label. JS fills this
    one node when cloning the shape from a ``<template>``, so labels are the only
    thing the JS sets — all classes and structure stay server-side."""
    return Span(data_search_select_label="", class_=extra_class or None)[text]


# A placeholder option for rendering template prototypes (JS overwrites it).
_BLANK_OPTION: SearchSelectOption = {"value": "", "label": "", "data": {}}


class RowKind(Enum):
    """The hook the element reads."""

    OPTION = "option"
    #: Pinned; the text filter never hides it.
    MODIFIER = "modifier"
    #: Hidden until no label equals the query.
    CREATE = "create"


def _option_row(
    option: SearchSelectOption,
    kind: RowKind = RowKind.OPTION,
    *,
    selected: bool = False,
    actions: Sequence[Node] = (),
) -> Node:
    """Every picker row, in one look.

    A create row carries its own hook, not an option's:
    each answer empties the option rows, and it would
    vanish mid-keystroke.
    """
    label: Node
    if kind is RowKind.CREATE:
        attributes: list[HTMLAttribute] = [
            ("data-search-select-create", ""),
            ("role", "option"),
            ("aria-selected", "false"),
            ("hidden", ""),
        ]
        label = Span(data_label="")
    elif kind is RowKind.MODIFIER:
        attributes = [
            *_option_role_attributes(selected),
            ("data-search-select-modifier-option", str(option["value"])),
            ("data-label", option["label"]),
        ]
        label = Span()[option["label"]]
    else:
        attributes = [
            *_data_attributes(option["data"]),
            *_option_role_attributes(selected),
            ("data-search-select-option", ""),
            ("data-value", str(option["value"])),
            ("data-label", option["label"]),
        ]
        label = _label_slot(
            option["label"], extra_class="truncate min-w-0" if actions else ""
        )
    if not actions:
        return Div(attributes, class_=_ROW_CLASS)[label]
    return Div(attributes, class_=_ROW_WITH_ACTIONS_CLASS)[
        label, Span(class_=_ROW_ACTIONS_CLASS)[*actions]
    ]


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


class _ComboboxLayout(NamedTuple):
    """Where a combobox lives, declared once."""

    container_class: str
    #: None: the hosting dialog is the panel.
    panel_class: str | None
    #: The <drop-down> owns the list's visibility.
    menu_target: bool


def _combobox_children(
    *,
    pill_nodes: list[Node],
    search_attributes: Attributes,
    options_children: list[Node],
    always_visible: bool,
    items_visible: int,
    multi_select: bool = False,
    layout: _ComboboxLayout,
    templates: list[Node] | None = None,
    no_results_text: str = "No results",
    create_row: Node | None = None,
    marker: list[Node] | None = None,
    clear_button: Node | None = None,
    box_class: str = _BOX_CLASS,
) -> list[Node]:
    """Build and return the shared combobox interior nodes.

    Returns the field box, the options panel and any templates.

    The shell owns the ARIA combobox pattern (issue #154): the search input is
    the combobox, the options panel the listbox. ``aria-controls`` /
    ``aria-activedescendant`` and the ids they reference are wired by the JS at
    init (see module docstring); the JS also keeps ``aria-expanded`` in sync
    with the panel's visibility.

    ``layout`` places the list; pills always sit in the box.
    ``box_class`` styles the field box.
    ``clear_button`` and ``marker`` follow the input inside it.
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
    )[no_results_text]
    panel_children = [*options_children, no_results]
    if create_row:
        panel_children.append(create_row)
    listbox_attributes: list[HTMLAttribute] = [
        ("data-search-select-options", ""),
        ("role", "listbox"),
        # Else Chrome makes the scroller tabbable.
        ("tabindex", "-1"),
        ("style", f"max-height: {items_visible * _ROW_HEIGHT_REM:.2f}rem"),
    ]
    if multi_select:
        listbox_attributes.append(("aria-multiselectable", "true"))
    options_panel: Node
    if layout.panel_class is None:
        options_panel = Div(listbox_attributes, class_=_DIALOG_LISTBOX_CLASS)[
            *panel_children
        ]
    else:
        panel_attributes: list[HTMLAttribute] = [("data-search-select-panel", "")]
        if layout.menu_target:
            panel_attributes.append(("data-menu", ""))
        if layout.menu_target or not always_visible:
            panel_attributes.append(("hidden", ""))
        options_panel = DropdownPanel(
            panel_attributes,
            width="w-full",
            class_=layout.panel_class,
            content_attributes=listbox_attributes,
            content_class="scroll-py-2",
        )[panel_children]
    pills = Div(data_search_select_pills="", class_=_PILLS_CLASS)[*pill_nodes]
    box = Div(data_search_select_box="", class_=box_class)[
        pills,
        search,
        *([clear_button] if clear_button else []),
        *(marker or []),
    ]
    return [box, options_panel, *(templates or [])]


def SearchSelect(
    *,
    name: str,
    selected: list[SearchSelectOption] | None = None,
    options: list[SearchSelectOption] | None = None,
    option_groups: list[OptionGroup] | None = None,
    search_url: str = "",
    params: ParamSources | None = None,
    create_url: str = "",
    csrf: str = "",
    commit_sole_option: bool = False,
    multi_select: bool = False,
    always_visible: bool = False,
    items_visible: int = 5,
    items_scroll: int = 10,
    prefetch: int = 0,
    placeholder: str = "Search…",
    id: str = "",
    sync_url: bool = False,
    autofocus: bool = False,
    host_dropdown: bool = False,
    dynamic_options: bool = False,
    committed_marker: bool = True,
    panel: bool = False,
    clearable: bool = True,
    clear_description_id: str | None = None,
) -> Node:
    """Render the search-select widget. See module docstring for the contract.

    ``panel=True`` is the panel-hosted personality: an always-visible widget
    using the module's static panel classes, for content placed inside a
    :func:`ComboboxDropdown` dialog (which owns open/close/dismiss). The same
    composition :func:`PresetSelect` and a panel-layout :func:`FilterSelect`
    build by hand — the hosting dialog, not the widget, is the disclosure.

    ``host_dropdown`` (issue #348) wraps the widget in
    ``<drop-down behavior="inline-combobox">`` so its panel opens/closes/positions/
    dismisses through the shared attachMenu engine (the widget's own search input
    is the trigger — focus opens). The add-form comboboxes
    (``games/forms.py`` :class:`SearchSelectWidget`) and the filter-builder field
    picker (:func:`FilterFieldPicker`) pass it; the preset picker uses its own
    ``behavior="combobox"`` host, and bare test mounts leave it ``False``.

    Pass ``option_groups`` instead of ``options`` to render a grouped panel
    (non-selectable header rows before each group's options); the two are mutually
    exclusive and grouping is only meaningful for the inline (no ``search_url``)
    complete-set case.

    ``dynamic_options`` ships the row ``<template>`` even without a ``search_url``,
    so the client can swap the inline option set via the element's ``setOptions``
    (the field-comparison right operand recomputes its list per left column +
    operator, #282). Ignored when a ``search_url`` already ships the template.

    ``committed_marker`` (issue #450, single-select only, default on): renders
    the uncommitted-state cue nodes — a pencil glyph plus a permanently sr-only
    ``role="status"`` span the JS wires via ``aria-describedby`` and fills when
    the box holds text with no committed value. The span's presence is the JS's
    opt-in signal for toggling ``data-uncommitted`` (the visual cue); pass
    ``False`` to opt a widget out. Every single-select flavor built through
    this function gets the cue (form widgets, the filter builder's field
    picker, the comparison column pickers); ``PresetSelect`` and
    ``FilterSelect`` build their own markup and are structurally unaffected —
    correctly so for the preset picker, whose pick is a command and whose box
    clears by design.

    ``clearable``: a trailing × empties query and value.
    ``clear_description_id``: the ×'s ``aria-describedby`` target.
    """
    if panel:
        always_visible = True
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

    clear_button: Node | None = None
    if clearable:
        search_attrs.append(("class", "peer"))
        clear_button = Button(
            type="button",
            data_search_select_clear="",
            aria_label="Clear",
            title="Clear",
            aria_describedby=clear_description_id,
            hidden=not selected,
            class_=_CLEAR_BUTTON_CLASS,
        )[Icon("x-mark", [("aria-hidden", "true"), ("class", "size-4")])]

    layout = (
        _DIALOG_LAYOUT
        if panel
        else (_INLINE_LAYOUT if host_dropdown else _STANDALONE_LAYOUT)
    )

    # ── Options panel (pre-rendered only when there is no search_url) ──
    if search_url:
        option_rows: list[Node] = []
    elif option_groups:
        option_rows = _grouped_option_rows(option_groups)
    else:
        # In the multi (aria-multiselectable) listbox aria-selected conveys
        # membership, so pre-render it for already-selected values. Single-select
        # keeps the highlight-driven aria-selected, owned by the JS.
        selected_values = (
            {str(option["value"]) for option in selected} if multi_select else set()
        )
        option_rows = [
            _option_row(option, selected=str(option["value"]) in selected_values)
            for option in options
        ]

    # ── Templates the JS clones: a row when results are fetched (or when the
    #    client swaps the inline option set via ``setOptions``), a pill when
    #    multi-select adds chosen items. ──
    templates: list[Node] = []
    if search_url or dynamic_options:
        templates.append(
            Template(data_search_select_template="row")[_option_row(_BLANK_OPTION)]
        )
    if multi_select:
        templates.append(
            Template(data_search_select_template="pill")[
                Pill(label="", value="", removable=True, label_slot=True)
            ]
        )

    # ── Committed-marker cue nodes (#450, single-select only): the pencil
    #    "draft" glyph (visual, CSS-toggled off data-uncommitted) and the empty
    #    sr-only status span the JS fills ("No option selected") and points
    #    aria-describedby at. The id is JS-assigned, never rendered here —
    #    the filter builder clones whole <search-select> prototypes (#154). ──
    marker: list[Node] | None = None
    show_marker = committed_marker and not multi_select
    if show_marker:
        # The cue's state utilities ride the search box only on opted-in
        # widgets, so every other flavor's markup stays byte-identical.
        search_attrs.append(("class", _UNCOMMITTED_SEARCH_CLASS))
        marker = [
            Icon(
                "edit",
                [
                    ("data-search-select-marker", ""),
                    ("aria-hidden", "true"),
                    ("class", _MARKER_ICON_CLASS),
                ],
            ),
            Span(data_search_select_status="", role="status", class_="sr-only"),
        ]

    children = _combobox_children(
        create_row=_option_row(_BLANK_OPTION, RowKind.CREATE) if create_url else None,
        pill_nodes=pills_children,
        search_attributes=search_attrs,
        options_children=option_rows,
        always_visible=always_visible,
        items_visible=items_visible,
        multi_select=multi_select,
        templates=templates,
        layout=layout,
        marker=marker,
        clear_button=clear_button,
        box_class=f"{_BOX_CLASS} {_UNCOMMITTED_BOX_CLASS}"
        if show_marker
        else _BOX_CLASS,
    )
    widget = _SearchSelect(
        # The <search-select> element itself is the drop-down's [data-toggle]: it
        # is the positioning anchor (its field box) and the focus/typing trigger.
        # No id/aria-controls/aria-expanded stamp — the widget owns those at init.
        [("data-toggle", "")] if host_dropdown else [],
        name=name,
        search_url=search_url,
        params=json.dumps(params) if params else "",
        create_url=create_url,
        csrf=csrf,
        commit_sole_option="true" if commit_sole_option else "false",
        multi="true" if multi_select else "false",
        filter_mode="false",
        free_text="false",
        always_visible="true" if always_visible else "false",
        prefetch=prefetch,
        sync_url="true" if sync_url else "false",
        class_=layout.container_class,
    )[*children]
    if not host_dropdown:
        return widget
    # block (not the generic inline-flex) so the field keeps its full form-column
    # width. attachMenu positions the [data-menu] panel fixed relative to the
    # <search-select> anchor; the inline-combobox behavior wires the rest.
    return _Dropdown(
        class_="block",
        placement="bottom-start",
        submenu="false",
        behavior="inline-combobox",
    )[widget]


def _filter_value_pill(
    option: SearchSelectOption, kind: Literal["include", "exclude"]
) -> Node:
    """An include (✓) or exclude (✗) value pill."""
    return Pill(
        _data_attributes(option["data"]),
        label=option["label"],
        removable=True,
        label_slot=True,
        kind=kind,
        data_value=str(option["value"]),
        data_label=option["label"],
        data_search_select_type=kind,
    )


def _filter_modifier_pill(modifier_value: str, label: str) -> Node:
    """The lone, sticky modifier pill (e.g. "(Any)"/"(None)")."""
    return Pill(
        label=label,
        removable=True,
        label_slot=True,
        kind="modifier",
        data_search_select_modifier=modifier_value,
    )


def _row_action(action: str, symbol: Child, title: str, *, css: str) -> Node:
    """A trailing row button, never tabbable."""
    return Button(
        type="button",
        tabindex="-1",
        data_search_select_action=action,
        class_=css,
        title=title,
        aria_label=title,
    )[symbol]


def _filter_option_row(value: str | int, label: str, *, selected: bool = False) -> Node:
    """A value row; ``selected``: a pill names it."""
    return _option_row(
        {"value": value, "label": label, "data": {}},
        selected=selected,
        actions=[
            _row_action("include", "+", "Include", css=_ROW_ACTION_CLASS),
            _row_action("exclude", "−", "Exclude", css=_ROW_ACTION_CLASS),
        ],
    )


def _filter_modifier_row(
    modifier_value: str, label: str, *, selected: bool = False
) -> Node:
    """A pinned pseudo-option row, e.g. "(Any)"."""
    return _option_row(
        {"value": modifier_value, "label": label, "data": {}},
        RowKind.MODIFIER,
        selected=selected,
    )


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
    layout: FilterSelectLayout = "field",
    search_aria_label: str = "",
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

    The default ``layout="field"`` hosts itself in
    ``<drop-down behavior="inline-combobox">`` so its panel opens/closes/positions/
    dismisses through the shared attachMenu engine (the search input is the
    trigger — focus opens), mirroring :func:`SearchSelect` ``host_dropdown=True``.

    ``layout="panel"`` renders the same widget in the panel personality (see
    :data:`FilterSelectLayout`): pills in their own wrap row above the
    field box, options always visible and flowing statically —
    for hosting inside a :func:`ComboboxDropdown` dialog (which supplies the
    drop-down at that level, so the panel layout stays bare here). State logic,
    templates, every ``data-search-select-*`` hook and the serializer DOM
    contract are identical to the field layout.

    ``search_aria_label`` names the search input (``aria-label``) — required
    by panel callers, whose visible facet label lives on the dropdown trigger
    rather than a ``<label>`` next to the widget.
    """
    panel_layout = layout == "panel"
    # The field layout hosts itself in <drop-down behavior="inline-combobox"> so its
    # panel uses the shared attachMenu engine (the same hooks SearchSelect(host_dropdown)
    # uses); the panel layout is hosted a level up by ComboboxDropdown, so it stays bare.
    field_host = not panel_layout
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

    combobox_layout = _DIALOG_LAYOUT if panel_layout else _INLINE_LAYOUT

    # ── Search box (NO name — the query is never submitted) ──
    search_attributes: list[HTMLAttribute] = [
        ("data-search-select-search", ""),
        ("placeholder", placeholder),
        ("autocomplete", "off"),
        ("class", _SEARCH_CLASS),
    ]
    if search_aria_label:
        search_attributes.append(("aria-label", search_aria_label))

    # ── Options: pinned modifier rows, then value rows (pre-rendered only when
    #    there is no search_url; otherwise the JS fetches them) ──
    modifier_rows = [
        _filter_modifier_row(value, label, selected=value == modifier)
        for value, label in modifier_options
    ]
    # aria-selected means membership here (the listbox is aria-multiselectable):
    # a row is selected when an include or exclude pill exists for its value.
    pilled_values = {
        str(option["value"]) for option in [*normalized_included, *normalized_excluded]
    }
    value_rows = (
        [
            _filter_option_row(
                option["value"],
                option["label"],
                selected=str(option["value"]) in pilled_values,
            )
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
        pill_nodes=pills_children,
        search_attributes=search_attributes,
        options_children=[*modifier_rows, *value_rows],
        always_visible=panel_layout,
        items_visible=items_visible,
        # FilterSelect is always multi (include/exclude pill sets).
        multi_select=True,
        templates=templates,
        layout=combobox_layout,
    )
    # The self-describe root attributes for the generic filter serializer. Only
    # Filter-layer callers pass ``path``; synthetic/test callers leave it None and
    # get no extra attributes (kind is always "set" for a FilterSelect).
    widget_attributes = (
        filter_widget_attributes(path, "set") if path is not None else []
    )
    if field_host:
        # The <search-select> element itself is the drop-down's [data-toggle]: its
        # field box is the positioning anchor and its search input is the trigger.
        widget_attributes = [("data-toggle", ""), *widget_attributes]
    widget = _SearchSelect(
        widget_attributes,
        name=field_name,
        search_url=search_url,
        multi="true",
        filter_mode="true",
        free_text="true" if free_text else "false",
        always_visible="true" if panel_layout else "false",
        prefetch=prefetch,
        sync_url="false",
        class_=combobox_layout.container_class,
        id_=id or None,
        data_modifier=modifier or None,
    )[*children]
    if not field_host:
        return widget
    # block (not the generic inline-flex) so the field keeps its full column width;
    # attachMenu positions the [data-menu] panel fixed relative to the anchor.
    return _Dropdown(
        class_="block",
        placement="bottom-start",
        submenu="false",
        behavior="inline-combobox",
    )[widget]


# ── Panel personality styling ───────────────────────────
# Dialog-hosted comboboxes: field box above a list.
_PANEL_CONTAINER_CLASS = "block text-type-body"

# Absolute below the box; no drop-down.
_STANDALONE_LAYOUT = _ComboboxLayout(
    container_class=_CONTAINER_CLASS,
    panel_class=_STANDALONE_PANEL_CLASS,
    menu_target=False,
)
# Pinned by the hosting drop-down.
_INLINE_LAYOUT = _ComboboxLayout(
    container_class=_CONTAINER_CLASS, panel_class="", menu_target=True
)
# Inside a dialog's padded surface.
_DIALOG_LAYOUT = _ComboboxLayout(
    container_class=_PANEL_CONTAINER_CLASS, panel_class=None, menu_target=False
)

# Fetch-on-open window. A preset collection is per-user and small; one fetch
# returns it all, and the type-to-filter narrows client-side.
_PRESET_PREFETCH = 100


def _preset_option_row(option: SearchSelectOption) -> Node:
    """A preset row with a remove action."""
    return _option_row(
        option,
        actions=[
            _row_action(
                "delete",
                Icon("x-mark", [("aria-hidden", "true"), ("class", "size-4")]),
                "Remove preset",
                css=_ROW_REMOVE_ACTION_CLASS,
            )
        ],
    )


def PresetSelect(*, api_url: str, mode: str, items_visible: int = 8) -> Node:
    """The preset-picker personality of the combobox shell (issue #297).

    An always-visible single-select whose options are fetched from the preset
    API (``?mode=`` scoped) on every open — the hosting dropdown's ``combobox``
    behavior calls ``refetchOptions()`` on ``dropdown:show``, so the list is
    server-fresh after saves and deletes with no refresh plumbing. A pick emits
    the standard ``search-select:change`` whose ``last.data.filter`` carries the
    preset's filter JSON; the consumer decides what a pick means (the builder
    loads it into the tree, the filter bar navigates). The pick is transient —
    consumers call ``clearSelection()`` after handling it.
    """
    search_attributes: list[HTMLAttribute] = [
        ("data-search-select-search", ""),
        ("placeholder", "Filter presets…"),
        ("autocomplete", "off"),
        ("class", _SEARCH_CLASS),
    ]
    templates: list[Node] = [
        Template(data_search_select_template="row")[_preset_option_row(_BLANK_OPTION)]
    ]
    children = _combobox_children(
        pill_nodes=[],
        search_attributes=search_attributes,
        options_children=[],
        always_visible=True,
        items_visible=items_visible,
        templates=templates,
        layout=_DIALOG_LAYOUT,
        no_results_text="No saved presets",
    )
    return _SearchSelect(
        name="preset",
        search_url=f"{api_url}?mode={mode}",
        multi="false",
        filter_mode="false",
        free_text="false",
        always_visible="true",
        prefetch=_PRESET_PREFETCH,
        sync_url="false",
        class_=_DIALOG_LAYOUT.container_class,
    )[*children]


def ComboboxDropdown(
    *,
    label: str,
    content: Node,
    id: str,
    ghost: bool = False,
    config: dict[str, str] | None = None,
    panel_width: str = "w-72",
) -> Node:
    """A "Label ▾" trigger + combobox dialog, composed from the two shared
    primitives: ``<drop-down>`` owns the trigger,
    open/close, outside-click, Escape and the panel surface; the panel hosts
    ``content`` (a combobox-shell widget such as :func:`PresetSelect` or a
    panel-layout :func:`FilterSelect`). The ``combobox`` client behavior opts
    out of the menu's item navigation, focuses the search box on open, and
    refetches its options on every show.

    ``ghost=True`` renders the trigger with the transparent-until-hover
    ``ControlButton`` variant (the quick filter bar's compact facet look);
    the default is the filled gray button. The dialog's accessible name is
    always ``label`` — the trigger text names the panel it opens.
    ``panel_width`` sets the dialog width class: the default ``w-72`` suits
    list-shaped content; content with an intrinsic width (a calendar) passes
    ``w-auto``.
    """
    trigger = ControlButton(
        color="gray",
        variant="ghost" if ghost else "filled",
        aria_haspopup="dialog",
    )[
        label,
        Icon("arrowdown", size="h-3 w-3"),
    ].as_element()
    # A dialog; the widget brings listbox semantics.
    panel = DropdownPanel(role="dialog", aria_label=label, width=panel_width)[content]
    return Dropdown(
        trigger_element=trigger,
        target_element=panel,
        id=id,
        behavior="combobox",
        config=config,
    )


def LoadPresetDropdown(
    *, api_url: str, mode: str, id: str = "load-preset-dropdown", ghost: bool = False
) -> Node:
    """The "Load preset ▾" picker: a :func:`ComboboxDropdown`
    hosting a :func:`PresetSelect`. ``ghost`` selects the quiet trigger (the
    quick filter bar); the builder toolbar keeps the filled gray default.

    The wrapper carries ``data-preset-picker`` — the discriminator consumers use
    to tell the picker's ``search-select:change``/``search-select:action`` events
    apart from other widgets', and the hook whose ``close()`` they call after a
    pick.
    """
    return ComboboxDropdown(
        label="Load preset",
        content=PresetSelect(api_url=api_url, mode=mode),
        id=id,
        ghost=ghost,
        config={"data_preset_picker": ""},
    )


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
